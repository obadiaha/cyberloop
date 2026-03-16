"""
CyberLoop Report Card Generator

Analyzes full interview transcripts using Gemini 3.1 Pro to produce
structured report cards with per-domain scores, feedback, strengths,
gaps, and study recommendations.

Supports both technical and behavioral interview modes.
"""

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# ---------------------------------------------------------------------------
# Google GenAI SDK import (lazy so unit tests run without credentials)
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


REPORT_MODEL = "gemini-2.5-pro"


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class DomainReport:
    """Per-domain breakdown in the report card."""

    domain: str
    display_name: str
    score: float  # 1-10
    level: str  # Junior / Mid-Level / Senior / Staff
    depth_reached: int  # 1-4
    feedback: str  # 2-3 sentence specific feedback
    concepts_demonstrated: list[str] = field(default_factory=list)
    concepts_missed: list[str] = field(default_factory=list)
    study_topics: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BehavioralReport:
    """Behavioral mode report section."""

    overall_score: float  # 0-10
    star_structure_score: float  # average across stories
    i_vs_we_ratio: float  # 0.0-1.0
    depth_under_pressure: str  # "improved" | "stable" | "degraded"
    story_count: int
    feedback: str
    lp_coverage: dict = field(default_factory=dict)  # LP -> strength

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReportCard:
    """Full structured report card returned to the frontend / API."""

    session_id: str
    company: str
    level: str
    mode: str  # "technical" | "behavioral" | "mixed"
    overall_score: float
    overall_level: str
    duration_minutes: float
    total_exchanges: int

    # Technical
    domain_reports: list[DomainReport] = field(default_factory=list)

    # Behavioral
    behavioral_report: Optional[BehavioralReport] = None

    # Summary
    top_strengths: list[str] = field(default_factory=list)
    top_areas_to_improve: list[str] = field(default_factory=list)
    study_recommendations: list[str] = field(default_factory=list)

    generated_at: float = 0.0

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = time.time()

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _score_to_level(score: float) -> str:
    if score <= 3:
        return "Junior"
    elif score <= 6:
        return "Mid-Level"
    elif score <= 9:
        return "Senior"
    else:
        return "Staff / Principal"


def _build_transcript_text(exchanges: list) -> str:
    """Build a readable transcript from exchange objects."""
    lines = []
    for i, ex in enumerate(exchanges, 1):
        q = ex.get("question", "") if isinstance(ex, dict) else getattr(ex, "question", "")
        r = ex.get("response", "") if isinstance(ex, dict) else getattr(ex, "response", "")
        depth = ex.get("depth_level", 1) if isinstance(ex, dict) else getattr(ex, "depth_level", 1)
        lines.append(f"[Exchange {i} | Depth {depth}]")
        lines.append(f"Interviewer: {q}")
        lines.append(f"Candidate: {r}")
        lines.append("")
    return "\n".join(lines)


def _parse_json_response(text: str) -> dict:
    """Parse JSON from Gemini response, handling markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


# ---------------------------------------------------------------------------
# ReportGenerator
# ---------------------------------------------------------------------------
class ReportGenerator:
    """
    Generates structured report cards from completed interview sessions.

    Uses Gemini 3.1 Pro to analyze the full transcript holistically,
    producing per-domain scores, feedback, strengths, gaps, and study
    recommendations.
    """

    def __init__(self):
        self._firestore_client = None

    def _get_firestore(self):
        """Lazy Firestore client initialization."""
        if self._firestore_client is None:
            project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
            if project_id:
                from google.cloud import firestore

                self._firestore_client = firestore.Client(project=project_id)
        return self._firestore_client

    def generate_report_sync(
        self,
        session_state: dict,
        exchanges: list,
        scores: Optional[dict] = None,
    ) -> ReportCard:
        """
        Synchronous wrapper around generate_report() for CLI / script usage.

        Safe to call from a fresh Python process (no running event loop).
        If an event loop is already running (e.g. inside a notebook), it falls
        back to a thread-pool so the inner asyncio.run() can start its own loop.

        Args: same as generate_report().
        Returns: ReportCard dataclass.
        """
        import concurrent.futures

        coro = self.generate_report(session_state, exchanges, scores)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # We're inside an active event loop (Jupyter, FastAPI test, etc.)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)

    async def generate_report(
        self,
        session_state: dict,
        exchanges: list,
        scores: Optional[dict] = None,
    ) -> ReportCard:
        """
        Generate a full report card from session data.

        Args:
            session_state: Session state dict (from InterviewState.to_dict()
                           or a plain dict with config, status, domain_scores, etc.)
            exchanges: List of Exchange objects or dicts with question/response/score/depth_level
            scores: Optional pre-computed scores dict {domain: DomainScore.to_dict()}

        Returns:
            ReportCard dataclass ready for JSON serialization.
        """
        config = session_state.get("config", {})
        mode = config.get("mode", "technical")
        company = config.get("company", "generic")
        level = config.get("level", "senior")
        session_id = session_state.get("session_id", "unknown")

        # Calculate duration
        started = session_state.get("started_at", 0)
        ended = session_state.get("ended_at", 0)
        duration = round((ended - started) / 60, 1) if started and ended else 0.0

        # Build transcript for Gemini analysis
        transcript = _build_transcript_text(exchanges)

        if mode == "behavioral":
            report = await self._generate_behavioral_report(
                session_id=session_id,
                company=company,
                level=level,
                transcript=transcript,
                exchanges=exchanges,
                session_state=session_state,
                duration=duration,
            )
        else:
            report = await self._generate_technical_report(
                session_id=session_id,
                company=company,
                level=level,
                mode=mode,
                transcript=transcript,
                exchanges=exchanges,
                session_state=session_state,
                scores=scores,
                duration=duration,
            )

        # Persist to Firestore if available
        self._save_to_firestore(session_id, report)

        return report

    # ---- Technical Report ----

    async def _generate_technical_report(
        self,
        session_id: str,
        company: str,
        level: str,
        mode: str,
        transcript: str,
        exchanges: list,
        session_state: dict,
        scores: Optional[dict],
        duration: float,
    ) -> ReportCard:
        """Generate report for technical interview mode."""
        config = session_state.get("config", {})
        domains = config.get("domains", [])
        max_depth = session_state.get("max_depth_reached", {})
        domain_scores_raw = session_state.get("domain_scores", {})

        # Use Gemini for holistic transcript analysis
        gemini_analysis = await self._analyze_transcript_with_gemini(
            transcript=transcript,
            mode="technical",
            company=company,
            level=level,
            domains=domains,
        )

        # Build domain reports
        domain_reports = []
        for domain in domains:
            raw_scores = domain_scores_raw.get(domain, [])
            avg_score = sum(raw_scores) / len(raw_scores) if raw_scores else 0
            depth = max_depth.get(domain, 1)

            # Priority: Use real average score if we have exchanges, 
            # fall back to Gemini analysis for empty/hallucinated data
            real_avg = round(avg_score, 1) if raw_scores else 0
            
            # Use real average if we have data, otherwise take Gemini's guess
            final_score = real_avg if raw_scores else domain_analysis.get("score", 0)

            dr = DomainReport(
                domain=domain,
                display_name=domain.replace("_", " ").title(),
                score=final_score,
                level=_score_to_level(final_score),
                depth_reached=depth,
                feedback=domain_analysis.get("feedback", self._compute_fallback_feedback(domain, exchanges)),
                concepts_demonstrated=domain_analysis.get("concepts_demonstrated", []),
                concepts_missed=domain_analysis.get("concepts_missed", []),
                study_topics=domain_analysis.get("study_topics", []),
            )
            domain_reports.append(dr)

        # Compute overall score
        if domain_reports:
            overall_score = round(
                sum(dr.score for dr in domain_reports) / len(domain_reports), 1
            )
        else:
            overall_score = 0

        report = ReportCard(
            session_id=session_id,
            company=company,
            level=level,
            mode=mode,
            overall_score=overall_score,
            overall_level=_score_to_level(overall_score),
            duration_minutes=duration,
            total_exchanges=len(exchanges),
            domain_reports=domain_reports,
            top_strengths=gemini_analysis.get("top_strengths", [])[:3],
            top_areas_to_improve=gemini_analysis.get("top_areas_to_improve", [])[:3],
            study_recommendations=gemini_analysis.get("study_recommendations", [])[:5],
        )

        return report

    # ---- Behavioral Report ----

    async def _generate_behavioral_report(
        self,
        session_id: str,
        company: str,
        level: str,
        transcript: str,
        exchanges: list,
        session_state: dict,
        duration: float,
    ) -> ReportCard:
        """Generate report for behavioral interview mode."""
        behavioral_scores = session_state.get("behavioral_scores", {})

        # Use Gemini for holistic analysis
        gemini_analysis = await self._analyze_transcript_with_gemini(
            transcript=transcript,
            mode="behavioral",
            company=company,
            level=level,
            domains=[],
        )

        behavioral_analysis = gemini_analysis.get("behavioral_report", {})

        # Compute I-vs-we ratio from exchanges
        i_vs_we = self._compute_i_vs_we_ratio(exchanges)

        behavioral_report = BehavioralReport(
            overall_score=behavioral_analysis.get(
                "overall_score",
                behavioral_scores.get("overall_score", 0),
            ),
            star_structure_score=behavioral_analysis.get("star_structure_score", 0),
            i_vs_we_ratio=behavioral_analysis.get("i_vs_we_ratio", i_vs_we),
            depth_under_pressure=behavioral_analysis.get("depth_under_pressure", "stable"),
            story_count=behavioral_analysis.get("story_count", len(exchanges)),
            feedback=behavioral_analysis.get("feedback", ""),
            lp_coverage=behavioral_analysis.get("lp_coverage", {}),
        )

        overall_score = behavioral_report.overall_score

        report = ReportCard(
            session_id=session_id,
            company=company,
            level=level,
            mode="behavioral",
            overall_score=overall_score,
            overall_level=_score_to_level(overall_score),
            duration_minutes=duration,
            total_exchanges=len(exchanges),
            behavioral_report=behavioral_report,
            top_strengths=gemini_analysis.get("top_strengths", [])[:3],
            top_areas_to_improve=gemini_analysis.get("top_areas_to_improve", [])[:3],
            study_recommendations=gemini_analysis.get("study_recommendations", [])[:5],
        )

        return report

    # ---- Gemini Transcript Analysis ----

    async def _analyze_transcript_with_gemini(
        self,
        transcript: str,
        mode: str,
        company: str,
        level: str,
        domains: list[str],
    ) -> dict:
        """
        Send full transcript to Gemini 3.1 Pro for holistic analysis.

        Returns a structured dict with scores, feedback, strengths, and recommendations.
        """
        if mode == "behavioral":
            prompt = self._build_behavioral_analysis_prompt(
                transcript, company, level
            )
        else:
            prompt = self._build_technical_analysis_prompt(
                transcript, company, level, domains
            )

        try:
            client = _get_genai_client()
            response = await client.aio.models.generate_content(
                model=REPORT_MODEL,
                contents=prompt,
            )
            parsed = _parse_json_response(response.text)
            if parsed:
                return parsed
        except Exception as e:
            # Log but don't fail, we'll use fallback scoring
            import logging

            logging.getLogger(__name__).warning(
                "Gemini report analysis failed: %s. Using fallback scoring.", e
            )

        return {}

    def _build_technical_analysis_prompt(
        self,
        transcript: str,
        company: str,
        level: str,
        domains: list[str],
    ) -> str:
        domain_list = ", ".join(d.replace("_", " ").title() for d in domains)

        return f"""You are an expert cybersecurity interview evaluator. Analyze this complete interview transcript and produce a structured report card.

INTERVIEW CONTEXT:
- Company style: {company}
- Target level: {level}
- Domains evaluated: {domain_list}

FULL TRANSCRIPT:
{transcript}

SCORING SCALE:
- 1-3 (Junior): Names tools/concepts correctly, follows procedures, explains what not why
- 4-6 (Mid-Level): Applies concepts to scenarios, considers false positives, has practical experience
- 7-9 (Senior): Architects solutions with tradeoffs, considers attacker perspective, connects to business impact
- 10 (Staff/Principal): Challenges premises, reframes problems, systemic/organizational thinking

Analyze the transcript holistically and return ONLY a JSON object (no markdown, no code fences):
{{
  "domain_reports": {{
    "{domains[0] if domains else 'general'}": {{
      "score": <float 1-10>,
      "feedback": "<2-3 sentences: what they said well, what they missed, how to improve. Use specific technical terms from their responses.>",
      "concepts_demonstrated": ["<concepts the candidate clearly demonstrated>"],
      "concepts_missed": ["<important concepts the candidate should have mentioned but didn't>"],
      "study_topics": ["<specific topics to study, with enough detail to be actionable>"]
    }}
  }},
  "top_strengths": [
    "<strength 1: specific, citing what they said>",
    "<strength 2>",
    "<strength 3>"
  ],
  "top_areas_to_improve": [
    "<area 1: specific gap with what they should learn>",
    "<area 2>",
    "<area 3>"
  ],
  "study_recommendations": [
    "<specific topic 1 with context on why>",
    "<specific topic 2>",
    "<specific topic 3>",
    "<specific topic 4>",
    "<specific topic 5>"
  ]
}}

Be precise and specific. Reference exact things the candidate said or failed to say. Do not give generic feedback."""

    def _build_behavioral_analysis_prompt(
        self,
        transcript: str,
        company: str,
        level: str,
    ) -> str:
        return f"""You are an expert behavioral interview evaluator using the STAR framework. Analyze this complete interview transcript.

INTERVIEW CONTEXT:
- Company style: {company}
- Target level: {level}
- Mode: Behavioral

FULL TRANSCRIPT:
{transcript}

STAR SCORING:
- Situation (0-2): Specificity of context (named project, team, timeframe, stakes)
- Action (0-3): Individual contribution clarity, I-vs-we ratio, decision rationale
- Result (0-3): Quantified outcomes, business impact, learning stated
- Depth Under Pressure (0-2): Quality under follow-up probing (improves, stable, degrades)
- Total: 0-10

I-VS-WE RATIO: Count first-person singular (I, my, me, myself) vs plural (we, our, us). Target >60% "I" for senior roles.

DEPTH UNDER PRESSURE:
- "improved": Candidate added richer detail under probing, suggesting real experience
- "stable": Maintained quality but didn't add depth
- "degraded": Contradicted themselves or got vague, suggesting memorized/fabricated story

Analyze holistically and return ONLY a JSON object (no markdown, no code fences):
{{
  "behavioral_report": {{
    "overall_score": <float 0-10>,
    "star_structure_score": <float 0-10 average>,
    "i_vs_we_ratio": <float 0.0-1.0>,
    "depth_under_pressure": "<improved|stable|degraded>",
    "story_count": <int>,
    "feedback": "<3-4 sentences: STAR structure quality, I-vs-we assessment, how they held up under probing>",
    "lp_coverage": {{<leadership_principle_id>: <strength 0-3>}}
  }},
  "top_strengths": [
    "<strength 1>",
    "<strength 2>",
    "<strength 3>"
  ],
  "top_areas_to_improve": [
    "<area 1>",
    "<area 2>",
    "<area 3>"
  ],
  "study_recommendations": [
    "<recommendation 1>",
    "<recommendation 2>",
    "<recommendation 3>"
  ]
}}

Be rigorous. Reference specific things the candidate said. A score of 7+ means genuinely strong STAR stories with clear individual contribution and quantified results."""

    # ---- Fallback / utility methods ----

    def _compute_fallback_feedback(self, domain: str, exchanges: list) -> str:
        """Generate basic feedback without Gemini (fallback)."""
        all_detected = []
        all_missed = []
        for ex in exchanges:
            if isinstance(ex, dict):
                all_detected.extend(ex.get("concepts_detected", []))
                all_missed.extend(ex.get("concepts_missed", []))
            else:
                all_detected.extend(getattr(ex, "concepts_detected", []))
                all_missed.extend(getattr(ex, "concepts_missed", []))

        detected_str = ", ".join(list(set(all_detected))[:5]) if all_detected else "limited concepts"
        missed_str = ", ".join(list(set(all_missed))[:5]) if all_missed else "none identified"

        display = domain.replace("_", " ").title()
        return (
            f"In {display}, you demonstrated knowledge of: {detected_str}. "
            f"Key gaps include: {missed_str}. "
            f"Focus on building depth in the missed areas to strengthen your interview performance."
        )

    @staticmethod
    def _compute_i_vs_we_ratio(exchanges: list) -> float:
        """Compute I-vs-we ratio from all candidate responses."""
        all_text = []
        for ex in exchanges:
            r = ex.get("response", "") if isinstance(ex, dict) else getattr(ex, "response", "")
            all_text.append(r)

        combined = " ".join(all_text).lower()
        words = combined.split()
        i_words = {"i", "i'd", "i've", "i'm", "i'll", "my", "me", "myself"}
        we_words = {"we", "we'd", "we've", "we're", "we'll", "our", "us", "ourselves"}

        i_count = sum(1 for w in words if w in i_words)
        we_count = sum(1 for w in words if w in we_words)
        total = i_count + we_count

        if total == 0:
            return 0.5
        return round(i_count / total, 2)

    # ---- Firestore persistence ----

    def _save_to_firestore(self, session_id: str, report: ReportCard) -> None:
        """Save the report card to Firestore if available."""
        db = self._get_firestore()
        if db is None:
            return

        try:
            doc_ref = (
                db.collection("sessions")
                .document(session_id)
                .collection("report_card")
                .document("latest")
            )
            doc_ref.set(report.to_dict())
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "Failed to save report to Firestore: %s", e
            )


# ---------------------------------------------------------------------------
# Convenience function for offline / script usage
# ---------------------------------------------------------------------------
async def generate_report_from_exchanges(
    exchanges: list[dict],
    domain: str = "incident_response",
    company: str = "generic",
    level: str = "senior",
    mode: str = "technical",
    session_id: str = "offline",
) -> ReportCard:
    """
    Convenience wrapper for generating a report from a list of exchange dicts.
    Used by scripts/analyze_transcript.py for offline analysis.

    Args:
        exchanges: List of dicts with keys: question, response, score, depth_level,
                   concepts_detected, concepts_missed
        domain: Domain being evaluated
        company: Company style
        level: Target level
        mode: "technical" or "behavioral"
        session_id: Session identifier

    Returns:
        ReportCard
    """
    # Build a minimal session state
    started = time.time()
    domain_scores_raw = {}
    max_depth = {}

    for ex in exchanges:
        d = ex.get("domain", domain)
        score = ex.get("score", 0)
        depth = ex.get("depth_level", 1)

        if d not in domain_scores_raw:
            domain_scores_raw[d] = []
        domain_scores_raw[d].append(score)
        max_depth[d] = max(max_depth.get(d, 0), depth)

    session_state = {
        "session_id": session_id,
        "config": {
            "company": company,
            "level": level,
            "mode": mode,
            "domains": list(domain_scores_raw.keys()) if domain_scores_raw else [domain],
        },
        "status": "complete",
        "started_at": started - 300,  # assume 5 min ago
        "ended_at": started,
        "domain_scores": domain_scores_raw,
        "max_depth_reached": max_depth,
        "behavioral_scores": {},
    }

    generator = ReportGenerator()
    return await generator.generate_report(
        session_state=session_state,
        exchanges=exchanges,
    )
