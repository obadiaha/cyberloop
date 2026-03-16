"""
ADK tool definitions for the CyberLoop agent.

These tools are called by the Gemini model during the interview to:
- Fetch the next question from the question tree
- Advance the depth ladder when the candidate performs well
- Score candidate responses against the rubric
- End the interview and trigger report generation

The tools operate on a shared InterviewState instance and communicate
with the session manager for persistence.
"""

import json
import os
import logging
from typing import Any

from google import genai
from google.genai import types as genai_types

from agent.session import (
    Exchange,
    InterviewState,
    SessionManager,
    SessionStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Question tree cache (loaded from data/ directory or Cloud Storage)
# ---------------------------------------------------------------------------

_question_trees: dict[str, Any] = {}


def load_question_trees(data_dir: str | None = None) -> None:
    """
    Load question trees from the data directory into memory.
    Called once at startup.
    """
    global _question_trees
    if data_dir is None:
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "data", "question_trees"
        )

    if not os.path.isdir(data_dir):
        logger.warning("Question trees directory not found: %s", data_dir)
        return

    for filename in os.listdir(data_dir):
        if filename.endswith(".json"):
            domain = filename.replace(".json", "")
            filepath = os.path.join(data_dir, filename)
            try:
                with open(filepath, "r") as f:
                    _question_trees[domain] = json.load(f)
                logger.info("Loaded question tree: %s", domain)
            except (json.JSONDecodeError, OSError) as e:
                logger.error("Failed to load %s: %s", filepath, e)


def get_question_tree(domain: str) -> dict[str, Any] | None:
    """Get the question tree for a domain."""
    return _question_trees.get(domain)


# ---------------------------------------------------------------------------
# Tool: get_next_question
# ---------------------------------------------------------------------------

def get_next_question(
    state: InterviewState,
    direction: str = "next",
) -> dict[str, Any]:
    """
    Fetch the next question from the question tree based on current state.

    This tool is called by the Gemini agent to get the appropriate question.
    It considers: current domain, depth level, question index, and whether
    we should probe deeper or move to a new root question.

    Args:
        state: Current interview state
        direction: "next" for next root question, "deeper" for depth probe,
                   "same" to rephrase current level

    Returns:
        Dict with question text, question_id, depth_level, and expected_concepts
    """
    # For behavioral mode, use the behavioral_bank tree
    if state.config.mode == "behavioral":
        domain = "behavioral_bank"
    else:
        domain = state.current_domain or (
            state.config.domains[0] if state.config.domains else "incident_response"
        )
    tree = get_question_tree(domain)

    # If no tree loaded, return a fallback generic question
    if not tree:
        return _fallback_question(domain, state.current_depth_level, state.question_index)

    # Cache flattened/shuffled questions on state to avoid re-shuffling each call
    cache_key = f"_cached_questions_{domain}"
    if hasattr(state, cache_key) and getattr(state, cache_key):
        root_questions = getattr(state, cache_key)
    else:
        import random
        rng = random.Random(state.session_id)

        # Behavioral trees use "themes" with nested questions; flatten them
        root_questions = list(tree.get("root_questions", []))
        if not root_questions and "themes" in tree:
            root_questions = []
            for theme in tree["themes"]:
                for q in theme.get("questions", []):
                    depth_probes = []
                    star_probes = q.get("star_probes", {})
                    for phase in ["situation", "task", "action", "result"]:
                        probes = star_probes.get(phase, [])
                        if probes:
                            depth_probes.append({
                                "level": len(depth_probes) + 1,
                                "text": probes[0],
                                "expected_concepts": [f"star_{phase}"],
                            })
                    for dp in q.get("depth_probes", []):
                        depth_probes.append({
                            "level": len(depth_probes) + 1,
                            "text": dp,
                            "expected_concepts": ["depth_of_experience"],
                        })
                    root_questions.append({
                        "id": q.get("id", ""),
                        "text": q.get("text", ""),
                        "expected_concepts": q.get("red_flags", []),
                        "depth_probes": depth_probes,
                        "theme": theme.get("display_name", ""),
                    })

        # In coding mode, show only the IP extraction question (de_007) for demo
        if state.config.mode == "coding":
            demo_q = [q for q in root_questions if q.get("id") == "de_007"]
            if demo_q:
                root_questions = demo_q
                logger.info("Coding mode: using de_007 (IP extraction) for demo")
            else:
                coding_questions = [q for q in root_questions if q.get("category") == "hands_on_coding"]
                if coding_questions:
                    root_questions = coding_questions
                    logger.info("Coding mode: filtered to %d hands-on questions", len(root_questions))

        # Shuffle for variety, seeded by session for consistency
        if state.config.mode == "coding":
            pass  # Demo mode: fixed order, no shuffle
        else:
            rng.shuffle(root_questions)
        logger.info("Shuffled %d questions for %s (seed=%s). First 3: %s",
                     len(root_questions), domain, state.session_id[:8],
                     [q.get("id", "?") for q in root_questions[:3]])
        setattr(state, cache_key, root_questions)

    if not root_questions:
        return _fallback_question(domain, state.current_depth_level, state.question_index)

    if direction == "deeper":
        # Try to get the depth probe at the current level
        return _get_depth_probe(root_questions, state)
    elif direction == "same":
        # Rephrase at the same level
        return _get_current_question(root_questions, state)
    else:
        # Move to next root question
        return _get_next_root_question(root_questions, state)


def _get_next_root_question(
    root_questions: list[dict], state: InterviewState
) -> dict[str, Any]:
    """Get the next root question in the tree."""
    idx = state.question_index
    if idx >= len(root_questions):
        # Exhausted all questions in this domain
        return {
            "question": "",
            "question_id": "",
            "depth_level": 1,
            "expected_concepts": [],
            "exhausted": True,
            "message": f"All questions covered for {state.current_domain}",
        }

    q = root_questions[idx]
    state.question_index = idx + 1
    state.current_depth_level = 1
    state.consecutive_shallow = 0
    state.current_question = q.get("text", "")
    state.current_question_id = q.get("id", f"q_{idx}")

    result = {
        "question": q["text"],
        "question_id": q.get("id", f"q_{idx}"),
        "depth_level": 1,
        "expected_concepts": q.get("expected_concepts", []),
        "red_flags": q.get("red_flags", []),
        "exhausted": False,
        "scoring_hint": (
            "Use expected_concepts as a REFERENCE for what a strong answer covers. "
            "Use red_flags to identify weak patterns. But score holistically, "
            "not by keyword counting."
        ),
    }

    # Include scoring guidance and strong answer markers if available
    if q.get("scoring_guidance"):
        result["scoring_guidance"] = q["scoring_guidance"]
    if q.get("strong_answer_markers"):
        result["strong_answer_markers"] = q["strong_answer_markers"]
    if q.get("challenge_data"):
        result["challenge_data"] = q["challenge_data"]

    return result


def _get_depth_probe(
    root_questions: list[dict], state: InterviewState
) -> dict[str, Any]:
    """Get the next unanswered depth probe, skipping ones whose concepts are already covered."""
    idx = max(0, state.question_index - 1)  # Current root question
    if idx >= len(root_questions):
        return _get_next_root_question(root_questions, state)

    q = root_questions[idx]
    probes = q.get("depth_probes", [])

    # Track which probes have been asked
    asked_probes = getattr(state, "_asked_probe_indices", set())

    # Get all candidate speech so far for concept matching
    candidate_text = getattr(state, "_last_candidate_text", "").lower()
    # Also include all exchange responses
    for ex in state.exchanges:
        if ex.response:
            candidate_text += " " + ex.response.lower()

    # Find the next probe that hasn't been asked AND whose concepts aren't already covered
    for i, probe in enumerate(probes):
        if i in asked_probes:
            continue

        expected = probe.get("expected_concepts", [])
        if expected and candidate_text:
            # Check how many concepts are already covered
            covered = 0
            for concept in expected:
                # Check for the concept or common synonyms in candidate speech
                concept_lower = concept.lower().replace("_", " ")
                if concept_lower in candidate_text or any(
                    word in candidate_text for word in concept_lower.split()
                ):
                    covered += 1
            # If most concepts already covered, skip this probe
            if covered > 0 and covered >= len(expected) * 0.5:
                logger.info("Skipping probe %d (%s) - %d/%d concepts already covered",
                           i, probe.get("text", "")[:40], covered, len(expected))
                asked_probes.add(i)
                continue

        # Found a probe to ask
        asked_probes.add(i)
        state._asked_probe_indices = asked_probes
        probe_text = probe.get("question") or probe.get("text", "")
        probe_level = probe.get("level", state.current_depth_level)
        state.current_question = probe_text
        state.current_question_id = f"{q.get('id', 'q')}_probe{i}"
        logger.info("Selected probe %d (level %d): %s", i, probe_level, probe_text[:60])
        return {
            "question": probe_text,
            "question_id": state.current_question_id,
            "depth_level": probe_level,
            "expected_concepts": expected,
            "red_flags": probe.get("red_flags", []),
            "exhausted": False,
            "scoring_hint": (
                "Paraphrase this question naturally based on the conversation. "
                "Ask ONE question only. Do NOT add extra questions."
            ),
        }

    # All probes exhausted or covered
    return _get_next_root_question(root_questions, state)


def _get_current_question(
    root_questions: list[dict], state: InterviewState
) -> dict[str, Any]:
    """Return the current question (for rephrasing)."""
    return {
        "question": state.current_question,
        "question_id": state.current_question_id,
        "depth_level": state.current_depth_level,
        "expected_concepts": [],
        "exhausted": False,
    }


def _fallback_question(domain: str, depth_level: int, question_index: int) -> dict[str, Any]:
    """Generate a fallback question when no tree is available."""
    fallback_questions = {
        "incident_response": [
            "Walk me through how you would handle a suspected ransomware incident from initial detection to containment.",
            "Tell me about a time you led or participated in an incident response. What was your role and what was the outcome?",
            "How would you set up an incident response program from scratch for a mid-size company?",
            "Describe your approach to post-incident review. What do you focus on?",
            "A critical server is showing signs of compromise but hasn't been confirmed. What's your first 30 minutes?",
        ],
        "detection_engineering": [
            "Walk me through how you'd build a detection for credential dumping.",
            "How do you handle false positives at scale in a detection pipeline?",
            "Describe your approach to mapping detection coverage to MITRE ATT&CK.",
            "How would you architect a detection-as-code pipeline?",
            "A new zero-day is announced. Walk me through your detection response.",
        ],
        "soc_operations": [
            "How would you triage a high-severity alert that fires at 3 AM?",
            "Describe how you'd measure and improve SOC performance metrics.",
            "Walk me through your ideal SOC architecture and tier structure.",
            "How do you handle alert fatigue in a SOC team?",
            "Describe your approach to building and maintaining runbooks.",
        ],
        "digital_forensics": [
            "Walk me through acquiring forensic evidence from a compromised Windows endpoint.",
            "How do you approach memory forensics? What tools and techniques do you use?",
            "Describe your process for building a forensic timeline from multiple data sources.",
            "What's your approach to cloud forensics vs traditional on-prem forensics?",
            "How do you maintain chain of custody in a fast-moving incident?",
        ],
        "threat_intelligence": [
            "How do you distinguish between tactical, operational, and strategic threat intelligence?",
            "Walk me through how you'd build an intelligence-driven detection program.",
            "Describe your approach to threat actor profiling and tracking.",
            "How do you assess the reliability and credibility of intelligence sources?",
            "How would you structure intelligence sharing with external partners?",
        ],
    }

    domain_qs = fallback_questions.get(domain, fallback_questions["incident_response"])
    idx = question_index % len(domain_qs)

    return {
        "question": domain_qs[idx],
        "question_id": f"fallback_{domain}_{idx}",
        "depth_level": depth_level,
        "expected_concepts": [],
        "exhausted": idx >= len(domain_qs) - 1,
    }


# ---------------------------------------------------------------------------
# Tool: advance_depth_ladder
# ---------------------------------------------------------------------------

def advance_depth_ladder(state: InterviewState) -> dict[str, Any]:
    """
    Move to the next depth level in the interview ladder.

    Called when the candidate demonstrates sufficient understanding at
    the current level. Advances depth and returns the new level info.

    Args:
        state: Current interview state

    Returns:
        Dict with new depth level, previous level, and whether max depth reached
    """
    previous_level = state.current_depth_level
    new_level = state.advance_depth()
    max_level = 4  # Max depth in our ladder

    logger.info(
        "Depth ladder advanced: %d -> %d for session %s",
        previous_level, new_level, state.session_id
    )

    return {
        "previous_level": previous_level,
        "new_level": new_level,
        "max_depth_reached": new_level >= max_level,
        "level_labels": {
            1: "Foundational (Explain)",
            2: "Applied (Apply to scenario)",
            3: "Architectural (Design/tradeoffs)",
            4: "Principal (Challenge the premise)",
        },
        "current_label": {
            1: "Foundational",
            2: "Applied",
            3: "Architectural",
            4: "Principal",
        }.get(new_level, "Advanced"),
    }


# ---------------------------------------------------------------------------
# Tool: score_response
# ---------------------------------------------------------------------------

def score_response(
    state: InterviewState,
    question: str,
    response: str,
    score: int = 3,
    technical_depth: int = 3,
    specificity: int = 3,
    communication: int = 3,
    assessment: str = "",
    key_strengths: list[str] | None = None,
    areas_to_probe: list[str] | None = None,
    # Coding mode sub-scores
    approach: int = 0,
    code_quality: int = 0,
    security_insight: int = 0,
    speed: int = 0,
    # Legacy params (accepted but ignored for backwards compat)
    expected_concepts: list[str] | None = None,
    detected_concepts: list[str] | None = None,
) -> dict[str, Any]:
    """
    Record the model's evaluation of a candidate response.

    The interviewer model (Gemini) IS the scorer. It hears the full audio,
    understands context and nuance. This tool records its judgment.

    Args:
        state: Current interview state
        question: The question that was asked
        response: Summary of the candidate's response
        score: Overall score 1-10 (1-2=weak, 3-4=basic, 5-6=adequate, 7-8=strong, 9-10=exceptional)
        technical_depth: 1-10, how deep was their technical knowledge
        specificity: 1-10, did they give concrete examples with details
        communication: 1-10, was the answer clear and well-structured
        assessment: Brief qualitative assessment of the response
        key_strengths: What the candidate did well
        areas_to_probe: Topics worth digging deeper on

    Returns:
        Dict with recorded score and guidance for next action
    """
    if key_strengths is None:
        key_strengths = []
    if areas_to_probe is None:
        areas_to_probe = []

    # Clamp scores to valid range (1-10)
    score = max(1, min(10, score))
    technical_depth = max(1, min(10, technical_depth))
    specificity = max(1, min(10, specificity))
    communication = max(1, min(10, communication))

    depth = state.current_depth_level

    # Map 1-10 score to quality label
    quality_map = {
        1: "weak", 2: "weak",
        3: "basic", 4: "basic",
        5: "adequate", 6: "adequate",
        7: "strong", 8: "strong",
        9: "exceptional", 10: "exceptional",
    }
    quality = quality_map.get(score, "adequate")

    # Track stalls for low scores
    if score <= 4:
        state.record_shallow_response()
    else:
        state.reset_shallow_count()

    # Score is already on 1-10 scale, use directly
    score_10 = score

    # Depth bonus multiplier: deeper questions reward higher scores
    # Level 1 = no bonus, Level 2 = +5%, Level 3 = +10%, Level 4 = +15%
    depth_bonus = 1 + 0.05 * (depth - 1)
    score_10 = min(10, round(score_10 * depth_bonus))
    logger.info("Depth bonus applied: depth=%d, multiplier=%.2f, score_10=%d", depth, depth_bonus, score_10)

    # Sub-score composite divergence check
    # Use mode-appropriate weights
    if state.config.mode == "coding" and approach > 0:
        # Coding mode: approach 30%, code_quality 25%, security_insight 25%, communication 10%, speed 10%
        approach = max(1, min(10, approach))
        code_quality = max(1, min(10, code_quality))
        security_insight = max(1, min(10, security_insight))
        speed = max(1, min(10, speed))
        composite = round(
            0.30 * approach +
            0.25 * code_quality +
            0.25 * security_insight +
            0.10 * communication +
            0.10 * speed
        )
        logger.info(
            "Coding sub-scores: approach=%d, code_quality=%d, security_insight=%d, communication=%d, speed=%d → composite=%d",
            approach, code_quality, security_insight, communication, speed, composite
        )
    else:
        # Technical/behavioral mode: technical_depth 40%, specificity 30%, communication 20%, overall 10%
        composite = round(0.4 * technical_depth + 0.3 * specificity + 0.2 * communication + 0.1 * score_10)
    if abs(composite - score_10) >= 3:
        logger.warning("Sub-score divergence detected: composite=%d vs score=%d", composite, score_10)

    level_label = state.get_level_label(float(score_10))

    logger.info(
        "Score recorded: %d/10 (%s) | depth=%d | strengths=%s | probe=%s",
        score_10, quality, depth, key_strengths[:2], areas_to_probe[:1]
    )

    # Record the exchange
    exchange = Exchange(
        question=question,
        question_id=state.current_question_id,
        response=response,
        score=score_10,
        depth_level=depth,
        assessment=assessment,
        key_strengths=key_strengths,
        areas_to_probe=areas_to_probe,
        technical_depth=technical_depth,
        specificity=specificity,
        communication=communication,
        approach=approach,
        code_quality=code_quality,
        security_insight=security_insight,
        speed=speed,
    )
    state.add_exchange(exchange)

    return {
        "score": score,
        "score_10": score_10,
        "level_label": level_label,
        "quality": quality,
        "depth_level": depth,
        "should_advance": score >= 7 and depth < 4,
        "is_stall": quality == "weak" and state.consecutive_shallow >= 3,
        "exchange_id": exchange.exchange_id,
        "guidance": (
            f"Probe deeper on: {areas_to_probe[0]}" if areas_to_probe and score >= 5
            else "Move to next topic" if score <= 4
            else "Continue current line of questioning"
        ),
    }


def _get_concept_variants(concept: str) -> list[str]:
    """Get lowercase variations of a concept for matching."""
    base = concept.lower().replace("_", " ")
    variants = [base]

    # Add common aliases
    aliases: dict[str, list[str]] = {
        "lsass": ["lsass", "local security authority"],
        "mimikatz": ["mimikatz", "credential dumping tool"],
        "sysmon": ["sysmon", "system monitor"],
        "sigma": ["sigma", "sigma rules"],
        "yara": ["yara", "yara rules"],
        "mitre": ["mitre", "att&ck", "attack framework"],
        "nist": ["nist", "nist framework", "800-61"],
        "volatility": ["volatility", "memory analysis"],
        "wireshark": ["wireshark", "packet capture", "pcap"],
        "splunk": ["splunk", "siem"],
        "elk": ["elk", "elastic", "elasticsearch", "kibana"],
        "soar": ["soar", "orchestration", "automation and response"],
        "edr": ["edr", "endpoint detection", "crowdstrike", "carbon black", "sentinel one"],
        "mttd": ["mttd", "mean time to detect"],
        "mttr": ["mttr", "mean time to respond", "mean time to recover"],
    }

    for key, vals in aliases.items():
        if key in base or base in key:
            variants.extend(vals)

    return list(set(variants))


def _detect_depth_indicators(response: str) -> dict[str, bool]:
    """Detect qualitative depth indicators in a response."""
    indicators = {
        "challenges_premise": False,
        "discusses_tradeoffs": False,
        "uses_specific_examples": False,
        "mentions_scale": False,
        "quantifies_results": False,
    }

    # Challenge premise markers
    challenge_markers = [
        "i would push back",
        "i'd challenge",
        "the real question is",
        "actually, i think the premise",
        "instead of",
        "rather than approaching it that way",
        "the better question is",
    ]
    if any(m in response for m in challenge_markers):
        indicators["challenges_premise"] = True

    # Tradeoff markers
    tradeoff_markers = [
        "tradeoff",
        "trade-off",
        "on one hand",
        "the downside",
        "the risk is",
        "versus",
        "compared to",
        "at the cost of",
        "but the tradeoff",
        "pros and cons",
        "balanced against",
    ]
    if any(m in response for m in tradeoff_markers):
        indicators["discusses_tradeoffs"] = True

    # Specific examples
    example_markers = [
        "for example",
        "in my experience",
        "at my previous",
        "when i was at",
        "one time",
        "specifically",
        "in practice",
        "i've seen",
    ]
    if any(m in response for m in example_markers):
        indicators["uses_specific_examples"] = True

    # Scale mentions
    scale_markers = [
        "at scale",
        "millions",
        "thousands",
        "billions",
        "per second",
        "per day",
        "high volume",
        "enterprise",
        "across the org",
    ]
    if any(m in response for m in scale_markers):
        indicators["mentions_scale"] = True

    # Quantified results
    import re
    if re.search(r'\d+%|\d+ percent|\d+x|reduced by \d+|improved by \d+', response):
        indicators["quantifies_results"] = True

    return indicators


# ---------------------------------------------------------------------------
# Semantic concept evaluation (LLM-based, runs at report time)
# ---------------------------------------------------------------------------

async def semantic_evaluate_concepts(
    transcript: list[dict[str, str]],
    missed_concepts: list[str],
) -> dict[str, list[str]]:
    """
    Use Gemini Flash to semantically check if 'missed' concepts were
    actually covered in the full transcript using different wording.

    Args:
        transcript: List of {speaker, text} dicts (full conversation)
        missed_concepts: Concepts the keyword matcher flagged as missed

    Returns:
        Dict with 'actually_covered' and 'truly_missed' lists
    """
    if not missed_concepts:
        return {"actually_covered": [], "truly_missed": []}

    # Build transcript text
    transcript_text = "\n".join(
        f"{'INTERVIEWER' if t['speaker'] == 'agent' else 'CANDIDATE'}: {t['text']}"
        for t in transcript
    )

    prompt = f"""You are evaluating a cybersecurity interview transcript.

The scoring system flagged these concepts as NOT covered by the candidate:
{json.dumps(missed_concepts)}

Review the FULL transcript below and determine which concepts the candidate
actually DID cover, even if they used different terminology, synonyms, or
described the concept without using the exact term.

For example:
- "validate alert" is covered if candidate said "verify the alert", "confirm it's not a false positive", "check if the alert is legitimate", etc.
- "chain of custody" is covered if candidate said "evidence handling", "forensic preservation", "maintaining integrity of evidence", etc.
- "lateral movement" is covered if candidate said "moving between systems", "pivoting to other hosts", "spreading through the network", etc.

Transcript:
{transcript_text}

Respond with ONLY a JSON object (no markdown, no explanation):
{{"actually_covered": ["concept1", "concept2"], "truly_missed": ["concept3"]}}

Every concept from the input list must appear in exactly one of the two arrays."""

    try:
        client = genai.Client()
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=1024,
            ),
        )
        result_text = response.text.strip()
        # Strip markdown code fences if present
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1]
            if result_text.endswith("```"):
                result_text = result_text.rsplit("```", 1)[0]
        result = json.loads(result_text)
        logger.info(
            "Semantic eval: %d concepts re-evaluated. Recovered: %s",
            len(missed_concepts),
            result.get("actually_covered", []),
        )
        return result
    except Exception as e:
        logger.error("Semantic evaluation failed: %s", e)
        # Fall back to keyword results
        return {"actually_covered": [], "truly_missed": missed_concepts}


# ---------------------------------------------------------------------------
# Tool: end_interview
# ---------------------------------------------------------------------------

def end_interview(
    state: InterviewState,
    session_manager: SessionManager,
    reason: str = "complete",
) -> dict[str, Any]:
    """
    Wrap up the interview session and trigger report generation.

    Called when:
    - All planned questions have been covered
    - Time limit reached
    - Candidate requests to end
    - Agent determines sufficient data collected

    Args:
        state: Current interview state
        session_manager: For persisting final state
        reason: Why the interview ended

    Returns:
        Dict with session summary and report generation status
    """
    # Complete the session
    session_manager.complete_session(state)

    # Calculate summary scores
    domain_summaries = {}
    for domain, scores in state.domain_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            domain_summaries[domain] = {
                "average_score": round(avg, 1),
                "level_label": state.get_level_label(avg),
                "max_depth_reached": state.max_depth_reached.get(domain, 1),
                "questions_answered": len(scores),
            }

    total_exchanges = len(state.exchanges)
    duration_minutes = 0
    if state.started_at and state.ended_at:
        duration_minutes = round((state.ended_at - state.started_at) / 60, 1)

    summary = {
        "session_id": state.session_id,
        "status": "complete",
        "reason": reason,
        "duration_minutes": duration_minutes,
        "total_exchanges": total_exchanges,
        "domain_summaries": domain_summaries,
        "behavioral_scores": state.behavioral_scores,
        "report_status": "pending",
    }

    logger.info(
        "Interview ended for session %s. Reason: %s. Exchanges: %d",
        state.session_id, reason, total_exchanges
    )

    return summary


# ---------------------------------------------------------------------------
# Tool: evaluate_and_continue (merged score + advance + get_next)
# ---------------------------------------------------------------------------

def evaluate_and_continue(
    state: InterviewState,
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
    # Coding mode sub-scores
    approach: int = 0,
    code_quality: int = 0,
    security_insight: int = 0,
    speed: int = 0,
) -> dict[str, Any]:
    """
    Combined tool: score the response, auto-advance depth, and get the next question.

    This replaces the 3-step score_response -> advance_depth_ladder -> get_next_question
    chain with a single tool call, reducing Gemini Live API round trips from 3 to 1.

    Args:
        state: Current interview state
        question: The question that was asked
        response: Summary of the candidate's response
        score: Overall score 1-10
        technical_depth: 1-10
        specificity: 1-10
        communication: 1-10
        assessment: Brief qualitative assessment
        key_strengths: What the candidate did well
        areas_to_probe: Topics worth probing deeper
        next_direction: "next" for new topic, "deeper" for depth probe, "done" to end
        approach: Coding mode only, 1-10
        code_quality: Coding mode only, 1-10
        security_insight: Coding mode only, 1-10
        speed: Coding mode only, 1-10

    Returns:
        Dict with score result, depth advancement info, and next question
    """
    # 1. Record the score
    score_result = score_response(
        state, question, response,
        score=score,
        technical_depth=technical_depth,
        specificity=specificity,
        communication=communication,
        assessment=assessment,
        key_strengths=key_strengths,
        areas_to_probe=areas_to_probe,
        approach=approach,
        code_quality=code_quality,
        security_insight=security_insight,
        speed=speed,
    )

    # 2. Auto-advance depth if warranted
    depth_advanced = False
    if score_result["should_advance"]:
        advance_depth_ladder(state)
        depth_advanced = True
        logger.info("Auto-advanced depth to %d", state.current_depth_level)

    # 3. Get next question (unless ending)
    if next_direction == "done":
        return {
            **score_result,
            "depth_advanced": depth_advanced,
            "new_depth_level": state.current_depth_level,
            "next_question": None,
            "interview_ending": True,
        }

    question_result = get_next_question(state, direction=next_direction)

    # If questions exhausted, return the last question for continued discussion
    if question_result.get("exhausted"):
        return {
            **score_result,
            "depth_advanced": depth_advanced,
            "new_depth_level": state.current_depth_level,
            "next_question": None,
            "questions_exhausted": True,
            "message": "No more prepared questions. STAY on the current coding problem. "
                       "You may ask about: code improvements, edge cases, error handling, "
                       "or performance. Do NOT introduce new topics like detection pipelines, "
                       "Sigma rules, or architecture. Do NOT end the interview unless the "
                       "candidate says they want to stop.",
        }

    return {
        **score_result,
        "depth_advanced": depth_advanced,
        "new_depth_level": state.current_depth_level,
        "next_question": question_result,
    }


# ---------------------------------------------------------------------------
# Convenience alias: get_tools() returns the list of tool declarations
# ---------------------------------------------------------------------------

def get_tools() -> list[dict]:
    """Return the list of ADK tool declarations for Gemini function calling."""
    return TOOL_DECLARATIONS


# ---------------------------------------------------------------------------
# Tool declarations for Gemini function calling
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS = [
    {
        "name": "get_next_question",
        "description": (
            "Fetch the next interview question. Call this when you need a new "
            "question to ask the candidate. Use direction='next' for a new topic, "
            "'deeper' to probe deeper on the current topic, or 'same' to rephrase "
            "the current question. The result includes expected_concepts (what a "
            "strong answer covers) and red_flags (patterns that indicate weakness). "
            "Use these as CONTEXT for your scoring, not for keyword matching."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["next", "deeper", "same"],
                    "description": "Direction to traverse the question tree",
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "advance_depth_ladder",
        "description": (
            "Move to the next depth level when the candidate has demonstrated "
            "sufficient understanding at the current level. Call this before "
            "asking a deeper probe question. Only advance when the candidate's "
            "response was strong or adequate."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "score_response",
        "description": (
            "Record your evaluation of the candidate's response. Call this after "
            "every substantive candidate response. YOU are the scorer. "
            "For TECHNICAL/BEHAVIORAL modes, evaluate: (1) technical_depth, "
            "(2) specificity, (3) communication. "
            "For CODING mode, evaluate ALL of: (1) approach (30%) - planning, "
            "problem breakdown, clarifying questions, (2) code_quality (25%) - "
            "syntax, structure, data structures, (3) security_insight (25%) - "
            "interpreting results, identifying attack chain, (4) communication "
            "(10%) - thinking out loud, explaining reasoning, (5) speed (10%) - "
            "reasonable pace, not stuck forever. "
            "Score each dimension 1-10. Be calibrated: 1-2 = weak/vague, "
            "3-4 = basic understanding, 5-6 = competent mid-level, "
            "7-8 = strong senior with depth, 9-10 = exceptional/architectural."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question that was asked",
                },
                "response": {
                    "type": "string",
                    "description": "Summary of the candidate's response",
                },
                "score": {
                    "type": "integer",
                    "description": "Overall score 1-10. 1-2=weak/vague, 3-4=basic understanding, 5-6=competent mid-level, 7-8=strong senior with depth, 9-10=exceptional/architectural",
                },
                "technical_depth": {
                    "type": "integer",
                    "description": "1-10. Did they explain WHY, not just WHAT? Show understanding of underlying principles?",
                },
                "specificity": {
                    "type": "integer",
                    "description": "1-10. Concrete examples? Real tool names, numbers, timelines, outcomes?",
                },
                "communication": {
                    "type": "integer",
                    "description": "1-10. Clear, organized, concise? Good use of structure (STAR for behavioral)? For coding: did they think out loud and explain reasoning?",
                },
                "approach": {
                    "type": "integer",
                    "description": "CODING MODE ONLY. 1-10. Did they plan before coding? Break down the problem? Ask clarifying questions before jumping in? (30% of coding score)",
                },
                "code_quality": {
                    "type": "integer",
                    "description": "CODING MODE ONLY. 1-10. Correct syntax, clean structure, appropriate data structures, error handling? (25% of coding score)",
                },
                "security_insight": {
                    "type": "integer",
                    "description": "CODING MODE ONLY. 1-10. Can they interpret the results? Identify suspicious activity? Explain the attack chain? Connect code output to real threats? (25% of coding score)",
                },
                "speed": {
                    "type": "integer",
                    "description": "CODING MODE ONLY. 1-10. Reasonable pace? Not stuck for extended periods? Efficient approach? (10% of coding score)",
                },
                "assessment": {
                    "type": "string",
                    "description": "1-2 sentence qualitative assessment of the response quality",
                },
                "key_strengths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What the candidate did well in this answer (1-3 items)",
                },
                "areas_to_probe": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Topics worth digging deeper on based on their answer (1-2 items)",
                },
            },
            "required": ["question", "response", "score", "assessment"],
        },
    },
    {
        "name": "end_interview",
        "description": (
            "End the interview session. Call this when all planned questions "
            "have been covered, the candidate asks to stop, or sufficient data "
            "has been collected for a meaningful report. Provide a reason."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the interview is ending",
                },
            },
            "required": ["reason"],
        },
    },
]
