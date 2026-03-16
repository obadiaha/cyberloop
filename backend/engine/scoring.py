"""
CyberLoop Scoring Engine

Technical and Behavioral scoring using Gemini 3.1 Pro for semantic evaluation.
Scores responses against rubrics and expected concepts to determine candidate level.
"""

import json
import os
import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Google GenAI SDK import (lazy so unit tests can run without credentials)
# ---------------------------------------------------------------------------
_genai_client = None

def _get_genai_client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable"
            )
        _genai_client = genai.Client(api_key=api_key)
    return _genai_client

SCORING_MODEL = "gemini-2.5-pro-preview-06-05"

# ---------------------------------------------------------------------------
# Data directory resolution
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def _load_json(relative_path: str) -> dict:
    path = DATA_DIR / relative_path
    with open(path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------
class Level(str, Enum):
    JUNIOR = "Junior"
    MID = "Mid-Level"
    SENIOR = "Senior"
    STAFF = "Staff / Principal"


def score_to_level(score: float) -> Level:
    if score <= 3:
        return Level.JUNIOR
    elif score <= 6:
        return Level.MID
    elif score <= 9:
        return Level.SENIOR
    else:
        return Level.STAFF


@dataclass
class ConceptAnalysis:
    mentioned: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    red_flags_triggered: list[str] = field(default_factory=list)
    additional_concepts: list[str] = field(default_factory=list)


@dataclass
class ExchangeScore:
    question_id: str
    question_text: str
    response_text: str
    score: float  # 1-10
    level: str
    concepts: ConceptAnalysis
    feedback: str
    depth_level: int
    reasoning: str = ""


@dataclass
class DomainScore:
    domain: str
    display_name: str
    overall_score: float  # 1-10
    level: str
    depth_reached: int  # 1-4
    exchange_scores: list[ExchangeScore] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    study_recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class STARScore:
    situation_score: float  # 0-2
    action_score: float  # 0-3
    result_score: float  # 0-3
    depth_under_pressure: float  # 0-2
    total: float  # 0-10
    i_vs_we_ratio: float  # 0.0-1.0
    feedback: str
    lp_signals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BehavioralScore:
    stories: list[STARScore] = field(default_factory=list)
    overall_score: float = 0.0
    story_bank_depth: int = 0  # how many distinct stories
    lp_coverage: dict = field(default_factory=dict)
    feedback: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# TechnicalScorer
# ---------------------------------------------------------------------------
class TechnicalScorer:
    """
    Scores technical responses 1-10 mapping to:
        Junior (1-3) | Mid (4-6) | Senior (7-9) | Staff (10)

    Uses Gemini 3.1 Pro for semantic evaluation of responses against
    domain-specific rubrics and expected concepts per question.
    """

    def __init__(self, domain: str):
        self.domain = domain
        self.rubric = _load_json("rubrics/technical_rubric.json")
        self.domain_criteria = self.rubric["domain_criteria"].get(domain, {})
        self._exchange_scores: list[ExchangeScore] = []
        self._depth_reached = 0

    async def score_exchange(
        self,
        question_id: str,
        question_text: str,
        response_text: str,
        expected_concepts: list[str],
        red_flags: list[str],
        depth_level: int,
    ) -> ExchangeScore:
        """Score a single exchange using Gemini for semantic evaluation."""

        prompt = self._build_scoring_prompt(
            question_text, response_text, expected_concepts, red_flags, depth_level
        )

        client = _get_genai_client()
        response = await client.aio.models.generate_content(
            model=SCORING_MODEL,
            contents=prompt,
        )

        parsed = self._parse_scoring_response(response.text)

        exchange_score = ExchangeScore(
            question_id=question_id,
            question_text=question_text,
            response_text=response_text,
            score=parsed["score"],
            level=score_to_level(parsed["score"]).value,
            concepts=ConceptAnalysis(
                mentioned=parsed.get("concepts_mentioned", []),
                missed=parsed.get("concepts_missed", []),
                red_flags_triggered=parsed.get("red_flags_triggered", []),
                additional_concepts=parsed.get("additional_concepts", []),
            ),
            feedback=parsed.get("feedback", ""),
            depth_level=depth_level,
            reasoning=parsed.get("reasoning", ""),
        )

        self._exchange_scores.append(exchange_score)
        if depth_level > self._depth_reached and parsed["score"] >= 4:
            self._depth_reached = depth_level

        return exchange_score

    def calculate_depth_reached(self) -> int:
        """
        Determine where the candidate stalled.
        Stall = two consecutive scores below 4 at the same depth level.
        """
        if not self._exchange_scores:
            return 0

        max_passing_depth = 0
        consecutive_low = 0

        for ex in self._exchange_scores:
            if ex.score >= 4:
                max_passing_depth = max(max_passing_depth, ex.depth_level)
                consecutive_low = 0
            else:
                consecutive_low += 1

        return max_passing_depth if max_passing_depth > 0 else 1

    def calculate_domain_score(self) -> DomainScore:
        """Calculate overall domain score from all exchange scores."""
        if not self._exchange_scores:
            return DomainScore(
                domain=self.domain,
                display_name=self.domain,
                overall_score=0,
                level=Level.JUNIOR.value,
                depth_reached=0,
            )

        # Weighted average: deeper questions count more
        total_weight = 0
        weighted_sum = 0
        for ex in self._exchange_scores:
            weight = ex.depth_level  # Level 1 = weight 1, Level 4 = weight 4
            weighted_sum += ex.score * weight
            total_weight += weight

        overall = round(weighted_sum / total_weight, 1) if total_weight > 0 else 0

        # Collect strengths and gaps
        strengths = []
        gaps = []
        for ex in self._exchange_scores:
            if ex.concepts.mentioned:
                strengths.extend(ex.concepts.mentioned[:3])
            if ex.concepts.missed:
                gaps.extend(ex.concepts.missed[:3])

        # Deduplicate
        strengths = list(dict.fromkeys(strengths))
        gaps = list(dict.fromkeys(gaps))

        depth = self.calculate_depth_reached()

        return DomainScore(
            domain=self.domain,
            display_name=self.domain.replace("_", " ").title(),
            overall_score=overall,
            level=score_to_level(overall).value,
            depth_reached=depth,
            exchange_scores=self._exchange_scores,
            strengths=strengths[:10],
            gaps=gaps[:10],
        )

    # ---- Private helpers ----

    def _build_scoring_prompt(
        self,
        question: str,
        response: str,
        expected_concepts: list[str],
        red_flags: list[str],
        depth_level: int,
    ) -> str:
        level_descriptions = self.rubric["scoring_scale"]["levels"]

        return f"""You are an expert cybersecurity interview evaluator. Score this interview response.

DOMAIN: {self.domain.replace('_', ' ').title()}
DEPTH LEVEL: {depth_level} of 4

QUESTION:
{question}

CANDIDATE RESPONSE:
{response}

EXPECTED CONCEPTS (candidate should mention or demonstrate knowledge of):
{json.dumps(expected_concepts)}

RED FLAGS (if candidate says these, it indicates a gap):
{json.dumps(red_flags)}

SCORING RUBRIC:
- Junior (1-3): {json.dumps(level_descriptions['junior']['general_markers'])}
- Mid (4-6): {json.dumps(level_descriptions['mid']['general_markers'])}
- Senior (7-9): {json.dumps(level_descriptions['senior']['general_markers'])}
- Staff (10): {json.dumps(level_descriptions['staff']['general_markers'])}

DOMAIN-SPECIFIC CRITERIA:
- Junior indicators: {json.dumps(self.domain_criteria.get('junior_indicators', []))}
- Mid indicators: {json.dumps(self.domain_criteria.get('mid_indicators', []))}
- Senior indicators: {json.dumps(self.domain_criteria.get('senior_indicators', []))}
- Staff indicators: {json.dumps(self.domain_criteria.get('staff_indicators', []))}

Evaluate the response and return ONLY a JSON object (no markdown, no code fences) with these fields:
{{
  "score": <float 1-10>,
  "concepts_mentioned": [<list of expected concepts the candidate demonstrated>],
  "concepts_missed": [<list of expected concepts the candidate did not address>],
  "red_flags_triggered": [<list of red flags observed in the response>],
  "additional_concepts": [<list of relevant concepts the candidate mentioned beyond the expected list>],
  "feedback": "<2-3 sentences of specific, actionable feedback. Name what they said well and what they missed. Use real technical terms.>",
  "reasoning": "<1-2 sentences explaining why you assigned this score.>"
}}

Be precise. A score of 7 means they demonstrated senior-level thinking. A score of 4 means they applied concepts correctly but without depth. Do not inflate scores."""

    def _parse_scoring_response(self, text: str) -> dict:
        """Parse JSON from Gemini response, handling markdown fences."""
        cleaned = text.strip()
        # Strip markdown code fences
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last fence lines
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Attempt to extract JSON object via regex
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            # Fallback
            return {
                "score": 3,
                "concepts_mentioned": [],
                "concepts_missed": [],
                "red_flags_triggered": [],
                "additional_concepts": [],
                "feedback": "Unable to parse scoring response. Defaulting to conservative score.",
                "reasoning": "Parse error in scoring response.",
            }


# ---------------------------------------------------------------------------
# BehavioralScorer
# ---------------------------------------------------------------------------
class BehavioralScorer:
    """
    STAR/CARL framework evaluation for behavioral interview responses.

    Scoring dimensions:
        Situation specificity: 0-2
        Action clarity (I-vs-we): 0-3
        Result with metrics: 0-3
        Depth under pressure: 0-2
        Total: 0-10
    """

    def __init__(self, company_profile: Optional[str] = None):
        self.rubric = _load_json("rubrics/behavioral_rubric.json")
        self.company = company_profile or "generic"
        try:
            self.company_config = _load_json(f"company_profiles/{self.company}.json")
        except FileNotFoundError:
            self.company_config = _load_json("company_profiles/generic.json")
        self._story_scores: list[STARScore] = []

    async def evaluate_story(
        self,
        question_text: str,
        response_text: str,
        follow_up_responses: Optional[list[str]] = None,
        target_lps: Optional[list[str]] = None,
    ) -> STARScore:
        """Evaluate a behavioral story using STAR framework via Gemini."""

        prompt = self._build_behavioral_prompt(
            question_text, response_text, follow_up_responses or [], target_lps or []
        )

        client = _get_genai_client()
        response = await client.aio.models.generate_content(
            model=SCORING_MODEL,
            contents=prompt,
        )

        parsed = self._parse_behavioral_response(response.text)

        star_score = STARScore(
            situation_score=parsed.get("situation_score", 0),
            action_score=parsed.get("action_score", 0),
            result_score=parsed.get("result_score", 0),
            depth_under_pressure=parsed.get("depth_under_pressure", 0),
            total=parsed.get("total", 0),
            i_vs_we_ratio=parsed.get("i_vs_we_ratio", 0.0),
            feedback=parsed.get("feedback", ""),
            lp_signals=parsed.get("lp_signals", {}),
        )

        self._story_scores.append(star_score)
        return star_score

    def calculate_overall_behavioral(self) -> BehavioralScore:
        """Calculate aggregate behavioral score from all story evaluations."""
        if not self._story_scores:
            return BehavioralScore(
                overall_score=0.0,
                story_bank_depth=0,
                feedback="No behavioral stories evaluated.",
            )

        avg_total = sum(s.total for s in self._story_scores) / len(self._story_scores)
        avg_i_we = sum(s.i_vs_we_ratio for s in self._story_scores) / len(
            self._story_scores
        )

        # Aggregate LP signals
        lp_coverage: dict[str, list[float]] = {}
        for story in self._story_scores:
            for lp, strength in story.lp_signals.items():
                if lp not in lp_coverage:
                    lp_coverage[lp] = []
                lp_coverage[lp].append(
                    strength if isinstance(strength, (int, float)) else 0
                )

        lp_averages = {
            lp: round(sum(scores) / len(scores), 1)
            for lp, scores in lp_coverage.items()
        }

        # Build feedback
        i_we_threshold = (
            self.company_config.get("scoring_adjustments", {}).get(
                "behavioral_i_vs_we_threshold", 0.5
            )
        )
        i_we_feedback = ""
        if avg_i_we < i_we_threshold:
            i_we_feedback = (
                f" Your I-vs-we ratio is {avg_i_we:.0%}, below the {i_we_threshold:.0%} "
                f"target for this company. Use more 'I' statements to clarify your individual contribution."
            )

        return BehavioralScore(
            stories=self._story_scores,
            overall_score=round(avg_total, 1),
            story_bank_depth=len(self._story_scores),
            lp_coverage=lp_averages,
            feedback=f"Average STAR score: {avg_total:.1f}/10 across {len(self._story_scores)} stories.{i_we_feedback}",
        )

    @staticmethod
    def calculate_i_vs_we_ratio(text: str) -> float:
        """
        Calculate the ratio of first-person singular vs plural statements.
        Returns float between 0.0 and 1.0 where 1.0 = all 'I' statements.
        """
        words = text.lower().split()
        i_count = sum(1 for w in words if w in ("i", "i'd", "i've", "i'm", "i'll", "my", "me", "myself"))
        we_count = sum(1 for w in words if w in ("we", "we'd", "we've", "we're", "we'll", "our", "us", "ourselves"))

        total = i_count + we_count
        if total == 0:
            return 0.5  # neutral if no pronouns detected

        return round(i_count / total, 2)

    # ---- Private helpers ----

    def _build_behavioral_prompt(
        self,
        question: str,
        response: str,
        follow_ups: list[str],
        target_lps: list[str],
    ) -> str:
        star_criteria = self.rubric["star_scoring"]
        follow_up_text = ""
        if follow_ups:
            follow_up_text = "\n\nFOLLOW-UP RESPONSES:\n" + "\n---\n".join(follow_ups)

        lp_text = ""
        if target_lps:
            lp_text = f"\n\nTARGET LEADERSHIP PRINCIPLES: {json.dumps(target_lps)}"

        company_context = ""
        if self.company != "generic":
            bar_focus = self.company_config.get("behavioral_emphasis", {}).get(
                "bar_raiser_focus", []
            )
            if bar_focus:
                company_context = (
                    f"\n\nCOMPANY INTERVIEW STYLE ({self.company.upper()}):\n"
                    + "\n".join(f"- {f}" for f in bar_focus)
                )

        return f"""You are an expert behavioral interview evaluator using the STAR framework.

QUESTION:
{question}

CANDIDATE RESPONSE:
{response}{follow_up_text}{lp_text}{company_context}

SCORING CRITERIA:

SITUATION (0-2):
{json.dumps(star_criteria['situation']['criteria'], indent=2)}

ACTION (0-3):
{json.dumps(star_criteria['action']['criteria'], indent=2)}
Note: Calculate I-vs-we ratio. Target for senior roles: >60% "I" statements.

RESULT (0-3):
{json.dumps(star_criteria['result']['criteria'], indent=2)}

DEPTH UNDER PRESSURE (0-2):
{json.dumps(star_criteria['depth_under_pressure']['criteria'], indent=2)}

Return ONLY a JSON object (no markdown, no code fences):
{{
  "situation_score": <0-2>,
  "action_score": <0-3>,
  "result_score": <0-3>,
  "depth_under_pressure": <0-2>,
  "total": <sum, 0-10>,
  "i_vs_we_ratio": <float 0.0-1.0>,
  "feedback": "<specific feedback: what was strong, what was missing, what to improve>",
  "lp_signals": {{<leadership_principle_id>: <strength 0-3 for each LP demonstrated>}}
}}

Be rigorous. A 2/3 on Action means clear I-statements with reasoning. A 1/3 means mostly 'we' language. Score what they actually said, not what they meant."""

    def _parse_behavioral_response(self, text: str) -> dict:
        """Parse JSON from Gemini behavioral evaluation response."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {
                "situation_score": 1,
                "action_score": 1,
                "result_score": 1,
                "depth_under_pressure": 1,
                "total": 4,
                "i_vs_we_ratio": 0.5,
                "feedback": "Unable to parse behavioral scoring response.",
                "lp_signals": {},
            }
