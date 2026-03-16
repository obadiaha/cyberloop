"""
CyberLoop Agent — Gemini Live API integration.

Bridges browser WebSocket audio to Gemini Live API for bidirectional
voice-based interviewing. Uses native audio mode with PCM16 at 16kHz.

Model: gemini-2.5-flash-native-audio-preview
Audio: PCM16, 16kHz, mono, little-endian
"""

import asyncio
import base64
import json
import logging
import os
import random
import time
from typing import Any

from google import genai
from google.genai import types as genai_types
from google.genai import types
from fastapi import WebSocket, WebSocketDisconnect

from agent.session import (
    InterviewState,
    SessionConfig,
    SessionManager,
    SessionStatus,
)
from agent.prompts import build_system_prompt, get_opening_line
from agent.tools import (
    TOOL_DECLARATIONS,
    get_next_question,
    advance_depth_ladder,
    score_response,
    end_interview,
    load_question_trees,
    get_question_tree,
)
from agent.interruption import InterruptionHandler, InterruptionType

logger = logging.getLogger(__name__)

# Gemini Live API model
# Native audio model - the only one that works with Live API without v1alpha
# Known issue: produces 'thought' tokens. We filter them in the receive loop.
MODEL_ID = "gemini-2.5-flash-native-audio-latest"

# Audio format constants
AUDIO_MIME_TYPE = "audio/pcm;rate=16000"
AUDIO_SAMPLE_RATE = 16000

# Voice options (Charon = professional/authoritative)
VOICE_NAME = "Charon"

# Session timing
SESSION_TIMEOUT_SECONDS = 600  # Gemini Live sessions ~10 min max
INTERVIEW_HARD_CAP_SECONDS = 20 * 60  # 20 minutes hard cap
INTERVIEW_SOFT_WRAP_SECONDS = 15 * 60  # 15 minutes: start wrapping up
CEILING_CONSECUTIVE_SAME = 3  # 3 same-level scores = ceiling found


class CyberLoopAgent:
    """
    Main interview agent. Manages the Gemini Live API session and
    bridges audio between the browser WebSocket and Gemini.
    """

    def __init__(
        self,
        state: InterviewState,
        session_manager: SessionManager,
    ):
        self.state = state
        self.session_manager = session_manager
        self.interruption_handler = InterruptionHandler()

        # Initialize the GenAI client
        # NOTE: v1alpha was causing 'thought' parts in audio responses even
        # with thinking disabled, creating audio stutter. Using default API.
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        self.client = genai.Client(api_key=api_key)

        # Build system prompt
        domain = state.current_domain or (
            state.config.domains[0] if state.config.domains else "incident_response"
        )
        question_tree = get_question_tree(domain)
        self.system_prompt = build_system_prompt(
            company=state.config.company,
            level=state.config.level,
            mode=state.config.mode,
            domains=state.config.domains,
            question_tree=question_tree,
        )

        # Tracking
        self._running = False
        self._gemini_session = None
        self._transcript_buffer: list[dict[str, str]] = []
        self._interview_start_time: float = 0.0
        self._soft_wrap_sent = False
        self._hard_cap_sent = False
        self._agent_speaking = False  # True while agent audio is streaming
        self._opening_complete = False  # Don't forward mic until opening is done
        self._audio_chunk_seq = 0  # Sequence counter for audio chunks
        self._debug_audio_file = None  # Debug: save raw audio to file
        # Transcription fragment buffers (accumulate words into sentences)
        self._output_text_buffer = ""
        self._input_text_buffer = ""

    def _build_live_config(self) -> types.LiveConnectConfig:
        """Build the configuration for Gemini Live API connection."""
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=self.system_prompt,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=VOICE_NAME,
                    )
                )
            ),
            # Enable transcription of both input (candidate) and output (interviewer)
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Affective dialog disabled: requires v1alpha which causes 'thought'
            # parts in audio responses, creating stutter. Re-enable when fixed.
            # enable_affective_dialog=True,
            # Thinking DISABLED: Causes audio stutter in Live API.
            # Model generates audio, pauses to think, then restarts the sentence.
            # The model's native reasoning + system prompt + tool calls provide
            # sufficient depth for interview follow-ups without explicit thinking.
            # thinking_config=types.ThinkingConfig(thinking_budget=1024),
            # Context window compression for sessions >15 min
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(
                    target_tokens=64000,
                ),
            ),
            # Realtime input config: auto VAD with tuned sensitivity
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=False,
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    prefix_padding_ms=20,
                    silence_duration_ms=500,
                ),
            ),
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
        )
        return config

    async def run_session(self, websocket: WebSocket) -> None:
        """
        Main session loop. Bridges browser WebSocket to Gemini Live API.

        Flow:
        1. Connect to Gemini Live API
        2. Start bidirectional audio streaming
        3. Handle tool calls from Gemini
        4. Forward audio responses to browser
        5. Detect and handle interruptions
        """
        self._running = True

        # Activate the session
        self.state.status = SessionStatus.ACTIVE
        self.session_manager.update_session(self.state)

        config = self._build_live_config()

        try:
            async with self.client.aio.live.connect(
                model=MODEL_ID,
                config=config,
            ) as gemini_session:
                self._gemini_session = gemini_session

                self._interview_start_time = time.time()
                logger.info(
                    "Gemini Live session connected for %s", self.state.session_id
                )

                # Notify browser that session is active
                await self._send_ws_message(websocket, {
                    "type": "session_started",
                    "session_id": self.state.session_id,
                    "company": self.state.config.company,
                    "mode": self.state.config.mode,
                    "domains": self.state.config.domains,
                })

                # Start receive loop FIRST so we catch the opening audio
                async def send_opening_then_forward():
                    """Send opening prompt, then start forwarding mic audio."""
                    # Small delay so receive loop is ready
                    await asyncio.sleep(0.1)

                    # Simplified opening to prevent double-intro
                    opening = (
                        "BEGIN. Greet the candidate briefly (e.g. 'Hi, let's get started') "
                        "and then immediately ask your first technical question. "
                        "Do not give a long introduction."
                    )

                    await gemini_session.send_client_content(
                        turns=types.Content(
                            role="user",
                            parts=[types.Part(text=opening)],
                        ),
                        turn_complete=True,
                    )
                    logger.info("Sent opening prompt for %s", self.state.session_id)
                    # Then start forwarding mic audio
                    await self._forward_audio_to_gemini(websocket, gemini_session)

                # Run bidirectional streaming
                await asyncio.gather(
                    send_opening_then_forward(),
                    self._receive_from_gemini(websocket, gemini_session),
                    return_exceptions=True,
                )

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected for session %s", self.state.session_id)
        except Exception as e:
            logger.error(
                "Session error for %s: %s", self.state.session_id, str(e),
                exc_info=True,
            )
            try:
                await self._send_ws_message(websocket, {
                    "type": "error",
                    "message": f"Session error: {str(e)}",
                })
            except Exception:
                pass
        finally:
            self._running = False
            self._gemini_session = None

            # Persist final state if not already complete
            if self.state.status != SessionStatus.COMPLETE:
                self.session_manager.update_session(self.state)

            logger.info("Session %s ended", self.state.session_id)

    async def _forward_audio_to_gemini(
        self,
        websocket: WebSocket,
        gemini_session: Any,
    ) -> None:
        """
        Receive audio from the browser WebSocket and forward to Gemini.
        Browser sends base64-encoded PCM16 audio chunks.
        """
        try:
            while self._running:
                raw = await websocket.receive_text()
                msg = json.loads(raw)

                if msg.get("type") == "audio":
                    # Don't forward mic audio until the agent's opening is done.
                    # Background noise triggers Gemini's VAD and makes it restart
                    # its greeting mid-sentence.
                    if not self._opening_complete:
                        continue

                    # Decode base64 audio data
                    audio_bytes = base64.b64decode(msg["data"])
                    self.interruption_handler.reset_silence_timer()

                    # Use send_realtime_input (not deprecated send)
                    # Optimized for real-time responsiveness
                    await gemini_session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_bytes,
                            mime_type=AUDIO_MIME_TYPE,
                        ),
                    )

                elif msg.get("type") == "end_of_turn":
                    # Candidate finished speaking - signal audio stream end
                    await gemini_session.send_realtime_input(
                        audio_stream_end=True,
                        end_of_turn=True,
                    )

                elif msg.get("type") == "interrupt":
                    # Manual interrupt button pressed
                    interrupt_type = InterruptionType(
                        msg.get("interrupt_type", "skip")
                    )
                    response_text = self.interruption_handler.handle(
                        interrupt_type, self.state
                    )
                    await self._send_ws_message(websocket, {
                        "type": "interrupt_handled",
                        "interrupt_type": interrupt_type.value,
                        "message": response_text,
                    })

                elif msg.get("type") == "end_session":
                    # Candidate wants to end
                    summary = end_interview(
                        self.state, self.session_manager, reason="candidate_requested"
                    )
                    await self._send_ws_message(websocket, {
                        "type": "session_ended",
                        "summary": summary,
                    })
                    self._running = False
                    break

        except WebSocketDisconnect:
            self._running = False
        except Exception as e:
            logger.error("Error forwarding audio to Gemini: %s", e)
            self._running = False

    async def _flush_transcript(self, websocket: WebSocket, speaker: str) -> None:
        """Flush buffered transcription text as a single transcript message."""
        if speaker == "agent" and self._output_text_buffer.strip():
            text = self._output_text_buffer.strip()
            self._output_text_buffer = ""
            self._transcript_buffer.append({
                "speaker": "agent",
                "text": text,
                "timestamp": time.time(),
            })
            await self._send_ws_message(websocket, {
                "type": "transcript",
                "speaker": "agent",
                "text": text,
            })
        elif speaker == "candidate" and self._input_text_buffer.strip():
            text = self._input_text_buffer.strip()
            self._input_text_buffer = ""
            self._transcript_buffer.append({
                "speaker": "candidate",
                "text": text,
                "timestamp": time.time(),
            })
            await self._send_ws_message(websocket, {
                "type": "transcript",
                "speaker": "candidate",
                "text": text,
            })

    async def _receive_from_gemini(
        self,
        websocket: WebSocket,
        gemini_session: Any,
    ) -> None:
        """
        Receive responses from Gemini Live API and forward to browser.
        Handles: audio data, text transcripts, and tool calls.

        Key behaviors:
        - Sets _agent_speaking flag while streaming audio (prevents echo)
        - Buffers transcription fragments into complete sentences
        - Flushes transcript buffer on turn_complete
        """
        try:
            while self._running:
                async for response in gemini_session.receive():
                    if not self._running:
                        break

                    # Handle audio data (top-level response.data)
                    if response.data:
                        self._agent_speaking = True
                        audio_b64 = base64.b64encode(response.data).decode("utf-8")
                        await self._send_ws_message(websocket, {
                            "type": "audio",
                            "data": audio_b64,
                        })

                    # Handle tool calls
                    if response.tool_call:
                        await self._handle_tool_call(
                            websocket, gemini_session, response.tool_call
                        )

                    # Handle server content
                    server_content = getattr(response, "server_content", None)
                    if server_content:
                        # Handle interruption (user barged in while agent was speaking)
                        interrupted = getattr(server_content, "interrupted", False)
                        if interrupted:
                            self._agent_speaking = False
                            # Tell frontend to clear audio buffer immediately
                            await self._send_ws_message(websocket, {
                                "type": "interrupted",
                            })
                            # Flush any partial transcript
                            await self._flush_transcript(websocket, "agent")
                            logger.info("Agent interrupted by candidate")

                        # Check for turn completion
                        turn_complete = getattr(server_content, "turn_complete", False)
                        if turn_complete:
                            # Agent finished speaking - flush transcript buffers
                            self._agent_speaking = False
                            # Enable mic forwarding after first turn (opening) completes
                            if not self._opening_complete:
                                self._opening_complete = True
                                logger.info("Opening complete, mic forwarding enabled for %s", self.state.session_id)
                            await self._flush_transcript(websocket, "agent")
                            await self._flush_transcript(websocket, "candidate")
                            await self._send_ws_message(websocket, {
                                "type": "turn_complete",
                            })

                        # Buffer output transcription fragments (agent speech -> text)
                        output_transcription = getattr(
                            server_content, "output_transcription", None
                        )
                        if output_transcription:
                            text = getattr(output_transcription, "text", "") or ""
                            # Filter thinking control tokens (<ctrl46> etc.)
                            if text:
                                import re
                                text = re.sub(r'<ctrl\d+>', '', text).strip()
                            if text:
                                self._output_text_buffer += text

                        # Buffer input transcription fragments (candidate speech -> text)
                        input_transcription = getattr(
                            server_content, "input_transcription", None
                        )
                        if input_transcription:
                            text = getattr(input_transcription, "text", "") or ""
                            if text:
                                import re
                                text = re.sub(r'<ctrl\d+>', '', text).strip()
                            if text:
                                # Candidate speaking means agent turn is over
                                if self._agent_speaking:
                                    self._agent_speaking = False
                                    await self._flush_transcript(websocket, "agent")
                                self._input_text_buffer += text

                        # Check for model turn with audio parts
                        # IMPORTANT: With thinking enabled, parts may contain
                        # 'text', 'thought', AND 'inline_data' (audio) mixed together.
                        # Only forward inline_data parts. Skip text/thought to avoid
                        # stuttering caused by non-audio parts interrupting the stream.
                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn and hasattr(model_turn, "parts"):
                            for part in model_turn.parts:
                                # Log what types of parts we're getting
                                part_types = []
                                if hasattr(part, "text") and part.text:
                                    part_types.append(f"text({len(part.text)})")
                                if hasattr(part, "thought") and part.thought:
                                    part_types.append("thought")
                                if hasattr(part, "inline_data") and part.inline_data:
                                    part_types.append(f"audio({len(part.inline_data.data)})")
                                if part_types:
                                    logger.debug("Part types: %s", ", ".join(part_types))

                                # Skip non-audio parts (text, thought, etc.)
                                if not hasattr(part, "inline_data") or not part.inline_data:
                                    continue
                                self._agent_speaking = True
                                self._audio_chunk_seq += 1
                                audio_data = part.inline_data.data
                                audio_b64 = base64.b64encode(audio_data).decode("utf-8")
                                # Save raw audio for debugging
                                if not self._debug_audio_file:
                                    debug_path = f"/tmp/ci_debug_{self.state.session_id[:8]}.pcm"
                                    self._debug_audio_file = open(debug_path, "wb")
                                    logger.info("Debug audio: %s", debug_path)
                                self._debug_audio_file.write(audio_data)
                                logger.info(
                                    "Audio chunk #%d: %d bytes",
                                    self._audio_chunk_seq, len(audio_data)
                                )
                                await self._send_ws_message(websocket, {
                                    "type": "audio",
                                    "data": audio_b64,
                                    "seq": self._audio_chunk_seq,
                                })

        except WebSocketDisconnect:
            self._running = False
        except Exception as e:
            logger.error("Error receiving from Gemini: %s", e, exc_info=True)
            self._running = False

    async def _handle_tool_call(
        self,
        websocket: WebSocket,
        gemini_session: Any,
        tool_call: Any,
    ) -> None:
        """
        Process a tool call from Gemini and send the result back.

        Dispatches to the appropriate tool function based on the
        function name in the tool call.
        """
        # tool_call may have function_calls attribute
        function_calls = getattr(tool_call, "function_calls", [tool_call])
        if not isinstance(function_calls, list):
            function_calls = [function_calls]

        for fc in function_calls:
            fn_name = getattr(fc, "name", "") or getattr(fc, "function_name", "")
            fn_args = getattr(fc, "args", {}) or {}
            call_id = getattr(fc, "id", None)

            logger.info("Tool call: %s(%s)", fn_name, json.dumps(fn_args)[:200])

            result = self._dispatch_tool(fn_name, fn_args)

            # Notify browser about the tool call
            await self._send_ws_message(websocket, {
                "type": "tool_call",
                "function": fn_name,
                "result": result,
            })

            # If it was a score, send score update AND state_update to browser
            if fn_name == "score_response" and "score" in result:
                await self._send_ws_message(websocket, {
                    "type": "score_update",
                    "score": result["score"],
                    "level": result.get("level_label", ""),
                    "quality": result.get("quality", ""),
                    "depth_level": result.get("depth_level", 1),
                })
                # Also emit state_update so frontend tracks depth + question count
                await self._send_ws_message(websocket, {
                    "type": "state_update",
                    "depth_level": result.get("depth_level", self.state.current_depth_level),
                    "question_count": len(self.state.exchanges),
                    "domain": self.state.current_domain,
                    "current_question": self.state.current_question,
                })

            # If interview ended, send report
            if fn_name == "end_interview":
                await self._send_ws_message(websocket, {
                    "type": "report_ready",
                    "session_id": self.state.session_id,
                    "summary": result,
                })
                self._running = False

            # If question tree exhausted, consider ending
            if fn_name == "get_next_question" and result.get("exhausted"):
                await self._send_ws_message(websocket, {
                    "type": "questions_exhausted",
                    "domain": self.state.current_domain,
                })

            # Send tool response back to Gemini
            await gemini_session.send_tool_response(
                function_responses=[
                    genai_types.FunctionResponse(
                        name=fn_name,
                        id=call_id,
                        response=result,
                    )
                ]
            )

            # Check session timing after each tool call
            if await self._check_session_timing(websocket, gemini_session):
                return  # Interview ended by time/ceiling

    def _dispatch_tool(self, fn_name: str, fn_args: dict) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate function."""

        if fn_name == "get_next_question":
            direction = fn_args.get("direction", "next")
            result = get_next_question(self.state, direction=direction)
            # Update state with new question
            if result.get("question"):
                self.state.current_question = result["question"]
                self.state.current_question_id = result.get("question_id", "")
            return result

        elif fn_name == "advance_depth_ladder":
            return advance_depth_ladder(self.state)

        elif fn_name == "score_response":
            return score_response(
                state=self.state,
                question=fn_args.get("question", ""),
                response=fn_args.get("response", ""),
                expected_concepts=fn_args.get("expected_concepts"),
            )

        elif fn_name == "end_interview":
            return end_interview(
                state=self.state,
                session_manager=self.session_manager,
                reason=fn_args.get("reason", "complete"),
            )

        else:
            logger.warning("Unknown tool call: %s", fn_name)
            return {"error": f"Unknown tool: {fn_name}"}

    def _elapsed_seconds(self) -> float:
        """Seconds since interview started."""
        if self._interview_start_time == 0:
            return 0.0
        return time.time() - self._interview_start_time

    def _check_ceiling_reached(self) -> bool:
        """
        Check if the candidate has hit their ceiling:
        3 consecutive responses scoring at the same depth level.
        """
        exchanges = self.state.exchanges
        if len(exchanges) < CEILING_CONSECUTIVE_SAME:
            return False
        recent = exchanges[-CEILING_CONSECUTIVE_SAME:]
        levels = [e.depth_level for e in recent]
        scores = [e.score for e in recent]
        # Same depth level AND scores within 2 points of each other
        if len(set(levels)) == 1 and (max(scores) - min(scores)) <= 2:
            return True
        return False

    async def _check_session_timing(
        self,
        websocket: WebSocket,
        gemini_session: Any,
    ) -> bool:
        """
        Check session timing and trigger natural wrap-up or hard cap.
        Returns True if the interview should end.
        """
        elapsed = self._elapsed_seconds()

        # Hard cap: 20 minutes — end the interview now
        if elapsed >= INTERVIEW_HARD_CAP_SECONDS and not self._hard_cap_sent:
            self._hard_cap_sent = True
            logger.info("Hard cap reached for session %s", self.state.session_id)

            # Tell Gemini to close naturally
            await gemini_session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text="[SYSTEM: Time is up. Wrap up the interview now.]")],
                ),
                turn_complete=True,
            )
            # Inject a system-level instruction to wrap up immediately
            await self._send_ws_message(websocket, {
                "type": "session_ending",
                "reason": "time_limit",
                "message": "Interview time complete. Generating your report card.",
            })

            # End the interview
            summary = end_interview(
                self.state, self.session_manager, reason="time_limit"
            )
            await self._send_ws_message(websocket, {
                "type": "report_ready",
                "session_id": self.state.session_id,
                "summary": summary,
            })
            self._running = False
            return True

        # Soft wrap: 15 minutes — tell Gemini to ask one more question
        if elapsed >= INTERVIEW_SOFT_WRAP_SECONDS and not self._soft_wrap_sent:
            self._soft_wrap_sent = True
            logger.info("Soft wrap triggered for session %s", self.state.session_id)

            await self._send_ws_message(websocket, {
                "type": "time_warning",
                "minutes_remaining": int((INTERVIEW_HARD_CAP_SECONDS - elapsed) / 60),
                "message": "Wrapping up soon.",
            })

            # Send a text hint to Gemini to start closing
            # The model will naturally incorporate this into its next response
            await gemini_session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=(
                        "[SYSTEM: We have about 5 minutes left. After the candidate "
                        "finishes their current answer, say something like: "
                        "'We have a few minutes left, let me ask you one more thing.' "
                        "Ask ONE final question, then wrap up naturally with: "
                        "'That's a good place to stop. I have a good picture of "
                        "where you are. Let me put together your report card.' "
                        "Then call the end_interview tool.]"
                    ))],
                ),
                turn_complete=False,
            )

        # Ceiling detection: 3 consecutive same-level scores
        if self._check_ceiling_reached() and elapsed > 5 * 60:
            # Only trigger after at least 5 minutes (don't end too early)
            if not self._soft_wrap_sent:
                self._soft_wrap_sent = True
                logger.info(
                    "Ceiling detected for session %s at depth %d",
                    self.state.session_id,
                    self.state.current_depth_level,
                )
                await self._send_ws_message(websocket, {
                    "type": "ceiling_detected",
                    "depth_level": self.state.current_depth_level,
                    "message": "Performance ceiling detected. Wrapping up.",
                })
                await gemini_session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[types.Part(text=(
                            "[SYSTEM: You've found the candidate's ceiling. They've "
                            "given 3 consecutive responses at the same depth level. "
                            "Wrap up naturally: 'I think I have a good picture of "
                            "where you are technically. Let me put together your "
                            "report card with some specific recommendations.' "
                            "Then call the end_interview tool with reason 'ceiling_reached'.]"
                        ))],
                    ),
                    turn_complete=False,
                )

        return False

    async def _send_ws_message(self, websocket: WebSocket, message: dict) -> None:
        """Send a JSON message to the browser WebSocket."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error("Failed to send WebSocket message: %s", e)

    def get_transcript(self) -> list[dict[str, str]]:
        """Return the full transcript buffer."""
        return self._transcript_buffer


# ---------------------------------------------------------------------------
# Alias for backwards-compatible import: from agent.interviewer import InterviewAgent
# ---------------------------------------------------------------------------
InterviewAgent = CyberLoopAgent
