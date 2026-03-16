"""
CyberLoop Question Tree Engine

Loads question tree JSON for a selected domain and traverses based on
keyword/concept detection in candidate responses. Handles branching,
depth ladder advancement, and concept tracking.
"""

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Data directory resolution
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _load_question_tree(domain: str) -> dict:
    path = DATA_DIR / "question_trees" / f"{domain}.json"
    with open(path, "r") as f:
        return json.load(f)


def _load_behavioral_bank() -> dict:
    path = DATA_DIR / "question_trees" / "behavioral_bank.json"
    with open(path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class QuestionNode:
    """Represents a question at a specific depth in the tree."""
    id: str
    text: str
    level: int
    expected_concepts: list[str] = field(default_factory=list)
    red_flags: list[str] = field(default_factory=list)
    category: str = ""
    follow_up_on_miss: str = ""


@dataclass
class ConceptTracker:
    """Tracks which concepts a candidate has mentioned vs missed across the session."""
    mentioned: set = field(default_factory=set)
    missed: set = field(default_factory=set)
    red_flags_triggered: set = field(default_factory=set)

    def record(self, mentioned: list[str], missed: list[str], red_flags: list[str]):
        self.mentioned.update(mentioned)
        self.missed.update(missed)
        self.red_flags_triggered.update(red_flags)

    def to_dict(self) -> dict:
        return {
            "mentioned": sorted(self.mentioned),
            "missed": sorted(self.missed),
            "red_flags_triggered": sorted(self.red_flags_triggered),
        }


@dataclass
class TraversalState:
    """Tracks the current position in the question tree."""
    domain: str
    current_root_index: int = 0
    current_depth: int = 1
    questions_asked: list[str] = field(default_factory=list)  # question IDs
    depth_reached: int = 1
    stall_count: int = 0  # consecutive low scores at current depth
    max_stall_before_advance: int = 2
    is_complete: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Concept Detection
# ---------------------------------------------------------------------------
class ConceptDetector:
    """
    Detects whether expected concepts are present in a candidate's response.
    Uses keyword matching with fuzzy normalization. For production, this would
    be augmented by Gemini semantic matching (done in the scoring engine).
    """

    @staticmethod
    def normalize(text: str) -> str:
        """Normalize text for matching: lowercase, collapse whitespace, strip punctuation."""
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def concept_to_keywords(concept: str) -> list[str]:
        """
        Convert a concept ID into searchable keywords.
        e.g., 'dns_exfiltration' -> ['dns exfiltration', 'dns exfil']
        e.g., 'sysmon_event_10' -> ['sysmon event 10', 'sysmon', 'event 10', 'event id 10']
        """
        # Replace underscores with spaces
        base = concept.replace("_", " ")
        keywords = [base]

        # Add individual significant words (skip very short ones)
        words = base.split()
        if len(words) > 1:
            for w in words:
                if len(w) > 3:
                    keywords.append(w)

        # Special patterns
        # Event IDs: "4656" or "event 4656" or "event id 4656"
        numbers = re.findall(r'\d+', concept)
        for num in numbers:
            keywords.append(num)
            keywords.append(f"event {num}")
            keywords.append(f"event id {num}")

        # Tool names that might be referenced differently
        tool_aliases = {
            "volatility3": ["volatility", "vol3", "vol.py"],
            "volatility": ["volatility", "vol", "vol.py"],
            "ftk_imager": ["ftk", "ftk imager", "accessdata"],
            "crowdstrike": ["crowdstrike", "falcon", "cs"],
            "mimikatz": ["mimikatz", "mimi"],
            "cobalt_strike": ["cobalt strike", "cs beacon", "beacon"],
            "wireshark": ["wireshark", "pcap", "packet capture"],
            "splunk": ["splunk", "spl"],
            "sentinel": ["sentinel", "kql"],
            "yara": ["yara", "yara rule"],
            "sigma": ["sigma", "sigma rule"],
            "atomic_red_team": ["atomic red team", "art", "atomic"],
            "caldera": ["caldera", "mitre caldera"],
            "log2timeline": ["log2timeline", "plaso", "l2t"],
        }
        concept_lower = concept.lower()
        for key, aliases in tool_aliases.items():
            if key in concept_lower:
                keywords.extend(aliases)

        return list(set(keywords))

    def detect_concepts(
        self, response: str, expected_concepts: list[str]
    ) -> tuple[list[str], list[str]]:
        """
        Detect which expected concepts are mentioned in the response.
        Returns (mentioned, missed).
        """
        normalized_response = self.normalize(response)
        mentioned = []
        missed = []

        for concept in expected_concepts:
            keywords = self.concept_to_keywords(concept)
            found = any(kw in normalized_response for kw in keywords)
            if found:
                mentioned.append(concept)
            else:
                missed.append(concept)

        return mentioned, missed

    def detect_red_flags(self, response: str, red_flags: list[str]) -> list[str]:
        """Detect if any red flag behaviors are present in the response."""
        normalized = self.normalize(response)
        triggered = []
        for flag in red_flags:
            keywords = self.concept_to_keywords(flag)
            if any(kw in normalized for kw in keywords):
                triggered.append(flag)
        return triggered

    def find_trigger_match(
        self, response: str, depth_probes: list[dict]
    ) -> Optional[dict]:
        """
        Find the best matching depth probe based on trigger concepts
        detected in the response.
        """
        normalized = self.normalize(response)
        best_match = None
        best_match_count = 0

        for probe in depth_probes:
            trigger_concepts = probe.get("trigger_concepts", [])
            match_count = 0
            for concept in trigger_concepts:
                keywords = self.concept_to_keywords(concept)
                if any(kw in normalized for kw in keywords):
                    match_count += 1

            # Require at least 1 trigger concept match, prefer more
            if match_count > best_match_count:
                best_match = probe
                best_match_count = match_count

        return best_match


# ---------------------------------------------------------------------------
# Question Tree Navigator
# ---------------------------------------------------------------------------
class QuestionTreeNavigator:
    """
    Navigates a domain-specific question tree using depth ladder logic.

    Flow:
    1. Start with root question at level 1
    2. After response, detect concepts
    3. If concepts match triggers -> advance to deeper probe
    4. If concepts miss -> stay at current level, try next root question
    5. Track stall points (where candidate stops advancing)
    """

    def __init__(self, domain: str):
        self.domain = domain
        self.tree = _load_question_tree(domain)
        self.root_questions = self.tree.get("root_questions", [])
        self.state = TraversalState(domain=domain)
        self.concept_detector = ConceptDetector()
        self.concept_tracker = ConceptTracker()
        self._current_probes: list[dict] = []  # depth probes for current root question

    def get_first_question(self) -> QuestionNode:
        """Get the first root question to start the interview."""
        if not self.root_questions:
            raise ValueError(f"No root questions found for domain: {self.domain}")

        root = self.root_questions[0]
        self._current_probes = root.get("depth_probes", [])

        node = QuestionNode(
            id=root["id"],
            text=root["text"],
            level=root.get("level", 1),
            expected_concepts=root.get("expected_concepts", []),
            red_flags=root.get("red_flags", []),
            category=root.get("category", ""),
        )
        self.state.questions_asked.append(node.id)
        return node

    def get_next_question(
        self,
        response: str,
        score: Optional[float] = None,
    ) -> Optional[QuestionNode]:
        """
        Determine the next question based on the candidate's response.

        Args:
            response: The candidate's response text
            score: Optional score from the scoring engine (1-10).
                   If provided, used alongside concept detection for advancement.

        Returns:
            Next QuestionNode, or None if the interview section is complete.
        """
        if self.state.is_complete:
            return None

        # Detect concepts in response
        current_root = self.root_questions[self.state.current_root_index]
        current_expected = current_root.get("expected_concepts", [])

        # If we're in a depth probe, use that probe's expected concepts
        if self.state.current_depth > 1 and self._current_probes:
            for probe in self._current_probes:
                if probe.get("level", 1) == self.state.current_depth:
                    current_expected = probe.get("expected_concepts", [])
                    break

        mentioned, missed = self.concept_detector.detect_concepts(
            response, current_expected
        )
        red_flags = self.concept_detector.detect_red_flags(
            response, current_root.get("red_flags", [])
        )
        self.concept_tracker.record(mentioned, missed, red_flags)

        # Determine advancement
        should_advance = self._should_advance_depth(mentioned, missed, score)

        if should_advance and self._current_probes:
            # Try to find a matching depth probe
            probe = self.concept_detector.find_trigger_match(
                response, [p for p in self._current_probes if p.get("level", 1) > self.state.current_depth]
            )

            if probe:
                self.state.current_depth = probe["level"]
                self.state.depth_reached = max(
                    self.state.depth_reached, self.state.current_depth
                )
                self.state.stall_count = 0

                node = QuestionNode(
                    id=f"{current_root['id']}_d{probe['level']}",
                    text=probe["question"],
                    level=probe["level"],
                    expected_concepts=probe.get("expected_concepts", []),
                    red_flags=probe.get("red_flags", []),
                    follow_up_on_miss=probe.get("follow_up_on_miss", ""),
                )
                self.state.questions_asked.append(node.id)
                return node

        # If didn't advance (or no probe matched), move to next root question
        self.state.stall_count += 1

        if self.state.stall_count >= self.state.max_stall_before_advance:
            return self._advance_to_next_root()

        # Give one more chance with a follow-up hint if available
        if missed and not should_advance:
            # Check for follow_up_on_miss in current probes
            for probe in self._current_probes:
                if probe.get("follow_up_on_miss") and probe.get("level", 1) == self.state.current_depth + 1:
                    return QuestionNode(
                        id=f"{current_root['id']}_hint",
                        text=probe["follow_up_on_miss"],
                        level=self.state.current_depth,
                        expected_concepts=current_expected,
                        red_flags=[],
                    )

        return self._advance_to_next_root()

    def _should_advance_depth(
        self,
        mentioned: list[str],
        missed: list[str],
        score: Optional[float],
    ) -> bool:
        """Determine if candidate should advance to the next depth level."""
        # If we have a score, use it as primary signal
        if score is not None:
            return score >= 4  # Mid-level or above means advance

        # Otherwise, use concept coverage ratio
        total = len(mentioned) + len(missed)
        if total == 0:
            return False

        coverage = len(mentioned) / total
        return coverage >= 0.4  # At least 40% of concepts mentioned

    def _advance_to_next_root(self) -> Optional[QuestionNode]:
        """Move to the next root question."""
        self.state.current_root_index += 1
        self.state.current_depth = 1
        self.state.stall_count = 0

        if self.state.current_root_index >= len(self.root_questions):
            self.state.is_complete = True
            return None

        root = self.root_questions[self.state.current_root_index]
        self._current_probes = root.get("depth_probes", [])

        node = QuestionNode(
            id=root["id"],
            text=root["text"],
            level=1,
            expected_concepts=root.get("expected_concepts", []),
            red_flags=root.get("red_flags", []),
            category=root.get("category", ""),
        )
        self.state.questions_asked.append(node.id)
        return node

    def get_state(self) -> dict:
        """Return current traversal state for persistence."""
        return {
            **self.state.to_dict(),
            "concept_tracker": self.concept_tracker.to_dict(),
        }


# ---------------------------------------------------------------------------
# Behavioral Question Navigator
# ---------------------------------------------------------------------------
class BehavioralNavigator:
    """
    Navigates the behavioral question bank. Selects questions based on
    target themes and leadership principles. Tracks which themes have been
    covered.
    """

    def __init__(self, target_themes: Optional[list[str]] = None):
        self.bank = _load_behavioral_bank()
        self.themes = self.bank.get("themes", [])
        self.target_themes = target_themes
        self._theme_index = 0
        self._question_index = 0
        self._questions_asked: list[str] = []
        self._current_question: Optional[dict] = None

        # Filter to target themes if specified
        if target_themes:
            self.themes = [
                t for t in self.themes if t["theme"] in target_themes
            ]

    def get_first_question(self) -> QuestionNode:
        """Get the first behavioral question."""
        if not self.themes:
            raise ValueError("No behavioral themes available")

        theme = self.themes[0]
        question = theme["questions"][0]
        self._current_question = question

        node = QuestionNode(
            id=question["id"],
            text=question["text"],
            level=1,
            category=theme["theme"],
        )
        self._questions_asked.append(node.id)
        return node

    def get_star_probes(self) -> dict:
        """Get STAR follow-up probes for the current question."""
        if self._current_question:
            return self._current_question.get("star_probes", {})
        return {}

    def get_depth_probes(self) -> list[str]:
        """Get depth probes for the current question (used to pressure-test)."""
        if self._current_question:
            return self._current_question.get("depth_probes", [])
        return []

    def get_next_question(self) -> Optional[QuestionNode]:
        """Get the next behavioral question, cycling through themes."""
        # Move to next question in current theme
        self._question_index += 1
        theme = self.themes[self._theme_index]

        if self._question_index >= len(theme["questions"]):
            # Move to next theme
            self._theme_index += 1
            self._question_index = 0

            if self._theme_index >= len(self.themes):
                return None  # All themes exhausted

            theme = self.themes[self._theme_index]

        question = theme["questions"][self._question_index]
        self._current_question = question

        node = QuestionNode(
            id=question["id"],
            text=question["text"],
            level=1,
            category=theme["theme"],
        )
        self._questions_asked.append(node.id)
        return node

    def get_target_lps(self) -> list[str]:
        """Get leadership principles for the current theme."""
        if self._theme_index < len(self.themes):
            return self.themes[self._theme_index].get("leadership_principles", [])
        return []

    def get_state(self) -> dict:
        return {
            "theme_index": self._theme_index,
            "question_index": self._question_index,
            "questions_asked": self._questions_asked,
        }


# ---------------------------------------------------------------------------
# Alias for backwards-compatible import: from engine.question_tree import QuestionTreeEngine
# ---------------------------------------------------------------------------
QuestionTreeEngine = QuestionTreeNavigator


# ---------------------------------------------------------------------------
# Utility: List available domains
# ---------------------------------------------------------------------------
def list_available_domains() -> list[dict]:
    """List all available question tree domains with metadata."""
    trees_dir = DATA_DIR / "question_trees"
    domains = []
    for path in sorted(trees_dir.glob("*.json")):
        if path.stem == "behavioral_bank":
            continue
        try:
            with open(path) as f:
                tree = json.load(f)
            domains.append({
                "id": tree.get("domain", path.stem),
                "display_name": tree.get("display_name", path.stem.replace("_", " ").title()),
                "description": tree.get("description", ""),
                "question_count": len(tree.get("root_questions", [])),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return domains
