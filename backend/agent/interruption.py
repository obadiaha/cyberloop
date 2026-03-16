"""
Interruption state machine for CyberLoop.

Handles candidate-initiated and agent-detected interruptions during
the interview flow. Tracks state through interruptions to maintain
coherent interview progression.

Types:
  REDO      - Candidate wants the question repeated/rephrased
  SKIP      - Candidate wants to move to the next question
  CLARIFY   - Candidate asks for clarification on terminology
  OFF_TRACK - Agent detects candidate has gone off-topic
  SILENCE   - Extended silence detected (>8 seconds)
"""

import time
from enum import Enum
from typing import Optional

from agent.session import InterviewState


class InterruptionType(str, Enum):
    REDO = "redo"
    SKIP = "skip"
    CLARIFY = "clarify"
    OFF_TRACK = "off_track"
    SILENCE = "silence"


# Keyword patterns for detecting candidate-initiated interruptions
INTERRUPTION_KEYWORDS: dict[InterruptionType, list[str]] = {
    InterruptionType.REDO: [
        "repeat that",
        "say that again",
        "didn't hear",
        "didn't catch",
        "what was the question",
        "come again",
        "one more time",
        "can you repeat",
        "could you repeat",
        "can you rephrase",
        "could you rephrase",
        "say again",
    ],
    InterruptionType.SKIP: [
        "skip this",
        "skip that",
        "next question",
        "move on",
        "pass on this",
        "let's move on",
        "i'll pass",
        "skip it",
        "can we skip",
        "next one",
    ],
    InterruptionType.CLARIFY: [
        "what do you mean",
        "can you clarify",
        "could you clarify",
        "what does that mean",
        "define that",
        "can you explain",
        "what exactly",
        "not sure i understand",
        "i don't understand",
        "can you be more specific",
    ],
}

# Responses per interruption type
INTERRUPTION_RESPONSES: dict[InterruptionType, str] = {
    InterruptionType.REDO: "Of course. Let me rephrase that.",
    InterruptionType.SKIP: "No problem, let's move on to the next question.",
    InterruptionType.CLARIFY: "Good question. Let me clarify.",
    InterruptionType.OFF_TRACK: (
        "That's interesting context, but let's bring it back to the question "
        "at hand."
    ),
    InterruptionType.SILENCE: (
        "Take your time. What's your initial thought on this?"
    ),
}


class InterruptionHandler:
    """
    Detects and handles interruptions during the interview.
    Maintains interrupt state so the interview can resume coherently.
    """

    def __init__(self):
        self.last_audio_time: float = time.time()
        self.silence_threshold_seconds: float = 8.0
        self.silence_prompted: bool = False
        self.interrupt_count: int = 0
        self.skip_count: int = 0

    def detect(self, transcript_fragment: str) -> Optional[InterruptionType]:
        """
        Detect if a transcript fragment contains an interruption keyword.

        Args:
            transcript_fragment: Recent text from the candidate

        Returns:
            InterruptionType if detected, None otherwise
        """
        if not transcript_fragment:
            return None

        lowered = transcript_fragment.lower().strip()

        for interrupt_type, keywords in INTERRUPTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in lowered:
                    return interrupt_type

        return None

    def check_silence(self) -> Optional[InterruptionType]:
        """
        Check if enough time has passed since last audio to trigger
        a silence prompt.

        Returns:
            InterruptionType.SILENCE if threshold exceeded, None otherwise
        """
        elapsed = time.time() - self.last_audio_time
        if elapsed >= self.silence_threshold_seconds and not self.silence_prompted:
            self.silence_prompted = True
            return InterruptionType.SILENCE
        return None

    def reset_silence_timer(self) -> None:
        """Reset the silence timer when audio is received."""
        self.last_audio_time = time.time()
        self.silence_prompted = False

    def handle(
        self,
        interrupt_type: InterruptionType,
        state: InterviewState,
    ) -> str:
        """
        Handle an interruption and return the appropriate response.

        Args:
            interrupt_type: The detected interruption type
            state: Current interview state

        Returns:
            Response string for the agent to speak
        """
        self.interrupt_count += 1

        if interrupt_type == InterruptionType.REDO:
            return self._handle_redo(state)
        elif interrupt_type == InterruptionType.SKIP:
            return self._handle_skip(state)
        elif interrupt_type == InterruptionType.CLARIFY:
            return self._handle_clarify(state)
        elif interrupt_type == InterruptionType.OFF_TRACK:
            return self._handle_off_track(state)
        elif interrupt_type == InterruptionType.SILENCE:
            return self._handle_silence(state)
        else:
            return ""

    def _handle_redo(self, state: InterviewState) -> str:
        """Repeat/rephrase the current question."""
        if state.current_question:
            return f"Of course. {state.current_question}"
        return "Sure, let me restate the question."

    def _handle_skip(self, state: InterviewState) -> str:
        """Skip current question and move on."""
        self.skip_count += 1
        # Reset depth tracking for new question
        state.consecutive_shallow = 0
        return INTERRUPTION_RESPONSES[InterruptionType.SKIP]

    def _handle_clarify(self, state: InterviewState) -> str:
        """Provide clarification without giving away the answer."""
        return state.get_clarification()

    def _handle_off_track(self, state: InterviewState) -> str:
        """Redirect candidate back to the current question."""
        if state.current_question:
            return (
                f"Interesting point, but let's bring it back. "
                f"{state.current_question}"
            )
        return INTERRUPTION_RESPONSES[InterruptionType.OFF_TRACK]

    def _handle_silence(self, state: InterviewState) -> str:
        """Prompt candidate after extended silence."""
        return INTERRUPTION_RESPONSES[InterruptionType.SILENCE]

    def get_stats(self) -> dict:
        """Return interruption statistics for the report."""
        return {
            "total_interruptions": self.interrupt_count,
            "skips": self.skip_count,
        }
