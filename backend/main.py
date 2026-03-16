"""
CyberLoop — FastAPI Backend

WebSocket endpoint bridges browser audio to Gemini Live API for
real-time voice-based mock interviews.

Endpoints:
  POST /sessions         — Create a new interview session
  GET  /sessions/{id}    — Get session state
  WS   /session/{id}     — WebSocket for live audio streaming
  GET  /health           — Health check
  GET  /                 — API info
"""

import logging
import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent.interviewer import CyberLoopAgent
from agent.adk_interviewer import run_adk_session
from agent.session import (
    InterviewState,
    SessionConfig,
    SessionManager,
    SessionStatus,
)
from agent.tools import load_question_trees

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("cyberloop")

# Allowed CORS origins (browser frontends)
CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
    "https://cyberloop.dev",
    "https://www.cyberloop.dev",
    "https://cyberloop-*.run.app",
]

# Additional origins from environment
extra_origins = os.environ.get("CORS_ORIGINS", "")
if extra_origins:
    CORS_ORIGINS.extend(o.strip() for o in extra_origins.split(",") if o.strip())

# ---------------------------------------------------------------------------
# Lifespan (startup/shutdown)
# ---------------------------------------------------------------------------

session_manager: SessionManager | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup, clean up on shutdown."""
    global session_manager

    logger.info("Starting CyberLoop backend...")

    # Load question trees from data directory
    data_dir = os.path.join(os.path.dirname(__file__), "data", "question_trees")
    load_question_trees(data_dir)
    logger.info("Question trees loaded from %s", data_dir)

    # Initialize session manager (Firestore or in-memory)
    emulator = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
    use_firestore = os.environ.get("USE_FIRESTORE", "").lower() == "true"
    if use_firestore or (emulator and emulator != "localhost:9999"):
        try:
            session_manager = SessionManager()
            logger.info("Firestore session manager initialized")
        except Exception as e:
            logger.warning(
                "Firestore unavailable, using in-memory sessions: %s", e
            )
            session_manager = InMemorySessionManager()
    else:
        session_manager = InMemorySessionManager()

    yield

    logger.info("Shutting down CyberLoop backend.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CyberLoop API",
    description=(
        "AI voice agent that conducts real-company-style mock interviews "
        "for cybersecurity roles. Powered by Gemini Live API."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    """Request body for creating a new interview session."""
    company: str = Field(
        default="generic",
        description="Company interview style: amazon, spacex, tiktok, generic",
    )
    level: str = Field(
        default="senior",
        description="Seniority level: junior, mid, senior, staff",
    )
    mode: str = Field(
        default="technical",
        description="Interview mode: technical, behavioral",
    )
    domains: list[str] = Field(
        default=["incident_response"],
        description=(
            "Domains to cover: incident_response, detection_engineering, "
            "digital_forensics, soc_operations, threat_intelligence"
        ),
    )
    demo: bool = Field(
        default=False,
        description="Demo mode: use fixed session seed for reproducible question order",
    )


class SessionResponse(BaseModel):
    """Response for session creation and retrieval."""
    session_id: str
    status: str
    config: dict
    websocket_url: str = ""
    started_at: float = 0.0
    ended_at: float = 0.0
    exchanges_count: int = 0
    domain_scores: dict = {}
    max_depth_reached: dict = {}


class ReportResponse(BaseModel):
    """Summarized report card for a completed session."""
    session_id: str
    status: str
    duration_minutes: float = 0.0
    domain_summaries: dict = {}
    behavioral_scores: dict = {}
    total_exchanges: int = 0
    max_depth_reached: dict = {}


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """API info / SPA root. Serves frontend if static build is present."""
    import pathlib as _pl
    _sd = _pl.Path(__file__).parent / "static" / "index.html"
    if _sd.is_file():
        from fastapi.responses import FileResponse as _FR
        return _FR(str(_sd))
    return {
        "name": "CyberLoop API",
        "version": "0.1.0",
        "description": "AI mock interview agent for cybersecurity roles",
        "endpoints": {
            "POST /sessions": "Create a new interview session",
            "GET /sessions/{session_id}": "Get session state",
            "WS /session/{session_id}": "WebSocket for live interview",
            "GET /health": "Health check",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for Cloud Run."""
    return {
        "status": "healthy",
        "service": "cyberloop-api",
        "gemini_configured": bool(os.environ.get("GEMINI_API_KEY")),
        "firestore_available": session_manager is not None
        and not isinstance(session_manager, InMemorySessionManager),
    }


# ---------------------------------------------------------------------------
# Code Execution
# ---------------------------------------------------------------------------

class RunCodeRequest(BaseModel):
    code: str

@app.post("/run-code")
async def run_code(request: RunCodeRequest):
    """Execute Python code in a sandboxed subprocess and return output."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(request.code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "Execution timed out (10 second limit)",
            "exit_code": -1,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": -1,
        }
    finally:
        os.unlink(tmp_path)


@app.post("/sessions", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    """
    Create a new interview session.

    Accepts configuration for company style, seniority level,
    interview mode, and domains to cover. Returns a session ID
    and WebSocket URL for the live interview.
    """
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    # Validate inputs
    valid_companies = {"amazon", "spacex", "tiktok", "generic"}
    valid_levels = {"junior", "mid", "senior", "staff"}
    valid_modes = {"technical", "behavioral", "coding"}
    valid_domains = {
        "incident_response",
        "detection_engineering",
        "digital_forensics",
        "soc_operations",
        "threat_intelligence",
    }

    company = request.company.lower()
    if company not in valid_companies:
        company = "generic"

    level = request.level.lower()
    if level not in valid_levels:
        level = "senior"

    mode = request.mode.lower()
    if mode not in valid_modes:
        mode = "technical"

    domains = [d for d in request.domains if d in valid_domains]
    if mode == "coding":
        # Coding questions only exist in detection_engineering
        domains = ["detection_engineering"]
    elif not domains:
        domains = ["incident_response"]

    config = SessionConfig(
        company=company,
        level=level,
        mode=mode,
        domains=domains,
    )

    state = session_manager.create_session(config)

    # Demo mode: override session_id with a fixed seed for reproducible question order
    if request.demo:
        old_id = state.session_id
        state.session_id = "demo-" + mode + "-" + "-".join(domains)
        # Re-map in session manager (remove old UUID key, add new demo key)
        if hasattr(session_manager, '_sessions'):
            session_manager._sessions.pop(old_id, None)
            session_manager._sessions[state.session_id] = state
        logger.info("DEMO MODE: session_id overridden to %s", state.session_id)

    logger.info(
        "Session created: %s (company=%s, level=%s, mode=%s, domains=%s)",
        state.session_id, company, level, mode, domains,
    )

    return SessionResponse(
        session_id=state.session_id,
        status=state.status.value,
        config={
            "company": company,
            "level": level,
            "mode": mode,
            "domains": domains,
        },
        websocket_url=f"/session/{state.session_id}",
        started_at=state.started_at,
    )


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get the current state of an interview session."""
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    state = session_manager.get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionResponse(
        session_id=state.session_id,
        status=state.status.value,
        config={
            "company": state.config.company,
            "level": state.config.level,
            "mode": state.config.mode,
            "domains": state.config.domains,
        },
        websocket_url=f"/session/{state.session_id}",
        started_at=state.started_at,
        ended_at=state.ended_at,
        exchanges_count=len(state.exchanges),
        domain_scores=state.domain_scores,
        max_depth_reached=state.max_depth_reached,
    )


@app.get("/report/{session_id}")
async def get_report_card(session_id: str):
    """
    Get the full report card for a completed session.

    Returns the rich format the frontend ReportCard page expects:
    { session_id, overall_level, technical_scores, behavioral_scores,
      strengths, improvements, study_recommendations, transcript,
      interview_duration, company, mode }

    Uses LLM-based semantic evaluation to check if 'missed' concepts
    were actually covered using different terminology.
    """
    from agent.tools import semantic_evaluate_concepts

    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    state = session_manager.get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build full transcript for semantic evaluation - prefer live transcript
    if state.live_transcript:
        full_transcript = [{"speaker": t["speaker"], "text": t["text"]} for t in state.live_transcript]
    else:
        full_transcript = []
        for ex in state.exchanges:
            if ex.question:
                full_transcript.append({"speaker": "agent", "text": ex.question})
            if ex.response:
                full_transcript.append({"speaker": "candidate", "text": ex.response})

    # Build technical_scores from domain_scores + exchange assessments
    technical_scores = []
    for domain, scores in state.domain_scores.items():
        avg = sum(scores) / len(scores) if scores else 0
        level = state.get_level_label(avg)

        # Gather assessments and areas_to_probe from exchanges
        domain_assessments = []
        all_areas = []
        all_strengths = []
        for ex in state.exchanges:
            if ex.assessment:
                domain_assessments.append(ex.assessment)
            all_areas.extend(ex.areas_to_probe)
            all_strengths.extend(ex.key_strengths)

        display_domain = domain
        if state.config.mode == "behavioral" and domain == "behavioral_bank":
            display_domain = "Behavioral Assessment"

        # Missed concepts populated by LLM analysis below (not static keyword matching)
        technical_scores.append({
            "domain": display_domain,
            "score": round(avg, 1),
            "level": level,
            "feedback": " ".join(domain_assessments[:3]) if domain_assessments else "",
            "missed_concepts": [],  # Filled by Gemini analysis
            "depth_reached": state.max_depth_reached.get(domain, 1),
        })

    # Build transcript list from exchanges
    # Use the real-time live transcript if available, otherwise fall back to exchange summaries
    if state.live_transcript:
        transcript = [{"speaker": t["speaker"], "text": t["text"]} for t in state.live_transcript]
    else:
        transcript = []
        for ex in state.exchanges:
            if ex.question:
                transcript.append({"speaker": "agent", "text": ex.question})
            if ex.response:
                transcript.append({"speaker": "candidate", "text": ex.response})

    # Compute duration
    interview_duration = 0
    if state.started_at and state.ended_at:
        interview_duration = int(state.ended_at - state.started_at)

    # Behavioral scores - populated from LLM analysis below if behavioral mode
    behavioral_scores = None
    if state.behavioral_scores:
        behavioral_scores = {
            "star_structure": state.behavioral_scores.get("star_structure_score", 0),
            "i_vs_we_ratio": state.behavioral_scores.get("i_vs_we_ratio", 0.5),
            "depth_under_pressure": state.behavioral_scores.get("depth_under_pressure", 0),
            "story_bank": state.behavioral_scores.get("feedback", ""),
        }

    # Overall score + level
    all_scores = [s["score"] for s in technical_scores]
    overall_score = sum(all_scores) / len(all_scores) if all_scores else 0
    overall_level = state.get_level_label(overall_score)

    # Generate deep analysis via LLM second pass
    strengths = []
    improvements = []
    study_recommendations = []
    per_question_feedback = []

    if full_transcript:
        try:
            from google import genai
            from agent.prompts import _load_calibration_data
            import os
            client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"))
            mode_label = "behavioral" if state.config.mode == "behavioral" else "technical cybersecurity"

            # Load calibration data for the domain
            calibration_context = ""
            for domain in (state.config.domains or []):
                cal_data = _load_calibration_data(domain)
                if cal_data:
                    calibration_context += cal_data + "\n\n"

            # Build transcript text for analysis (prefer live transcript over exchange summaries)
            exchange_details = []
            if state.live_transcript:
                for t in state.live_transcript:
                    speaker = "INTERVIEWER" if t["speaker"] == "agent" else "CANDIDATE"
                    exchange_details.append(f"{speaker}: {t['text']}")
            else:
                for i, ex in enumerate(state.exchanges):
                    sub_scores = ""
                    if ex.technical_depth or ex.specificity or ex.communication:
                        sub_scores = f" [depth:{ex.technical_depth}/5, specificity:{ex.specificity}/5, communication:{ex.communication}/5]"
                    exchange_details.append(
                        f"Q{i+1}: \"{ex.question[:100]}...\"\n"
                        f"  Score: {ex.score}/10{sub_scores}\n"
                        f"  Candidate said: \"{ex.response[:200]}...\""
                    )

            feedback_prompt = (
                f"You are an expert cybersecurity interview coach doing a DEEP analysis "
                f"of a completed {mode_label} interview.\n\n"
            )

            if state.config.mode == "behavioral":
                feedback_prompt += (
                    f"BEHAVIORAL INTERVIEW SCORING:\n"
                    f"Evaluate using the STAR framework:\n"
                    f"- Situation (0-2): Was it specific? Named project, date, team?\n"
                    f"- Task (0-2): What were THEY responsible for?\n"
                    f"- Action (0-3): What did THEY do? 'I' not 'we'?\n"
                    f"- Result (0-3): Quantified outcome? Business impact?\n"
                    f"Score star_structure_score (1-10 average across stories).\n"
                    f"Calculate i_vs_we_ratio: count 'I/my/me' vs 'we/our/us' (0.0-1.0, higher = more I).\n"
                    f"Score depth_under_pressure (1-10): Did answers improve or degrade under probing?\n"
                    f"Provide feedback on STAR completeness and areas to improve.\n\n"
                )
            elif state.config.mode == "coding":
                feedback_prompt += (
                    f"CODING INTERVIEW SCORING:\n"
                    f"Evaluate the candidate's coding ability AND security analysis:\n"
                    f"1. APPROACH (30%): Did they plan before coding? Break down the problem?\n"
                    f"2. CODE QUALITY (25%): Correct syntax, clean structure, appropriate data structures?\n"
                    f"3. SECURITY INSIGHT (25%): Did they identify the suspicious IP (10.0.0.33)? "
                    f"Did they explain the attack chain (brute force → admin access → exfiltration → "
                    f"persistence → log clearing)? Did they connect the dots?\n"
                    f"4. COMMUNICATION (10%): Did they think out loud? Explain reasoning?\n"
                    f"5. SPEED (10%): Reasonable pace?\n"
                    f"The candidate's code output (if they ran it) is in the transcript.\n"
                    f"Score each dimension 1-10 in your assessment.\n\n"
                )
            else:
                feedback_prompt += (
                    f"TECHNICAL INTERVIEW SCORING:\n"
                    f"Evaluate depth of cybersecurity knowledge:\n"
                    f"1. TECHNICAL DEPTH (40%): Did they explain WHY, not just WHAT?\n"
                    f"2. SPECIFICITY (30%): Concrete examples, tool names, numbers, timelines?\n"
                    f"3. COMMUNICATION (20%): Clear, organized, concise?\n"
                    f"4. BREADTH (10%): Coverage across the domain?\n"
                    f"Score each dimension 1-10 in your assessment.\n\n"
                )

            if calibration_context:
                feedback_prompt += (
                    f"LEVEL CALIBRATION (use this to determine the candidate's exact level):\n"
                    f"{calibration_context}\n\n"
                )

            if state.config.mode == "coding":
                feedback_prompt += (
                    f"IMPORTANT: This was a CODING interview. Score based on:\n"
                    f"1. Did the code work? (parsing logs, extracting IPs, counting, sorting)\n"
                    f"2. Did they identify 10.0.0.33 as suspicious?\n"
                    f"3. Did they explain the attack chain? (brute force → admin → exfil → persistence → log clearing)\n"
                    f"4. Code quality and approach\n"
                    f"Do NOT penalize for not answering follow-up detection engineering questions "
                    f"that went beyond the original coding challenge scope.\n\n"
                )

            feedback_prompt += (
                f"PER-QUESTION ANALYSIS:\n" + "\n\n".join(exchange_details) + "\n\n"
                f"FULL TRANSCRIPT:\n" +
                "\n".join(
                    f"{'Interviewer' if t['speaker'] == 'agent' else 'Candidate'}: {t['text']}"
                    for t in full_transcript
                ) +
                f"\n\n"
            )

            # Add body language observations if available (behavioral mode with webcam)
            if state.body_language_notes and state.config.mode == "behavioral":
                bl_summary = "\n".join(
                    f"  - [{n.get('confidence_level', 'neutral')}] {n.get('observation', '')} "
                    f"(signals: {', '.join(n.get('notable_signals', []))})"
                    for n in state.body_language_notes
                )
                feedback_prompt += (
                    f"BODY LANGUAGE OBSERVATIONS (from webcam during interview):\n"
                    f"{bl_summary}\n\n"
                    f"Include a 'body_language' section in your analysis based on these observations. "
                    f"Assess overall presence, confidence trajectory, and communication impact.\n\n"
                )

            feedback_prompt += (
                f"IMPORTANT: If any red_flags are detected, they MUST appear in the report. "
                f"Red flags override positive scoring - a candidate scoring 8/10 average but "
                f"showing a red flag (e.g., claims expertise but cannot describe basic workflow, "
                f"uses 'we' exclusively, gives contradictory answers) should have that prominently noted.\n\n"
                f"Provide a thorough analysis. Return ONLY valid JSON with this structure:\n"
                f"{{\n"
                f'  "overall_assessment": "2-3 sentence summary of candidate level and interview performance",\n'
                f'  "calibrated_level": "junior|mid|senior|staff based on calibration data above",\n'
                f'  "strengths": ["3 specific strengths with evidence from transcript"],\n'
                f'  "improvements": ["3 specific, actionable improvements with examples of what they SHOULD have said"],\n'
                f'  "study": ["3 specific study recommendations: topics, books, certs, or labs"],\n'
                f'  "patterns": ["2-3 cross-cutting patterns observed across multiple answers, e.g. always/never quantifies results, strong on theory weak on practice, uses we vs I"],\n'
                f'  "red_flags": ["any red flags detected, or empty array if none"],\n'
                f'  "missed_concepts": ["3-5 specific concepts, techniques, or topics the candidate SHOULD have mentioned but did not, based on the questions asked"],\n'
                f'  "next_level_gap": "What specifically separates this candidate from the NEXT level up, based on calibration data"'
                + (
                    f',\n  "behavioral_scores": {{\n'
                    f'    "star_structure_score": 0.0,\n'
                    f'    "i_vs_we_ratio": 0.0,\n'
                    f'    "depth_under_pressure": 0.0,\n'
                    f'    "feedback": "STAR assessment summary"\n'
                    f'  }}'
                    if state.config.mode == "behavioral"
                    else ""
                )
                + (
                    f',\n  "body_language": {{\n'
                    f'    "overall_presence": "confident|neutral|nervous",\n'
                    f'    "confidence_trajectory": "improving|stable|declining",\n'
                    f'    "observations": ["2-3 specific body language observations that impacted the interview"],\n'
                    f'    "impact_on_score": "How body language affected the overall communication assessment"\n'
                    f'  }}'
                    if state.body_language_notes and state.config.mode == "behavioral"
                    else ""
                )
                + f"\n}}"
            )

            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=feedback_prompt,
            )
            import json
            text = response.text.strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            feedback_data = json.loads(text)
            strengths = feedback_data.get("strengths", [])[:3]
            improvements = feedback_data.get("improvements", [])[:3]
            study_recommendations = feedback_data.get("study", [])[:3]

            # Store extra analysis fields for the frontend
            extra_analysis = {
                "overall_assessment": feedback_data.get("overall_assessment", ""),
                "calibrated_level": feedback_data.get("calibrated_level", ""),
                "patterns": feedback_data.get("patterns", []),
                "red_flags": feedback_data.get("red_flags", []),
                "next_level_gap": feedback_data.get("next_level_gap", ""),
            }
            # Only include body language for behavioral mode with webcam
            if feedback_data.get("body_language") and state.config.mode == "behavioral" and state.body_language_notes:
                extra_analysis["body_language"] = feedback_data["body_language"]
            # Extract behavioral scores from LLM analysis
            # Only extract behavioral scores for behavioral mode
            if feedback_data.get("behavioral_scores") and state.config.mode == "behavioral":
                bs = feedback_data["behavioral_scores"]
                behavioral_scores = {
                    "star_structure": bs.get("star_structure_score", 0),
                    "i_vs_we_ratio": bs.get("i_vs_we_ratio", 0.5),
                    "depth_under_pressure": bs.get("depth_under_pressure", 0),
                    "story_bank": bs.get("feedback", ""),
                }
                logger.info("Behavioral scores from LLM: star=%s, i_vs_we=%s, depth=%s",
                           behavioral_scores["star_structure"],
                           behavioral_scores["i_vs_we_ratio"],
                           behavioral_scores["depth_under_pressure"])
            # Populate missed_concepts from LLM analysis
            llm_missed = feedback_data.get("missed_concepts", [])
            if llm_missed and technical_scores:
                technical_scores[0]["missed_concepts"] = llm_missed[:5]

        except Exception as e:
            logger.warning("Failed to generate LLM feedback: %s", e)
            extra_analysis = {}
    else:
        extra_analysis = {}

    # Build per-question detail for the frontend
    per_question_detail = []
    for i, ex in enumerate(state.exchanges):
        per_question_detail.append({
            "question": ex.question,
            "response": ex.response,
            "score": ex.score,
            "technical_depth": ex.technical_depth,
            "specificity": ex.specificity,
            "communication": ex.communication,
            "assessment": ex.assessment,
            "key_strengths": ex.key_strengths,
            "areas_to_probe": ex.areas_to_probe,
            "depth_level": ex.depth_level,
        })

    # Compute score trajectory across the interview
    scores_sequence = [ex.score for ex in state.exchanges if ex.score is not None]
    trajectory = "stable"
    trajectory_detail = ""
    if len(scores_sequence) >= 2:
        mid = len(scores_sequence) // 2
        first_half_avg = sum(scores_sequence[:mid]) / mid
        second_half_avg = sum(scores_sequence[mid:]) / len(scores_sequence[mid:])
        diff = second_half_avg - first_half_avg
        if diff > 1.0:
            trajectory = "improving"
            trajectory_detail = (
                f"First half avg: {first_half_avg:.1f}, Second half avg: {second_half_avg:.1f} "
                f"- candidate warmed up significantly"
            )
        elif diff < -1.0:
            trajectory = "declining"
            trajectory_detail = (
                f"First half avg: {first_half_avg:.1f}, Second half avg: {second_half_avg:.1f} "
                f"- performance dropped as questions got harder"
            )
        else:
            trajectory = "stable"
            trajectory_detail = (
                f"First half avg: {first_half_avg:.1f}, Second half avg: {second_half_avg:.1f} "
                f"- consistent performance throughout"
            )

    # Use calibrated level only if it's consistent with the domain score
    # (prevents LLM from downgrading due to off-topic follow-up questions)
    if extra_analysis.get("calibrated_level"):
        calibrated = extra_analysis["calibrated_level"].capitalize()
        level_order = {"Junior": 1, "Mid": 2, "Mid-Level": 2, "Senior": 3, "Staff": 4}
        cal_rank = level_order.get(calibrated, 0)
        score_rank = level_order.get(overall_level, 0)
        # Only override if within 1 level of the score-based level
        if abs(cal_rank - score_rank) <= 1:
            overall_level = calibrated
        else:
            logger.info("Ignoring LLM calibrated_level '%s' (rank %d) - too far from score-based '%s' (rank %d)",
                       calibrated, cal_rank, overall_level, score_rank)

    return {
        "session_id": session_id,
        "overall_level": overall_level,
        "overall_assessment": extra_analysis.get("overall_assessment", ""),
        "technical_scores": technical_scores,
        "behavioral_scores": behavioral_scores,
        "strengths": strengths,
        "improvements": improvements,
        "study_recommendations": study_recommendations,
        "patterns": extra_analysis.get("patterns", []),
        "red_flags": extra_analysis.get("red_flags", []),
        "next_level_gap": extra_analysis.get("next_level_gap", ""),
        "trajectory": trajectory,
        "trajectory_detail": trajectory_detail,
        "per_question_detail": per_question_detail,
        "transcript": transcript,
        "interview_duration": interview_duration,
        "company": state.config.company,
        "mode": state.config.mode,
        "body_language": extra_analysis.get("body_language", None),
    }


@app.get("/sessions/{session_id}/report", response_model=ReportResponse)
async def get_report(session_id: str):
    """Get the report card for a completed interview session."""
    if session_manager is None:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    state = session_manager.get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    if state.status != SessionStatus.COMPLETE:
        raise HTTPException(
            status_code=400,
            detail=f"Session is {state.status.value}, not complete",
        )

    # Calculate summaries
    domain_summaries = {}
    for domain, scores in state.domain_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            domain_summaries[domain] = {
                "average_score": round(avg, 1),
                "level_label": state.get_level_label(avg),
                "max_depth": state.max_depth_reached.get(domain, 1),
                "questions_answered": len(scores),
            }

    duration = 0.0
    if state.started_at and state.ended_at:
        duration = round((state.ended_at - state.started_at) / 60, 1)

    return ReportResponse(
        session_id=state.session_id,
        status=state.status.value,
        duration_minutes=duration,
        domain_summaries=domain_summaries,
        behavioral_scores=state.behavioral_scores,
        total_exchanges=len(state.exchanges),
        max_depth_reached=state.max_depth_reached,
    )


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------

@app.websocket("/session/{session_id}")
async def websocket_interview(
    websocket: WebSocket,
    session_id: str,
    engine: str = "adk",
):
    """
    WebSocket endpoint for live interview audio streaming.

    Query params:
      engine=adk   (default) Use ADK run_live() pipeline
      engine=legacy         Use original CyberLoopAgent

    Protocol:
      Client -> Server:
        {"type": "audio", "data": "<base64 PCM16>"}
        {"type": "end_of_turn"}
        {"type": "interrupt", "interrupt_type": "skip|redo|clarify"}
        {"type": "end_session"}

      Server -> Client:
        {"type": "session_started", "session_id": "...", ...}
        {"type": "audio", "data": "<base64 PCM16>"}
        {"type": "transcript", "speaker": "interviewer", "text": "..."}
        {"type": "score_update", "score": 7, "level": "Senior", ...}
        {"type": "tool_call", "function": "...", "result": {...}}
        {"type": "turn_complete"}
        {"type": "report_ready", "session_id": "...", "summary": {...}}
        {"type": "session_ended", "summary": {...}}
        {"type": "error", "message": "..."}
    """
    await websocket.accept()

    if session_manager is None:
        await websocket.send_json({"type": "error", "message": "Service unavailable"})
        await websocket.close(code=1013)
        return

    # Load session state
    state = session_manager.get_session(session_id)
    if state is None:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close(code=4004)
        return

    if state.status == SessionStatus.COMPLETE:
        await websocket.send_json({
            "type": "error",
            "message": "Session already completed",
        })
        await websocket.close(code=4010)
        return

    # Create and run the interview agent
    try:
        if engine == "adk":
            logger.info("Session %s using ADK engine", session_id)
            await run_adk_session(
                websocket=websocket,
                state=state,
                session_manager=session_manager,
            )
        else:
            logger.info("Session %s using legacy engine", session_id)
            agent = CyberLoopAgent(
                state=state,
                session_manager=session_manager,
            )
            await agent.run_session(websocket)
    except Exception as e:
        logger.error("Agent error for session %s: %s", session_id, e, exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"Interview agent error: {str(e)}",
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/interview-adk/{session_id}")
async def websocket_interview_adk(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for ADK-powered live interview streaming.

    Same protocol as /session/{session_id} but uses the ADK Runner
    with run_live() instead of manual Gemini session management.
    """
    await websocket.accept()

    if session_manager is None:
        await websocket.send_json({"type": "error", "message": "Service unavailable"})
        await websocket.close(code=1013)
        return

    state = session_manager.get_session(session_id)
    if state is None:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close(code=4004)
        return

    if state.status == SessionStatus.COMPLETE:
        await websocket.send_json({
            "type": "error",
            "message": "Session already completed",
        })
        await websocket.close(code=4010)
        return

    try:
        await run_adk_session(websocket, state, session_manager)
    except Exception as e:
        logger.error("ADK agent error for session %s: %s", session_id, e, exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": f"ADK interview agent error: {str(e)}",
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# In-Memory Session Manager (fallback when Firestore is unavailable)
# ---------------------------------------------------------------------------

class InMemorySessionManager:
    """
    Fallback session manager for local development when Firestore
    is not configured. Stores sessions in memory (lost on restart).
    """

    def __init__(self):
        self._sessions: dict[str, InterviewState] = {}
        logger.info("Using in-memory session manager (no Firestore)")

    def create_session(self, config: SessionConfig) -> InterviewState:
        import time
        state = InterviewState(config=config)
        state.status = SessionStatus.SETUP
        state.current_domain = config.domains[0] if config.domains else ""
        state.started_at = time.time()
        self._sessions[state.session_id] = state
        return state

    def get_session(self, session_id: str) -> InterviewState | None:
        return self._sessions.get(session_id)

    def update_session(self, state: InterviewState) -> None:
        self._sessions[state.session_id] = state

    def activate_session(self, state: InterviewState) -> None:
        state.status = SessionStatus.ACTIVE
        self.update_session(state)

    def complete_session(self, state: InterviewState) -> None:
        import time
        state.status = SessionStatus.COMPLETE
        state.ended_at = time.time()
        self.update_session(state)

    def save_exchange(self, session_id: str, exchange) -> None:
        pass  # Exchanges stored in state.exchanges for in-memory mode


# ---------------------------------------------------------------------------
# Static Frontend Serving (production: serves React build from /static)
# ---------------------------------------------------------------------------

import pathlib
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_static_dir = pathlib.Path(__file__).parent / "static"
if _static_dir.is_dir():
    # Serve JS/CSS/assets at /assets
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    # Serve other static files (vite.svg, worklet processors, etc.)
    @app.get("/vite.svg")
    async def vite_svg():
        return FileResponse(str(_static_dir / "vite.svg"))

    @app.get("/pcm-player-processor.js")
    async def pcm_player():
        return FileResponse(
            str(_static_dir / "pcm-player-processor.js"),
            media_type="application/javascript",
        )

    @app.get("/pcm-recorder-processor.js")
    async def pcm_recorder():
        return FileResponse(
            str(_static_dir / "pcm-recorder-processor.js"),
            media_type="application/javascript",
        )

    # SPA catch-all: serve index.html for any unmatched route
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Don't catch API paths (they're already registered above)
        file_path = _static_dir / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_static_dir / "index.html"))

    logger.info("Static frontend mounted from %s", _static_dir)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )
