"""Conservative compound-name normalization and candidate ranking."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

from config import AUTO_AI_CONFIDENCE, AUTO_LOCAL_SCORE, AUTO_SCORE_MARGIN
from .research_goal import ResearchGoal


_GREEK = {
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "ε": "epsilon",
    "κ": "kappa",
    "λ": "lambda",
    "μ": "mu",
    "ω": "omega",
}


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    for symbol, word in _GREEK.items():
        text = text.replace(symbol, f" {word} ")
    text = re.sub(r"[‐‑‒–—−_/]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _similarity(left: str, right: str) -> float:
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    left_tokens = set(a.split())
    right_tokens = set(b.split())
    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union) if union else 0.0
    return round((0.65 * sequence) + (0.35 * jaccard), 6)


def score_candidate(query: str, candidate: dict[str, Any]) -> float:
    score = _similarity(query, str(candidate.get("name", "")))
    for synonym in candidate.get("synonyms") or []:
        if normalize_name(query) == normalize_name(str(synonym)):
            score = max(score, 0.98)
        else:
            score = max(score, _similarity(query, str(synonym)))
    return round(min(score, 1.0), 6)


def rank_candidates(query: str, candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for original in candidates:
        item = dict(original)
        item["local_score"] = score_candidate(query, item)
        ranked.append(item)
    ranked.sort(key=lambda item: (-float(item["local_score"]), normalize_name(item.get("name", ""))))
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def should_auto_confirm(
    candidates: list[dict[str, Any]],
    ai: dict[str, Any] | None,
) -> tuple[bool, str]:
    if not candidates:
        return False, "no website candidates"
    if not ai or ai.get("abstain"):
        return False, "AI abstained or is unavailable"

    top = candidates[0]
    top_score = float(top.get("local_score", 0.0))
    second_score = float(candidates[1].get("local_score", 0.0)) if len(candidates) > 1 else 0.0
    margin = top_score - second_score
    ai_index = int(ai.get("selected_index") or 0)
    ai_confidence = float(ai.get("confidence") or 0.0)

    if top_score < AUTO_LOCAL_SCORE:
        return False, f"local score {top_score:.3f} is below {AUTO_LOCAL_SCORE:.2f}"
    if margin < AUTO_SCORE_MARGIN:
        return False, f"candidate margin {margin:.3f} is below {AUTO_SCORE_MARGIN:.2f}"
    if ai_index != 1:
        return False, "AI did not select the locally top-ranked candidate"
    if ai_confidence < AUTO_AI_CONFIDENCE:
        return False, f"AI confidence {ai_confidence:.3f} is below {AUTO_AI_CONFIDENCE:.2f}"
    return True, "local evidence and AI independently agree"


def _bounded(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _canonical_matches(values: Iterable[str], expected: tuple[str, ...]) -> list[str]:
    by_key = {normalize_name(value): value for value in expected}
    result: list[str] = []
    for value in values:
        canonical = by_key.get(normalize_name(str(value)))
        if canonical and canonical not in result:
            result.append(canonical)
    return result


def structural_conflicts(query: str, candidate: str, local_score: float = 0.0) -> list[str]:
    """Detect explicit contradictions; omission alone is not treated as a conflict."""

    if local_score >= 0.98:
        return []
    left = unicodedata.normalize("NFKC", query or "").casefold()
    right = unicodedata.normalize("NFKC", candidate or "").casefold()
    conflicts: list[str] = []

    left_locants = set(re.findall(r"(?<![a-z])\d+(?:['′’])?", left))
    right_locants = set(re.findall(r"(?<![a-z])\d+(?:['′’])?", right))
    if left_locants and right_locants and left_locants != right_locants:
        conflicts.append("position/locant mismatch")

    def explicit_tokens(text: str, values: tuple[str, ...]) -> set[str]:
        normalized = normalize_name(text)
        return {value for value in values if re.search(rf"\b{re.escape(value)}\b", normalized)}

    for label, values in (
        ("D/L stereochemistry", ("d", "l")),
        ("R/S stereochemistry", ("r", "s")),
        ("cis/trans stereochemistry", ("cis", "trans")),
        ("alpha/beta form", ("alpha", "beta")),
    ):
        left_values = explicit_tokens(left, values)
        right_values = explicit_tokens(right, values)
        if left_values and right_values and left_values != right_values:
            conflicts.append(f"{label} mismatch")

    modification_groups = (
        ("sulfate", "sulphate"),
        ("phosphate",),
        ("glucoside", "glucopyranoside"),
        ("glucuronide",),
        ("glycoside",),
        ("acetate", "acetyl"),
    )
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    for group in modification_groups:
        left_has = any(re.search(rf"\b{term}\b", left_normalized) for term in group)
        right_has = any(re.search(rf"\b{term}\b", right_normalized) for term in group)
        if left_has != right_has:
            conflicts.append(f"{group[0]} modification mismatch")
    return conflicts


def rank_goal_candidates(
    query: str,
    candidates: list[dict[str, Any]],
    ai: dict[str, Any],
    goal: ResearchGoal,
) -> list[dict[str, Any]]:
    """Attach goal/pathway evidence and sort using the agreed aggressive weights."""

    preference = goal.strength / 100.0
    weights = {
        "local": 0.70 - (0.50 * preference),
        "identity": 0.30 - (0.20 * preference),
        "target": 0.45 * preference,
        "pathway": 0.25 * preference,
    }
    assessments = {
        int(item.get("index") or 0): item
        for item in ai.get("candidate_assessments") or []
        if isinstance(item, dict)
    }
    ranked: list[dict[str, Any]] = []
    for original_index, original in enumerate(candidates, start=1):
        item = dict(original)
        assessment = assessments.get(original_index, {})
        identity = _bounded(assessment.get("identity_confidence"))
        target = _bounded(assessment.get("target_alignment"))
        pathway_relevance = _bounded(assessment.get("pathway_relevance"))
        exact_target = max(
            (_similarity(target_name, str(item.get("name", ""))) for target_name in goal.compounds),
            default=0.0,
        )
        target = max(target, exact_target if exact_target >= 0.95 else 0.0)

        evidence = item.get("pathway_evidence") or {}
        status = str(evidence.get("status") or "no_kegg")
        valid_pathway_ids = {
            str(pathway.get("id") or "") for pathway in evidence.get("pathways") or []
        }
        matched_ids = [
            value
            for value in (str(v) for v in assessment.get("matched_pathway_ids") or [])
            if value in valid_pathway_ids
        ]
        matched_targets = {
            "compounds": _canonical_matches(
                assessment.get("matched_compounds") or (), goal.compounds
            ),
            "classes": _canonical_matches(assessment.get("matched_classes") or (), goal.classes),
            "pathways": _canonical_matches(
                assessment.get("matched_pathways") or (), goal.pathways
            ),
        }
        target_pathway_match = bool(matched_ids and matched_targets["pathways"])
        if status == "linked":
            pathway_score = 1.0 if (not goal.pathways or target_pathway_match) else 0.5
        elif status == "id_only":
            pathway_score = max(0.60, pathway_relevance * 0.80)
        elif status in {"no_link", "unavailable"}:
            pathway_score = 0.25
        else:
            pathway_score = 0.0

        local = _bounded(item.get("local_score"))
        combined = (
            (weights["local"] * local)
            + (weights["identity"] * identity)
            + (weights["target"] * target)
            + (weights["pathway"] * pathway_score)
        )
        conflicts = structural_conflicts(query, str(item.get("name", "")), local)
        if assessment.get("hard_conflict"):
            conflicts.append("AI reported a structural conflict")
        item.update(
            {
                "original_rank": original_index,
                "identity_confidence": round(identity, 6),
                "target_alignment": round(target, 6),
                "pathway_relevance": round(pathway_relevance, 6),
                "pathway_score": round(pathway_score, 6),
                "goal_score": round(combined, 6),
                "preference_strength": goal.strength,
                "goal_weights": {name: round(value, 6) for name, value in weights.items()},
                "target_reason": str(assessment.get("reasoning") or ""),
                "matched_targets": matched_targets,
                "matched_pathway_ids": matched_ids,
                "target_pathway_match": target_pathway_match,
                "structural_conflicts": list(dict.fromkeys(conflicts)),
            }
        )
        ranked.append(item)

    ranked.sort(
        key=lambda item: (
            -float(item.get("goal_score", 0.0)),
            -float(item.get("local_score", 0.0)),
            normalize_name(item.get("name", "")),
        )
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def should_auto_confirm_goal(
    candidates: list[dict[str, Any]],
    ai: dict[str, Any] | None,
    goal: ResearchGoal,
) -> tuple[bool, str]:
    """Commercial one-pass policy: broad target preference with explicit safety rails."""

    if not candidates:
        return False, "no website candidates"
    if goal.strength <= 0:
        return False, "preference strength is 0; strict identity policy is active"
    if not ai or ai.get("abstain"):
        return False, "AI abstained or is unavailable"
    top = candidates[0]
    second = float(candidates[1].get("goal_score", 0.0)) if len(candidates) > 1 else 0.0
    margin = float(top.get("goal_score", 0.0)) - second
    if int(ai.get("selected_index") or 0) != int(top.get("original_rank") or 0):
        return False, "AI did not select the goal-ranked candidate"
    preference = goal.strength / 100.0
    thresholds = {
        "ai": 0.98 - (0.13 * preference),
        "identity": 0.95 - (0.55 * preference),
        "target": 0.90 - (0.40 * preference),
        "local": 0.95 - (0.90 * preference),
        "margin": 0.15 - (0.15 * preference),
    }
    if _bounded(ai.get("confidence")) < thresholds["ai"]:
        return False, f"AI confidence is below {thresholds['ai']:.2f}"
    if float(top.get("identity_confidence", 0.0)) < thresholds["identity"]:
        return False, f"identity confidence is below {thresholds['identity']:.2f}"
    if float(top.get("target_alignment", 0.0)) < thresholds["target"]:
        return False, f"target alignment is below {thresholds['target']:.2f}"
    if float(top.get("local_score", 0.0)) < thresholds["local"]:
        return False, f"local name evidence is below {thresholds['local']:.2f}"
    if margin < thresholds["margin"]:
        return False, f"goal-score margin is below {thresholds['margin']:.2f}"
    evidence = top.get("pathway_evidence") or {}
    evidence_status = evidence.get("status")
    if evidence_status == "linked":
        if goal.pathways and not top.get("target_pathway_match") and goal.strength < 100:
            return False, "candidate is not linked to a requested KEGG pathway"
    elif evidence_status == "id_only":
        if goal.strength < 50:
            return False, "KEGG ID-only evidence requires preference strength 50 or higher"
        if goal.pathways and (
            goal.strength < 80
            or float(top.get("pathway_relevance", 0.0)) < 0.75
            or not (top.get("matched_targets") or {}).get("pathways")
        ):
            return False, (
                "target-pathway inference from a KEGG ID requires strength 80, "
                "AI relevance 0.75, and an explicit requested-pathway match"
            )
    elif goal.strength < 100:
        return False, "candidate has no usable KEGG pathway evidence"
    if top.get("structural_conflicts") and goal.strength < 100:
        return False, "; ".join(str(v) for v in top["structural_conflicts"])
    return True, (
        "research goal, AI identity, and KEGG pathway evidence agree "
        f"at preference strength {goal.strength}/100"
    )
