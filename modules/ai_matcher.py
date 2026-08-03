"""Privacy-bounded DeepSeek candidate judging."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from openai import OpenAI

from config import (
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    DEEPSEEK_REASONING_EFFORT,
    DEEPSEEK_THINKING_ENABLED,
    deepseek_api_key,
)


def _extract_json(text: str) -> dict[str, Any]:
    value = text.strip()
    if "```" in value:
        parts = value.split("```")
        if len(parts) >= 3:
            value = parts[1]
            if value.lstrip().startswith("json"):
                value = value.lstrip()[4:]
    parsed = json.loads(value.strip())
    if not isinstance(parsed, dict):
        raise ValueError("AI response must be a JSON object")
    return parsed


class AIMatcher:
    """Judge names and IDs only; concentration and sample data never enter prompts."""

    def __init__(self, client: OpenAI | None = None):
        api_key = deepseek_api_key()
        self.enabled = bool(api_key or client)
        if client is not None:
            self.client = client
        elif self.enabled:
            kwargs: dict[str, Any] = {
                "api_key": api_key,
                "base_url": DEEPSEEK_BASE_URL,
            }
            proxy = os.getenv("DEEPSEEK_PROXY", "").strip()
            if proxy:
                import httpx

                kwargs["http_client"] = httpx.Client(proxy=proxy, timeout=45.0)
            self.client = OpenAI(**kwargs)
        else:
            self.client = None

    def judge_candidates(
        self,
        query_name: str,
        candidates: list[dict[str, Any]],
        research_goal: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal = research_goal or {}
        goal_active = bool(
            goal.get("compounds") or goal.get("classes") or goal.get("pathways")
        )
        if not self.enabled or self.client is None:
            return {
                "selected_index": 0,
                "confidence": 0.0,
                "reasoning": "DEEPSEEK_API_KEY is not configured",
                "abstain": True,
                "candidate_assessments": [],
            }
        if not candidates:
            return {
                "selected_index": 0,
                "confidence": 0.0,
                "reasoning": "No website candidates",
                "abstain": True,
                "candidate_assessments": [],
            }

        safe_candidates = []
        for index, candidate in enumerate(candidates, start=1):
            safe = {
                    "index": index,
                    "name": candidate.get("name", ""),
                    "HMDB": candidate.get("hmdb", "NA"),
                    "KEGG": candidate.get("kegg", "NA"),
                    "PubChem": candidate.get("pubchem", "NA"),
                    "ChEBI": candidate.get("chebi", "NA"),
                    "MetLin": candidate.get("metlin", "NA"),
            }
            if goal_active:
                safe["local_name_score"] = candidate.get("local_score", 0.0)
                safe["kegg_pathway_evidence"] = candidate.get("pathway_evidence") or {}
            safe_candidates.append(safe)
        response_schema: dict[str, Any] = {
            "selected_index": "1-based integer; 0 when abstaining",
            "confidence": "number from 0 to 1",
            "reasoning": "short explanation",
            "abstain": "boolean",
        }
        if goal_active:
            response_schema["candidate_assessments"] = [
                {
                    "index": "1-based candidate index",
                    "identity_confidence": "0 to 1",
                    "target_alignment": "0 to 1",
                    "pathway_relevance": "0 to 1",
                    "hard_conflict": "boolean",
                    "matched_compounds": "research-goal compound strings copied exactly",
                    "matched_classes": "research-goal class strings copied exactly",
                    "matched_pathways": "research-goal pathway strings copied exactly",
                    "matched_pathway_ids": "IDs copied from supplied KEGG evidence only",
                    "reasoning": "short candidate-specific explanation",
                }
            ]
        prompt = {
            "query_name": query_name,
            "website_candidates": safe_candidates,
            "research_goal": goal if goal_active else {},
            "task": (
                "Select the candidate that best represents the query. Actively prefer a candidate "
                "aligned with the desired compounds, classes, and pathways, using supplied KEGG links "
                "as stronger evidence than general knowledge. The goal may break a weak naming tie, but "
                "explicitly report contradictory locants, stereochemistry, or covalent modifications. "
                "Never invent a candidate or a KEGG pathway link."
                if goal_active
                else "Select the candidate that represents the same chemical identity. Respect "
                "stereochemistry and substitution positions. Abstain when evidence is insufficient."
            ),
            "response_schema": response_schema,
        }
        system_message = (
            "You are a goal-oriented metabolomics nomenclature reviewer for a commercial data "
            "service. Maximize useful pathway coverage while keeping every choice auditable. "
            "Return JSON only and never invent a candidate or database evidence."
            if goal_active
            else "You are a conservative metabolomics nomenclature reviewer. Return JSON only and "
            "never invent a candidate."
        )
        try:
            request: dict[str, Any] = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": system_message,
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                "stream": False,
                "max_tokens": 1600 if goal_active else 400,
            }
            if DEEPSEEK_THINKING_ENABLED:
                request["reasoning_effort"] = DEEPSEEK_REASONING_EFFORT
                request["extra_body"] = {"thinking": {"type": "enabled"}}
            else:
                request["temperature"] = 0.0
            response = self.client.chat.completions.create(**request)
            result = _extract_json(response.choices[0].message.content or "{}")
            selected = int(result.get("selected_index") or 0)
            confidence = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
            abstain = bool(result.get("abstain", False)) or selected == 0
            assessments: list[dict[str, Any]] = []
            for raw in result.get("candidate_assessments") or []:
                if not isinstance(raw, dict):
                    continue
                index = int(raw.get("index") or 0)
                if index < 1 or index > len(candidates):
                    continue

                def bounded(key: str) -> float:
                    return max(0.0, min(1.0, float(raw.get(key) or 0.0)))

                assessments.append(
                    {
                        "index": index,
                        "identity_confidence": bounded("identity_confidence"),
                        "target_alignment": bounded("target_alignment"),
                        "pathway_relevance": bounded("pathway_relevance"),
                        "hard_conflict": bool(raw.get("hard_conflict", False)),
                        "matched_compounds": [str(v) for v in raw.get("matched_compounds") or []],
                        "matched_classes": [str(v) for v in raw.get("matched_classes") or []],
                        "matched_pathways": [str(v) for v in raw.get("matched_pathways") or []],
                        "matched_pathway_ids": [
                            str(v) for v in raw.get("matched_pathway_ids") or []
                        ],
                        "reasoning": str(raw.get("reasoning") or ""),
                    }
                )
        except Exception as exc:
            # A network error or non-JSON response must never turn a long scan
            # into a failed run.  It is conservative evidence to abstain and
            # send the item to the manual review queue.
            return {
                "selected_index": 0,
                "confidence": 0.0,
                "reasoning": f"AI unavailable or invalid response: {type(exc).__name__}",
                "abstain": True,
                "candidate_assessments": [],
            }
        if selected < 0 or selected > len(candidates):
            selected = 0
            abstain = True
        return {
            "selected_index": selected,
            "confidence": confidence,
            "reasoning": str(result.get("reasoning") or ""),
            "abstain": abstain,
            "candidate_assessments": assessments,
        }

    # Backward-compatible helper for the original local matcher.
    def select_best_match(
        self,
        query_name: str,
        candidates: list[dict[str, Any]],
        pathway_hint: Optional[str] = None,
        expected_compounds: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        judgment = self.judge_candidates(query_name, candidates)
        index = int(judgment.get("selected_index") or 0)
        if judgment.get("abstain") or index < 1:
            return None
        selected = dict(candidates[index - 1])
        selected["ai_reason"] = judgment.get("reasoning", "")
        return selected

    def suggest_standard_names(
        self,
        query_name: str,
        pathway_hint: Optional[str] = None,
        expected_compounds: Optional[list[str]] = None,
    ) -> list[str]:
        # Website candidates are authoritative in the new workflow.  The legacy
        # local matcher no longer asks the model to invent names.
        return []
