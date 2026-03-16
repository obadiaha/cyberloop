"""
ADK-based interviewer using Runner.run_live() for bidirectional streaming.

Replaces the manual Gemini Live API session management in interviewer.py
with ADK's built-in run_live() pattern (from bidi-demo).

The WebSocket handler translates ADK Events into our existing frontend
protocol so the React UI doesn't need major changes.
"""

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google.adk.agents.live_request_queue import LiveRequestQueue
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.adk_agent import create_interview_agent
from agent.session import InterviewState, SessionManager, SessionStatus
from agent.prompts import build_system_prompt
from agent.tools import get_question_tree, end_interview as end_interview_fn

logger = logging.getLogger(__name__)

APP_NAME = "cyberloop"

# Session timing constants
INTERVIEW_HARD_CAP_SECONDS = 20 * 60  # 20 minutes
INTERVIEW_SOFT_WRAP_SECONDS = 15 * 60  # 15 minutes
CEILING_CONSECUTIVE_SAME = 3


async def run_adk_session(
    websocket: WebSocket,
    state: InterviewState,
    session_manager: SessionManager,
) -> None:
    """
    Run an interview session using ADK's run_live().

    This replaces CyberLoopAgent.run_session() with the ADK pattern:
    - LiveRequestQueue for upstream (browser -> model)
    - Runner.run_live() for downstream (model -> browser)
    - FunctionTool closures for interview tools
    """

    # Build system prompt
    if state.config.mode == "behavioral":
        domain = "behavioral_bank"
    else:
        domain = state.current_domain or (
            state.config.domains[0] if state.config.domains else "incident_response"
        )
    question_tree = get_question_tree(domain)

    # In coding mode, use only the IP extraction question (de_007) for demo
    if state.config.mode == "coding" and question_tree:
        import copy
        question_tree = copy.deepcopy(question_tree)
        demo_q = [q for q in question_tree.get("root_questions", []) if q.get("id") == "de_007"]
        if demo_q:
            question_tree["root_questions"] = demo_q
            logger.info("Coding mode: using de_007 (IP extraction) for demo")
        else:
            coding_qs = [q for q in question_tree.get("root_questions", []) if q.get("category") == "hands_on_coding"]
            if coding_qs:
                question_tree["root_questions"] = coding_qs
                logger.info("Coding mode: filtered tree to %d hands-on questions", len(coding_qs))

    system_prompt = build_system_prompt(
        company=state.config.company,
        level=state.config.level,
        mode=state.config.mode,
        domains=state.config.domains,
        question_tree=question_tree,
    )

    # Event queue for tool side-effect messages -> WebSocket
    event_queue: asyncio.Queue = asyncio.Queue()

    # Create per-session ADK agent with tools bound to this session's state
    agent = create_interview_agent(state, session_manager, system_prompt, event_queue)

    # ADK session service and runner (created per connection)
    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)

    user_id = f"user-{state.session_id}"
    adk_session_id = state.session_id

    # Create ADK session
    await session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=adk_session_id
    )

    # RunConfig for native audio bidi streaming
    run_config = RunConfig(
        streaming_mode=StreamingMode.BIDI,
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Charon",
                )
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                prefix_padding_ms=20,
                silence_duration_ms=2000,
            ),
        ),
        # Extend session past 2-min audio+video limit by compressing old context
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow(
                target_tokens=20000,
            ),
        ),
        # Allow reconnection if WebSocket drops (~10 min connection lifetime)
        session_resumption=types.SessionResumptionConfig(
            handle=None,
        ),
    )

    live_request_queue = LiveRequestQueue()

    # Shared mutable state for the concurrent tasks
    ctx = {
        "running": True,
        "interview_start_time": time.time(),
        "soft_wrap_sent": False,
        "hard_cap_sent": False,
        "opening_complete": False,
        "agent_speaking": False,
        "output_text_buffer": "",
        "input_text_buffer": "",
        "transcript_buffer": [],
    }

    # Activate session
    state.status = SessionStatus.ACTIVE
    session_manager.update_session(state)

    # Notify browser that session is active
    await _send_ws(websocket, {
        "type": "session_started",
        "session_id": state.session_id,
        "company": state.config.company,
        "mode": state.config.mode,
        "domains": state.config.domains,
    })

    # -------------------------------------------------------------------
    # Upstream: Browser WebSocket -> LiveRequestQueue
    # -------------------------------------------------------------------
    async def upstream_task():
        await asyncio.sleep(0.2)  # Let downstream start first

        # Check if this is a reconnect (session already has exchanges)
        if state.exchanges:
            # Build transcript summary for context recovery
            transcript_lines = []
            for ex in state.exchanges[-5:]:  # Last 5 exchanges for context
                if ex.question:
                    transcript_lines.append(f"You asked: {ex.question}")
                if ex.response:
                    transcript_lines.append(f"Candidate said: {ex.response}")
            transcript_summary = "\n".join(transcript_lines)
            opening = (
                f"RESUME. The interview was interrupted. Here is the recent transcript:\n"
                f"{transcript_summary}\n\n"
                f"Continue from where you left off. Do NOT restart the interview. "
                f"Do NOT re-greet the candidate. Pick up naturally from your last "
                f"question or ask the next follow-up."
            )
            logger.info("Resuming session %s with %d prior exchanges", state.session_id, len(state.exchanges))
        else:
            if state.config.mode == "coding":
                opening = (
                    "BEGIN. Say exactly: 'Hi, welcome to your coding interview.' "
                    "Then call get_next_question(direction='next'). "
                    "After the tool returns, say ONLY: 'The challenge is in your panel. "
                    "Write a Python script, share your screen when ready.' "
                    "STOP. Do NOT read the question aloud. Do NOT explain further. "
                    "The candidate can read the question on screen."
                )
            else:
                opening = (
                    "BEGIN. Greet the candidate briefly (e.g. 'Hi, let's get started') "
                    "and then IMMEDIATELY call get_next_question(direction='next') to get your first question. "
                    "Do NOT make up a question from the question tree. You MUST use the tool. "
                    "Do not give a long introduction."
                )
        live_request_queue.send_content(
            types.Content(parts=[types.Part(text=opening)])
        )
        logger.info("Sent opening prompt for session %s", state.session_id)

        while ctx["running"]:
            try:
                raw = await websocket.receive_text()
                msg = json.loads(raw)

                if msg.get("type") == "audio":
                    # Don't forward mic until agent's opening is done
                    if not ctx["opening_complete"]:
                        continue
                    # Pause audio during tool calls to prevent 1008 errors
                    if getattr(state, "_tool_call_pending", False):
                        continue

                    if not ctx.get("_audio_logged"):
                        logger.info("First audio chunk received from client for %s", state.session_id)
                        ctx["_audio_logged"] = True

                    audio_bytes = base64.b64decode(msg["data"])
                    live_request_queue.send_realtime(
                        types.Blob(
                            mime_type="audio/pcm;rate=16000",
                            data=audio_bytes,
                        )
                    )

                elif msg.get("type") == "screen_frame":
                    # Store frame but DON'T send to Gemini automatically.
                    # Screen frames sent as live content trigger the model to
                    # speak even when no one is talking. Instead, store the
                    # latest frame and inject it only when scoring via tool call.
                    ctx["latest_screen_frame"] = base64.b64decode(msg["data"])
                    logger.info("Screen frame stored (%d bytes)", len(msg.get("data", "")))

                elif msg.get("type") == "webcam_frame":
                    state.webcam_active = True
                    frame_bytes = base64.b64decode(msg["data"])
                    image_part = types.Part(
                        inline_data=types.Blob(
                            data=frame_bytes, mime_type="image/jpeg"
                        )
                    )
                    live_request_queue.send_content(
                        types.Content(
                            parts=[
                                types.Part(
                                    text=(
                                        "[WEBCAM FRAME. Analyze the candidate's body language, "
                                        "posture, eye contact, and confidence level. Do NOT "
                                        "comment out loud. Instead, call log_body_language() "
                                        "with your observations. Only call it when you notice "
                                        "something notable (confident posture, nervous fidgeting, "
                                        "good eye contact, looking away frequently, etc). "
                                        "The ONLY exception for speaking: if the candidate "
                                        "appears extremely nervous, briefly offer encouragement.]"
                                    )
                                ),
                                image_part,
                            ]
                        )
                    )

                elif msg.get("type") == "code_update":
                    code = msg.get("code", "")
                    if code.strip():
                        ctx["latest_code"] = code
                        state._latest_code = code

                elif msg.get("type") == "code_result":
                    state._latest_code = msg.get("code", "")
                    state._latest_output = msg.get("stdout", "")
                    state._latest_stderr = msg.get("stderr", "")
                    state._latest_exit_code = msg.get("exit_code", -1)

                    # Pause audio while sending to prevent 1008
                    state._tool_call_pending = True

                    # Send text output first (fast response)
                    output_text = state._latest_output or state._latest_stderr or "(no output)"
                    status = "SUCCESS" if state._latest_exit_code == 0 else f"FAILED (exit {state._latest_exit_code})"
                    live_request_queue.send_content(types.Content(parts=[
                        types.Part(text=(
                            f"[CANDIDATE CLICKED RUN - {status}]\nOutput:\n```\n{output_text}\n```"
                        ))
                    ]))
                    logger.info("Sent code result to Gemini: %s (stdout=%d)", status, len(state._latest_output))

                    # Send screen frame separately (vision for hackathon)
                    if ctx.get("latest_screen_frame"):
                        live_request_queue.send_content(types.Content(parts=[
                            types.Part(inline_data=types.Blob(
                                data=ctx["latest_screen_frame"],
                                mime_type="image/jpeg",
                            ))
                        ]))
                        logger.info("Sent screen frame to Gemini (Run button)")

                    state._tool_call_pending = False
                    logger.info("Code result stored (stdout=%d, stderr=%d, exit=%d)",
                               len(state._latest_output), len(state._latest_stderr),
                               state._latest_exit_code)

                elif msg.get("type") == "end_session":
                    summary = end_interview_fn(
                        state, session_manager, reason="candidate_requested"
                    )
                    await _send_ws(websocket, {
                        "type": "session_ended",
                        "summary": summary,
                    })
                    ctx["running"] = False
                    break

            except WebSocketDisconnect:
                ctx["running"] = False
                break
            except Exception as e:
                logger.error("Upstream error: %s", e)
                ctx["running"] = False
                break

    # -------------------------------------------------------------------
    # Downstream: Runner.run_live() ADK Events -> Browser WebSocket
    # -------------------------------------------------------------------
    async def downstream_task():
        try:
            async for event in runner.run_live(
                user_id=user_id,
                session_id=adk_session_id,
                live_request_queue=live_request_queue,
                run_config=run_config,
            ):
                if not ctx["running"]:
                    break

                # --- Verbose logging ---
                input_tx = getattr(event, "input_transcription", None)
                output_tx = getattr(event, "output_transcription", None)
                has_content = getattr(event, "content", None) is not None
                is_turn_complete = getattr(event, "turn_complete", False)
                is_interrupted = getattr(event, "interrupted", False)

                if input_tx and getattr(input_tx, "text", ""):
                    logger.info("[CANDIDATE SAYS] %s", getattr(input_tx, "text", ""))
                if output_tx and getattr(output_tx, "text", ""):
                    logger.info("[AGENT SAYS] %s", getattr(output_tx, "text", ""))
                if is_turn_complete:
                    logger.info("[TURN COMPLETE]")
                if is_interrupted:
                    logger.info("[INTERRUPTED]")

                # Log tool calls from actions
                actions = getattr(event, "actions", None)
                if actions and (actions.transfer_to_agent or actions.escalate):
                    logger.info("[ACTIONS] %s", actions)

                # --- Turn Complete ---
                if getattr(event, "turn_complete", False):
                    ctx["agent_speaking"] = False
                    if not ctx["opening_complete"]:
                        ctx["opening_complete"] = True
                        logger.info(
                            "Opening complete, mic forwarding enabled for %s",
                            state.session_id,
                        )

                    # Flush agent transcript buffer (candidate is sent incrementally)
                    await _flush_buffer(websocket, ctx, "agent")
                    # Clear candidate buffer without re-sending (already sent incrementally)
                    if ctx["input_text_buffer"].strip():
                        ctx["transcript_buffer"].append({
                            "speaker": "candidate",
                            "text": ctx["input_text_buffer"].strip(),
                            "timestamp": time.time(),
                        })
                        ctx["input_text_buffer"] = ""

                    # Reset flags for next turn
                    ctx["_code_sent_this_turn"] = False
                    ctx["_code_context_sent_this_turn"] = False
                    ctx["_repetition_detected"] = False
                    ctx["_first_question_asked"] = False
                    ctx["_text_at_first_q"] = ""
                    # Persist transcript to session state for report card
                    state.live_transcript = list(ctx["transcript_buffer"])
                    # Store last candidate text for hallucination guard in tools
                    state._last_candidate_text = ctx["input_text_buffer"].strip() if ctx["input_text_buffer"].strip() else getattr(state, "_last_candidate_text", "")
                    await _send_ws(websocket, {"type": "turn_complete"})

                    # Check session timing
                    await _check_timing(
                        websocket, live_request_queue, state, session_manager, ctx
                    )
                    continue

                # --- Interrupted ---
                if getattr(event, "interrupted", False):
                    ctx["agent_speaking"] = False
                    await _flush_buffer(websocket, ctx, "agent")
                    await _send_ws(websocket, {"type": "interrupted"})
                    continue

                # --- Tool calls (function_call / function_response) ---
                # Log if there's a pending tool call so we can track latency
                actions = getattr(event, "actions", None)
                if actions:
                    logger.info("ADK actions: %s", actions)

                # --- Input Transcription (candidate speech -> text) ---
                input_transcription = getattr(event, "input_transcription", None)
                if input_transcription:
                    text = getattr(input_transcription, "text", "") or ""
                    if text:
                        text = re.sub(r"<ctrl\d+>", "", text)
                        if text.strip():
                            # Candidate speaking means agent turn is over
                            if ctx["agent_speaking"]:
                                ctx["agent_speaking"] = False
                                await _flush_buffer(websocket, ctx, "agent")
                            # Same cumulative handling as agent output:
                            # replace with longer text, append if shorter (new turn)
                            prev_len = len(ctx["input_text_buffer"])
                            if len(text) >= prev_len:
                                delta = text[prev_len:] if text.startswith(ctx["input_text_buffer"]) else text
                                ctx["input_text_buffer"] = text
                            else:
                                delta = text
                                ctx["input_text_buffer"] += text
                            # Update last candidate text for hallucination guard
                            state._last_candidate_text = ctx["input_text_buffer"]
                            if delta.strip():
                                await _send_ws(websocket, {
                                    "type": "transcript",
                                    "speaker": "candidate",
                                    "text": delta,
                                    "incremental": True,
                                })

                            # Code context is injected via evaluate_and_continue tool
                            # response, not via send_content (which triggers auto-talk)

                # --- Output Transcription (agent speech -> text) ---
                output_transcription = getattr(event, "output_transcription", None)
                if output_transcription:
                    text = getattr(output_transcription, "text", "") or ""
                    if text:
                        text = re.sub(r"<ctrl\d+>", "", text)
                        if text.strip():
                            # For agent output, just replace with cumulative text
                            if len(text) >= len(ctx["output_text_buffer"]):
                                # Mute audio after the FIRST question mark is detected
                                # This prevents the second question from being spoken aloud
                                # (transcription lags behind audio, so we must cut early)
                                if "?" in text and not ctx.get("_first_question_asked"):
                                    ctx["_first_question_asked"] = True
                                    ctx["_text_at_first_q"] = text
                                    logger.info("First question mark detected - will mute after brief delay")
                                elif ctx.get("_first_question_asked") and not ctx.get("_repetition_detected"):
                                    # Any new text after the first question = potential repeat, mute
                                    new_text = text[len(ctx.get("_text_at_first_q", "")):]
                                    if len(new_text) > 10:
                                        ctx["_repetition_detected"] = True
                                        logger.info("Audio muted - content after first question detected")

                                # Also detect semantic repetition
                                if not ctx.get("_repetition_detected"):
                                    buf = text.strip()
                                    if len(buf) > 60:
                                        # Split into sentences (with or without space after punctuation)
                                        sentences = [s.strip() for s in re.split(r'(?<=[.?!])\s*(?=[A-Z])', buf) if len(s.strip()) > 15]
                                        if len(sentences) >= 2:
                                            # Extract key nouns/verbs from each sentence (words 4+ chars)
                                            def key_words(s):
                                                return set(w.lower() for w in s.split() if len(w) >= 4)
                                            seen_signatures = []
                                            for sent in sentences:
                                                kw = key_words(sent)
                                                if len(kw) < 3:
                                                    continue
                                                for prev_kw in seen_signatures:
                                                    # If 60%+ of key words overlap, it's a repeat
                                                    overlap = len(kw & prev_kw)
                                                    smaller = min(len(kw), len(prev_kw))
                                                    if smaller > 0 and overlap / smaller >= 0.6:
                                                        ctx["_repetition_detected"] = True
                                                        logger.info(
                                                            "Semantic repetition detected - muting audio. "
                                                            "Overlap: %d/%d words", overlap, smaller
                                                        )
                                                        break
                                                if ctx.get("_repetition_detected"):
                                                    break
                                                seen_signatures.append(kw)
                                ctx["output_text_buffer"] = text
                            else:
                                ctx["output_text_buffer"] += text

                # --- Content (audio data from model) ---
                content = getattr(event, "content", None)
                if content and hasattr(content, "parts") and content.parts:
                    for part in content.parts:
                        inline_data = getattr(part, "inline_data", None)
                        if inline_data and inline_data.data:
                            # Don't forward audio if repetition detected
                            if ctx.get("_repetition_detected"):
                                continue
                            ctx["agent_speaking"] = True
                            audio_b64 = base64.b64encode(
                                inline_data.data
                            ).decode("utf-8")
                            await _send_ws(websocket, {
                                "type": "audio",
                                "data": audio_b64,
                            })

        except Exception as e:
            logger.error("Downstream error: %s", e, exc_info=True)
            # Notify frontend of connection loss
            try:
                await _send_ws(websocket, {
                    "type": "error",
                    "message": "Voice connection lost. Please start a new session.",
                    "recoverable": False,
                })
            except Exception:
                pass
        finally:
            logger.warning("Downstream task exiting for %s (running=%s)", state.session_id, ctx["running"])
            ctx["running"] = False

    # -------------------------------------------------------------------
    # Tool Events: Forward tool side-effect messages to WebSocket
    # -------------------------------------------------------------------
    async def tool_event_task():
        while ctx["running"]:
            try:
                msg = await asyncio.wait_for(event_queue.get(), timeout=0.5)
                await _send_ws(websocket, msg)

                # If report_ready, signal to stop
                if msg.get("type") == "report_ready":
                    ctx["running"] = False
                    break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error("Tool event error: %s", e)
                break

    # -------------------------------------------------------------------
    # Run all three tasks concurrently
    # -------------------------------------------------------------------
    try:
        await asyncio.gather(
            upstream_task(),
            downstream_task(),
            tool_event_task(),
            return_exceptions=True,
        )
    except WebSocketDisconnect:
        logger.info("Client disconnected: %s", state.session_id)
    except Exception as e:
        logger.error("ADK session error for %s: %s", state.session_id, e, exc_info=True)
        try:
            await _send_ws(websocket, {
                "type": "error",
                "message": f"Session error: {str(e)}",
            })
        except Exception:
            pass
    finally:
        live_request_queue.close()
        if state.status != SessionStatus.COMPLETE:
            session_manager.update_session(state)
        logger.info("ADK session ended: %s", state.session_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _send_ws(websocket: WebSocket, message: dict) -> None:
    """Send a JSON message to the browser WebSocket."""
    try:
        await websocket.send_text(json.dumps(message))
    except Exception as e:
        logger.error("Failed to send WS message: %s", e)


async def _flush_buffer(websocket: WebSocket, ctx: dict, speaker: str) -> None:
    """Flush a transcript text buffer and send as a single message."""
    key = "output_text_buffer" if speaker == "agent" else "input_text_buffer"
    text = ctx[key].strip()
    if not text:
        return

    # Clean control tokens
    text = re.sub(r"<ctrl\d+>", "", text).strip()
    if not text:
        ctx[key] = ""
        return

    # Agent should only ask ONE question per turn. If there are multiple
    # questions, keep only the first one (plus any lead-in statement).
    if speaker == "agent" and text.count("?") >= 2:
        # Find the first question mark and keep everything up to it
        first_q = text.index("?")
        text = text[:first_q + 1].strip()
        logger.info("Truncated agent text to first question only")

    # Remove semantically repeated sentences (Gemini sometimes says the same thing twice)
    if speaker == "agent" and len(text) > 60:
        # Split on sentence boundaries - with or without space after punctuation
        sentences = re.split(r'(?<=[.?!])\s*(?=[A-Z])', text)
        if len(sentences) >= 2:
            def key_words(s):
                return set(w.lower() for w in s.split() if len(w) >= 4)
            unique = []
            seen_sigs = []
            for sent in sentences:
                kw = key_words(sent)
                is_dup = False
                if len(kw) >= 3:
                    for prev_kw in seen_sigs:
                        overlap = len(kw & prev_kw)
                        smaller = min(len(kw), len(prev_kw))
                        if smaller > 0 and overlap / smaller >= 0.6:
                            is_dup = True
                            break
                    seen_sigs.append(kw)
                if not is_dup:
                    unique.append(sent)
            if len(unique) < len(sentences):
                logger.info("Deduped %d repeated sentences from agent transcript", len(sentences) - len(unique))
                text = " ".join(unique)

    ctx["transcript_buffer"].append({
        "speaker": speaker,
        "text": text,
        "timestamp": time.time(),
    })
    # Candidate transcripts are sent incrementally now, so only flush agent
    if speaker == "agent":
        await _send_ws(websocket, {
            "type": "transcript",
            "speaker": "agent",
            "text": text,
        })
    ctx[key] = ""


async def _check_timing(
    websocket: WebSocket,
    live_request_queue: LiveRequestQueue,
    state: InterviewState,
    session_manager: SessionManager,
    ctx: dict,
) -> None:
    """Check session timing and trigger wrap-up or hard cap."""
    elapsed = time.time() - ctx["interview_start_time"]

    # Hard cap: 20 minutes
    if elapsed >= INTERVIEW_HARD_CAP_SECONDS and not ctx["hard_cap_sent"]:
        ctx["hard_cap_sent"] = True
        logger.info("Hard cap reached for session %s", state.session_id)

        live_request_queue.send_content(
            types.Content(
                parts=[types.Part(text="[SYSTEM: Time is up. Wrap up the interview now.]")]
            )
        )

        await _send_ws(websocket, {
            "type": "session_ending",
            "reason": "time_limit",
            "message": "Interview time complete. Generating your report card.",
        })

        summary = end_interview_fn(state, session_manager, reason="time_limit")
        await _send_ws(websocket, {
            "type": "report_ready",
            "session_id": state.session_id,
            "summary": summary,
        })
        ctx["running"] = False
        return

    # Soft wrap: 15 minutes
    if elapsed >= INTERVIEW_SOFT_WRAP_SECONDS and not ctx["soft_wrap_sent"]:
        ctx["soft_wrap_sent"] = True
        logger.info("Soft wrap triggered for session %s", state.session_id)

        await _send_ws(websocket, {
            "type": "time_warning",
            "minutes_remaining": int((INTERVIEW_HARD_CAP_SECONDS - elapsed) / 60),
            "message": "Wrapping up soon.",
        })

        live_request_queue.send_content(
            types.Content(
                parts=[types.Part(text=(
                    "[SYSTEM: We have about 5 minutes left. After the candidate "
                    "finishes their current answer, say something like: "
                    "'We have a few minutes left, let me ask you one more thing.' "
                    "Ask ONE final question, then wrap up naturally with: "
                    "'That's a good place to stop. I have a good picture of "
                    "where you are. Let me put together your report card.' "
                    "Then call the end_interview tool.]"
                ))]
            )
        )

    # Ceiling detection: 3 consecutive same-level scores
    if _check_ceiling(state) and elapsed > 5 * 60:
        if not ctx["soft_wrap_sent"]:
            ctx["soft_wrap_sent"] = True
            logger.info(
                "Ceiling detected for session %s at depth %d",
                state.session_id,
                state.current_depth_level,
            )
            await _send_ws(websocket, {
                "type": "ceiling_detected",
                "depth_level": state.current_depth_level,
                "message": "Performance ceiling detected. Wrapping up.",
            })
            live_request_queue.send_content(
                types.Content(
                    parts=[types.Part(text=(
                        "[SYSTEM: You've found the candidate's ceiling. They've "
                        "given 3 consecutive responses at the same depth level. "
                        "Wrap up naturally and call the end_interview tool with "
                        "reason 'ceiling_reached'.]"
                    ))]
                )
            )


def _check_ceiling(state: InterviewState) -> bool:
    """Check if candidate hit their ceiling (3 consecutive same-level scores)."""
    exchanges = state.exchanges
    if len(exchanges) < CEILING_CONSECUTIVE_SAME:
        return False
    recent = exchanges[-CEILING_CONSECUTIVE_SAME:]
    levels = [e.depth_level for e in recent]
    scores = [e.score for e in recent]
    return len(set(levels)) == 1 and (max(scores) - min(scores)) <= 2
