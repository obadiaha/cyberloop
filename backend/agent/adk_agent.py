"""
ADK Agent factory for CyberLoop.

Creates a Google ADK Agent with interview tools bound to per-session state.
Each WebSocket connection gets its own Agent instance with closures capturing
the InterviewState and SessionManager.
"""

import asyncio
import logging
from typing import Any

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from agent.session import InterviewState, SessionManager
from agent.tools import (
    get_next_question,
    advance_depth_ladder,
    score_response,
    end_interview,
    evaluate_and_continue,
)

logger = logging.getLogger(__name__)

MODEL_ID = "gemini-2.5-flash-native-audio-latest"


def create_interview_agent(
    state: InterviewState,
    session_manager: SessionManager,
    system_prompt: str,
    event_queue: asyncio.Queue,
) -> Agent:
    """
    Create an ADK Agent with interview tools bound to the given session state.

    Tools are created as closures so they capture `state`, `session_manager`,
    and `event_queue` without the model needing to pass them.

    Args:
        state: Interview session state (mutable, shared across tools)
        session_manager: For persisting session state
        system_prompt: Full system instruction for the interviewer persona
        event_queue: Queue for pushing side-effect messages to the WebSocket
    """

    # -----------------------------------------------------------------------
    # Tool: get_next_question
    # -----------------------------------------------------------------------
    def get_next_question_tool(direction: str = "next") -> dict:
        """Fetch the next interview question from the question tree.

        Use direction='next' for a new root topic, 'deeper' to probe deeper
        on the current topic, or 'same' to rephrase the current question.

        Args:
            direction: Direction to traverse the question tree. One of 'next', 'deeper', 'same'.
        """
        state._tool_call_pending = True
        logger.info("Tool: get_next_question(direction=%s, question_index=%d)", direction, state.question_index)
        result = get_next_question(state, direction=direction)
        logger.info("Tool result: question_id=%s, text=%.60s...", result.get("question_id", ""), result.get("question", "")[:60])
        # Update state with new question
        if result.get("question"):
            state.current_question = result["question"]
            state.current_question_id = result.get("question_id", "")
        # Push state update to frontend
        state_event = {
            "type": "state_update",
            "depth_level": state.current_depth_level,
            "question_count": len(state.exchanges),
            "domain": state.current_domain,
            "current_question": state.current_question,
        }
        # Include challenge data (logs, environment info) for coding questions
        if result.get("challenge_data"):
            state_event["challenge_data"] = result["challenge_data"]
            logger.info("Sending challenge_data to frontend: %s", result["challenge_data"].get("title", "unknown"))
        event_queue.put_nowait(state_event)
        if result.get("exhausted"):
            event_queue.put_nowait({
                "type": "questions_exhausted",
                "domain": state.current_domain,
            })
        state._tool_call_pending = False
        return result

    # -----------------------------------------------------------------------
    # Tool: advance_depth_ladder
    # -----------------------------------------------------------------------
    def advance_depth_ladder_tool() -> dict:
        """Move to the next depth level when the candidate has demonstrated
        sufficient understanding at the current level. Call this before
        asking a deeper probe question. Only advance when the candidate's
        response was strong or adequate."""
        result = advance_depth_ladder(state)
        event_queue.put_nowait({
            "type": "state_update",
            "depth_level": result["new_level"],
            "question_count": len(state.exchanges),
            "domain": state.current_domain,
            "current_question": state.current_question,
        })
        return result

    # -----------------------------------------------------------------------
    # Tool: evaluate_and_continue (merged: score + advance + get_next)
    # -----------------------------------------------------------------------
    def evaluate_and_continue_tool(
        question: str,
        response: str,
        score: int = 3,
        technical_depth: int = 3,
        specificity: int = 3,
        communication: int = 3,
        assessment: str = "",
        key_strengths: list[str] | None = None,
        areas_to_probe: list[str] | None = None,
        next_direction: str = "next",
        approach: int = 0,
        code_quality: int = 0,
        security_insight: int = 0,
        speed: int = 0,
    ) -> dict:
        """Score the candidate's VERBAL response AND get the next question.
        IMPORTANT: Only call this AFTER the candidate has SPOKEN their answer.
        The 'response' field MUST contain what the candidate actually said.
        If the candidate hasn't answered yet, DO NOT call this tool.
        Wait for them to speak first, then call this tool.

        Args:
            question: The question that was asked.
            response: What the candidate ACTUALLY SAID verbally (not what you imagine they might say).
            score: Overall score 1-10. 1-2=weak, 3-4=basic, 5-6=mid, 7-8=strong, 9-10=exceptional.
            technical_depth: 1-10, depth of technical knowledge.
            specificity: 1-10, concrete examples and details.
            communication: 1-10, clarity and structure.
            assessment: Brief qualitative assessment.
            key_strengths: What the candidate did well (1-3 items).
            areas_to_probe: Topics to dig deeper on (1-2 items).
            next_direction: 'next' for new topic, 'deeper' to probe current topic, 'done' to end interview.
            approach: CODING ONLY. 1-10, planning and problem breakdown.
            code_quality: CODING ONLY. 1-10, syntax, structure, data structures.
            security_insight: CODING ONLY. 1-10, interpreting results, attack chain.
            speed: CODING ONLY. 1-10, reasonable pace.
        """
        state._tool_call_pending = True
        logger.info("Tool: evaluate_and_continue(score=%d, direction=%s, response_len=%d)", score, next_direction, len(response))

        # Guard: check if the candidate actually spoke recently
        last_real = getattr(state, "_last_candidate_text", "")
        if len(response.strip()) < 15:
            logger.warning("Tool REJECTED: response too short (%d chars)", len(response.strip()))
            state._tool_call_pending = False
            return {
                "error": "Cannot score yet - the candidate hasn't given a substantive verbal response. "
                         "Ask your question and WAIT for them to answer before calling this tool.",
                "should_retry": True,
            }
        if not last_real or len(last_real) < 20:
            logger.warning("Tool REJECTED: no recent candidate speech detected (last_real=%d chars). Model may be hallucinating the response.", len(last_real))
            state._tool_call_pending = False
            return {
                "error": "No recent candidate speech detected. The candidate may still be coding. "
                         "WAIT for them to speak before scoring. Do NOT fabricate their response.",
                "should_retry": True,
            }

        result = evaluate_and_continue(
            state, question, response,
            score=score,
            technical_depth=technical_depth,
            specificity=specificity,
            communication=communication,
            assessment=assessment,
            key_strengths=key_strengths,
            areas_to_probe=areas_to_probe,
            next_direction=next_direction,
            approach=approach,
            code_quality=code_quality,
            security_insight=security_insight,
            speed=speed,
        )
        # Inject latest code + output into the tool result
        code = getattr(state, "_latest_code", "")
        if code.strip():
            numbered = "\n".join(f"{i:3d} | {l}" for i, l in enumerate(code.split("\n"), 1))
            result["candidate_code"] = numbered
            result["code_review_note"] = "Review the candidate's code above. Reference line numbers in your feedback."
        output = getattr(state, "_latest_output", "")
        stderr = getattr(state, "_latest_stderr", "")
        exit_code = getattr(state, "_latest_exit_code", None)
        if exit_code is not None:
            if exit_code == 0 and output:
                result["code_output"] = output
                result["code_ran_successfully"] = True
                result["code_review_note"] = (
                    "The code ran successfully. Review the output above. "
                    "Give feedback referencing specific line numbers and output values."
                )
            elif stderr:
                result["code_error"] = stderr
                result["code_ran_successfully"] = False
                result["code_review_note"] = (
                    f"The code FAILED with exit code {exit_code}. Error: {stderr}. "
                    "Tell the candidate about the error and help them fix it. "
                    "Do NOT say the code works or 'successfully extracts' anything."
                )

        logger.info("Tool result: score=%s/10, quality=%s, depth_advanced=%s, next_q=%s, has_code=%s",
                     result.get("score_10"), result.get("quality"),
                     result.get("depth_advanced"), bool(result.get("next_question")), bool(code.strip()))

        # Push score update to frontend
        event_queue.put_nowait({
            "type": "score_update",
            "score": result["score"],
            "level": result.get("level_label", ""),
            "quality": result.get("quality", ""),
            "depth_level": result.get("new_depth_level", 1),
        })

        # Push state update to frontend
        next_q = result.get("next_question")
        state_event = {
            "type": "state_update",
            "depth_level": result.get("new_depth_level", state.current_depth_level),
            "question_count": len(state.exchanges),
            "domain": state.current_domain,
            "current_question": state.current_question,
        }
        if next_q and next_q.get("challenge_data"):
            state_event["challenge_data"] = next_q["challenge_data"]
        event_queue.put_nowait(state_event)

        if next_q and next_q.get("exhausted"):
            event_queue.put_nowait({
                "type": "questions_exhausted",
                "domain": state.current_domain,
            })

        state._tool_call_pending = False
        return result

    # -----------------------------------------------------------------------
    # Tool: end_interview
    # -----------------------------------------------------------------------
    def end_interview_tool(reason: str = "complete") -> dict:
        """End the interview session and trigger report generation.
        Call this when all planned questions have been covered, the candidate
        asks to stop, or sufficient data has been collected for a meaningful report.

        Args:
            reason: Why the interview is ending.
        """
        result = end_interview(state, session_manager, reason)
        event_queue.put_nowait({
            "type": "report_ready",
            "session_id": state.session_id,
            "summary": result,
        })
        return result

    # -----------------------------------------------------------------------
    # Tool: log_body_language
    # -----------------------------------------------------------------------
    def log_body_language_tool(
        observation: str,
        confidence_level: str = "neutral",
        notable_signals: list[str] | None = None,
    ) -> dict:
        """Log a body language observation from the webcam feed. Call this
        when you notice something notable in the candidate's body language,
        posture, eye contact, or demeanor. Do NOT call this for every frame,
        only when you observe a meaningful signal.

        Args:
            observation: What you observed (e.g. "Candidate appears confident, maintaining steady eye contact and upright posture")
            confidence_level: One of 'confident', 'neutral', 'nervous', 'very_nervous'
            notable_signals: Specific signals observed (e.g. ["steady eye contact", "upright posture", "natural hand gestures"])
        """
        import time
        note = {
            "timestamp": time.time(),
            "observation": observation,
            "confidence_level": confidence_level,
            "notable_signals": notable_signals or [],
            "question_index": state.question_index,
        }
        state.body_language_notes.append(note)
        logger.info("Tool: log_body_language(confidence=%s, signals=%s)", confidence_level, notable_signals)
        return {"status": "logged", "total_observations": len(state.body_language_notes)}

    # -----------------------------------------------------------------------
    # Build the ADK Agent
    # -----------------------------------------------------------------------
    tools = [
        FunctionTool(get_next_question_tool),
        FunctionTool(evaluate_and_continue_tool),
        FunctionTool(end_interview_tool),
    ]

    # Only include body language tool in behavioral mode (reduces tool confusion in other modes)
    if state.config.mode == "behavioral":
        tools.append(FunctionTool(log_body_language_tool))

    agent = Agent(
        name="cyber_loop",
        model=MODEL_ID,
        instruction=system_prompt,
        tools=tools,
    )

    return agent
