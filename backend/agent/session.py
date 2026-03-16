"""
Session state management for CyberLoop.

Tracks interview progress, persists to Firestore, handles state transitions.
States: SETUP -> ACTIVE -> COMPLETE
"""

import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

from google.cloud import firestore


class SessionStatus(str, Enum):
    SETUP = "setup"
    ACTIVE = "active"
    COMPLETE = "complete"


class InterviewMode(str, Enum):
    TECHNICAL = "technical"
    BEHAVIORAL = "behavioral"
    CODING = "coding"


@dataclass
class Exchange:
    """A single question-response pair in the interview."""
    exchange_id: str = ""
    question: str = ""
    question_id: str = ""
    response: str = ""
    score: int = 0
    # Legacy fields (kept for backwards compat)
    concepts_detected: list[str] = field(default_factory=list)
    concepts_missed: list[str] = field(default_factory=list)
    depth_level: int = 1
    timestamp: float = 0.0
    # New model-as-scorer fields
    assessment: str = ""
    key_strengths: list[str] = field(default_factory=list)
    areas_to_probe: list[str] = field(default_factory=list)
    technical_depth: int = 0  # 1-10 sub-score
    specificity: int = 0  # 1-10 sub-score
    communication: int = 0  # 1-10 sub-score
    difficulty_weight: float = 1.0
    # Coding mode sub-scores
    approach: int = 0  # 1-10: planning, problem breakdown, clarifying questions
    code_quality: int = 0  # 1-10: syntax, structure, data structures, error handling
    security_insight: int = 0  # 1-10: interpreting results, identifying attack chain
    speed: int = 0  # 1-10: reasonable pace, not stuck for extended periods

    def __post_init__(self):
        if not self.exchange_id:
            self.exchange_id = str(uuid.uuid4())[:8]
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class SessionConfig:
    """Configuration for an interview session."""
    company: str = "generic"
    level: str = "senior"
    mode: str = "technical"
    domains: list[str] = field(default_factory=lambda: ["incident_response"])


@dataclass
class InterviewState:
    """
    Full interview state. Tracks everything needed for depth ladder,
    scoring, and report generation.
    """
    session_id: str = ""
    config: SessionConfig = field(default_factory=SessionConfig)
    status: SessionStatus = SessionStatus.SETUP
    current_question: str = ""
    current_question_id: str = ""
    current_domain: str = ""
    current_depth_level: int = 1
    max_depth_reached: dict[str, int] = field(default_factory=dict)
    exchanges: list[Exchange] = field(default_factory=list)
    domain_scores: dict[str, list[int]] = field(default_factory=dict)
    behavioral_scores: dict = field(default_factory=dict)
    consecutive_shallow: int = 0
    question_index: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0
    webcam_active: bool = False
    body_language_notes: list[dict] = field(default_factory=list)
    live_transcript: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.session_id:
            self.session_id = str(uuid.uuid4())

    def add_exchange(self, exchange: Exchange) -> None:
        """Record a completed exchange."""
        self.exchanges.append(exchange)
        domain = self.current_domain or self.config.domains[0]
        if domain not in self.domain_scores:
            self.domain_scores[domain] = []
        self.domain_scores[domain].append(exchange.score)

    def advance_depth(self) -> int:
        """Move to next depth level. Returns new level."""
        self.current_depth_level += 1
        self.consecutive_shallow = 0
        domain = self.current_domain or self.config.domains[0]
        current_max = self.max_depth_reached.get(domain, 1)
        self.max_depth_reached[domain] = max(current_max, self.current_depth_level)
        return self.current_depth_level

    def record_shallow_response(self) -> bool:
        """
        Record a shallow response. Returns True if stall detected
        (2 consecutive shallow responses).
        """
        self.consecutive_shallow += 1
        return self.consecutive_shallow >= 2

    def reset_shallow_count(self) -> None:
        """Reset shallow counter after a good response."""
        self.consecutive_shallow = 0

    def get_clarification(self) -> str:
        """Return a clarification for the current question."""
        if self.current_question:
            return (
                f"Let me rephrase: {self.current_question} "
                "Feel free to approach it from any angle you're comfortable with."
            )
        return "Could you be more specific about what you'd like clarified?"

    def get_average_score(self, domain: str) -> float:
        """Get average score for a domain."""
        scores = self.domain_scores.get(domain, [])
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def get_level_label(self, score: float) -> str:
        """Map numeric score to seniority level."""
        if score >= 9:
            return "Staff/Principal"
        elif score >= 7:
            return "Senior"
        elif score >= 4:
            return "Mid"
        else:
            return "Junior"

    def to_dict(self) -> dict:
        """Serialize state for Firestore."""
        return {
            "session_id": self.session_id,
            "config": asdict(self.config),
            "status": self.status.value,
            "current_question": self.current_question,
            "current_question_id": self.current_question_id,
            "current_domain": self.current_domain,
            "current_depth_level": self.current_depth_level,
            "max_depth_reached": self.max_depth_reached,
            "exchanges": [asdict(e) for e in self.exchanges],
            "domain_scores": self.domain_scores,
            "behavioral_scores": self.behavioral_scores,
            "consecutive_shallow": self.consecutive_shallow,
            "question_index": self.question_index,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "webcam_active": self.webcam_active,
            "body_language_notes": self.body_language_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "InterviewState":
        """Deserialize from Firestore document."""
        config_data = data.get("config", {})
        config = SessionConfig(
            company=config_data.get("company", "generic"),
            level=config_data.get("level", "senior"),
            mode=config_data.get("mode", "technical"),
            domains=config_data.get("domains", ["incident_response"]),
        )
        exchanges = [
            Exchange(
                exchange_id=e.get("exchange_id", ""),
                question=e.get("question", ""),
                question_id=e.get("question_id", ""),
                response=e.get("response", ""),
                score=e.get("score", 0),
                concepts_detected=e.get("concepts_detected", []),
                concepts_missed=e.get("concepts_missed", []),
                depth_level=e.get("depth_level", 1),
                timestamp=e.get("timestamp", 0.0),
            )
            for e in data.get("exchanges", [])
        ]
        state = cls(
            session_id=data.get("session_id", ""),
            config=config,
            status=SessionStatus(data.get("status", "setup")),
            current_question=data.get("current_question", ""),
            current_question_id=data.get("current_question_id", ""),
            current_domain=data.get("current_domain", ""),
            current_depth_level=data.get("current_depth_level", 1),
            max_depth_reached=data.get("max_depth_reached", {}),
            exchanges=exchanges,
            domain_scores=data.get("domain_scores", {}),
            behavioral_scores=data.get("behavioral_scores", {}),
            consecutive_shallow=data.get("consecutive_shallow", 0),
            question_index=data.get("question_index", 0),
            started_at=data.get("started_at", 0.0),
            ended_at=data.get("ended_at", 0.0),
        )
        return state


class SessionManager:
    """
    Manages interview sessions with Firestore persistence.
    Handles create, read, update operations on session state.
    """

    def __init__(self):
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project_id:
            self.db = firestore.Client(project=project_id)
        else:
            # Local dev: use emulator or default project
            self.db = firestore.Client()
        self.collection = "sessions"

    def create_session(self, config: SessionConfig) -> InterviewState:
        """Create a new interview session and persist it."""
        state = InterviewState(config=config)
        state.status = SessionStatus.SETUP
        state.current_domain = config.domains[0] if config.domains else ""
        state.started_at = time.time()

        doc_ref = self.db.collection(self.collection).document(state.session_id)
        doc_ref.set(state.to_dict())
        return state

    def get_session(self, session_id: str) -> InterviewState | None:
        """Load session state from Firestore."""
        doc_ref = self.db.collection(self.collection).document(session_id)
        doc = doc_ref.get()
        if not doc.exists:
            return None
        return InterviewState.from_dict(doc.to_dict())

    def update_session(self, state: InterviewState) -> None:
        """Persist current state to Firestore."""
        doc_ref = self.db.collection(self.collection).document(state.session_id)
        doc_ref.set(state.to_dict(), merge=True)

    def activate_session(self, state: InterviewState) -> None:
        """Transition session from SETUP to ACTIVE."""
        state.status = SessionStatus.ACTIVE
        self.update_session(state)

    def complete_session(self, state: InterviewState) -> None:
        """Transition session to COMPLETE."""
        state.status = SessionStatus.COMPLETE
        state.ended_at = time.time()
        self.update_session(state)

    def save_exchange(self, session_id: str, exchange: Exchange) -> None:
        """Save a single exchange to a subcollection for fine-grained access."""
        doc_ref = (
            self.db.collection(self.collection)
            .document(session_id)
            .collection("exchanges")
            .document(exchange.exchange_id)
        )
        doc_ref.set(asdict(exchange))
