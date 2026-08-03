"""Atomic checkpointing and audit artifacts for long website runs."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def audit(self) -> Path:
        return self.root / "audit.jsonl"

    @property
    def mapping_before(self) -> Path:
        return self.root / "mapping_before.csv"

    @property
    def mapping_final(self) -> Path:
        return self.root / "mapping_final.csv"

    @property
    def review_queue(self) -> Path:
        return self.root / "review_queue.csv"

    @property
    def standardized(self) -> Path:
        return self.root / "Metabolite_data_standardized.csv"

    @property
    def goal_coverage(self) -> Path:
        return self.root / "goal_coverage.csv"


class RunState:
    def __init__(self, paths: RunPaths, data: dict[str, Any]):
        self.paths = paths
        self.data = data

    @classmethod
    def create(cls, runs_dir: Path, input_path: Path, input_sha256: str) -> "RunState":
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}-{input_sha256[:8]}"
        root = runs_dir.expanduser().resolve() / run_id
        root.mkdir(parents=True, exist_ok=False)
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "input_path": str(input_path),
            "input_sha256": input_sha256,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "stage": "created",
            "network": {},
            "preflight": {},
            "records": {},
        }
        state = cls(RunPaths(root), data)
        state.save()
        return state

    @classmethod
    def load(cls, runs_dir: Path, value: str) -> "RunState":
        supplied = Path(value).expanduser()
        root = supplied if supplied.is_dir() else runs_dir.expanduser() / value
        root = root.resolve()
        state_path = root / "state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"resume state not found: {state_path}")
        with state_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported state.json schema version")
        return cls(RunPaths(root), data)

    @property
    def records(self) -> dict[str, dict[str, Any]]:
        return self.data.setdefault("records", {})

    def save(self) -> None:
        self.data["updated_at"] = utc_now()
        self.paths.root.mkdir(parents=True, exist_ok=True)
        temporary = self.paths.state.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(self.paths.state)

    def set_stage(self, stage: str) -> None:
        self.data["stage"] = stage
        self.save()

    def update_record(self, query: str, **values: Any) -> dict[str, Any]:
        record = self.records.setdefault(query, {"query": query, "status": "pending"})
        record.update(values)
        record["updated_at"] = utc_now()
        self.save()
        return record

    def audit(self, event: str, **payload: Any) -> None:
        item = {"timestamp": utc_now(), "event": event, **payload}
        with self.paths.audit.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()


MAPPING_FIELDS = [
    "Query",
    "Match",
    "HMDB",
    "KEGG",
    "PubChem",
    "ChEBI",
    "MetLin",
    "SMILES",
    "Comment",
]


def write_mapping_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MAPPING_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "NA") for field in MAPPING_FIELDS})


def read_mapping_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_review_queue(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    fields = [
        "Query",
        "Status",
        "Rank",
        "Candidate",
        "LocalScore",
        "IdentityConfidence",
        "TargetAlignment",
        "GoalScore",
        "PreferenceStrength",
        "PathwayRelevance",
        "KeggPathwayStatus",
        "LinkedPathways",
        "TargetReason",
        "StructuralConflict",
        "HMDB",
        "KEGG",
        "PubChem",
        "ChEBI",
        "MetLin",
        "AISelected",
        "AIConfidence",
        "Reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            ai = record.get("ai") or {}
            candidates = record.get("candidates") or []
            policy = record.get("auto_policy") or {}
            error = record.get("error") or {}
            reason = str(
                policy.get("reason")
                or ai.get("reasoning")
                or error.get("message")
                or ("website returned no candidates" if not candidates else "")
            )
            if not candidates:
                writer.writerow(
                    {
                        "Query": record.get("query", ""),
                        "Status": record.get("status", ""),
                        "Rank": "",
                        "Candidate": "",
                        "LocalScore": "",
                        "IdentityConfidence": "",
                        "TargetAlignment": "",
                        "GoalScore": "",
                        "PreferenceStrength": "",
                        "PathwayRelevance": "",
                        "KeggPathwayStatus": "",
                        "LinkedPathways": "",
                        "TargetReason": "",
                        "StructuralConflict": "",
                        "HMDB": "NA",
                        "KEGG": "NA",
                        "PubChem": "NA",
                        "ChEBI": "NA",
                        "MetLin": "NA",
                        "AISelected": ai.get("selected_index", ""),
                        "AIConfidence": ai.get("confidence", ""),
                        "Reason": reason,
                    }
                )
                continue
            for rank, candidate in enumerate(candidates, start=1):
                writer.writerow(
                    {
                        "Query": record.get("query", ""),
                        "Status": record.get("status", ""),
                        "Rank": rank,
                        "Candidate": candidate.get("name", ""),
                        "LocalScore": candidate.get("local_score", ""),
                        "IdentityConfidence": candidate.get("identity_confidence", ""),
                        "TargetAlignment": candidate.get("target_alignment", ""),
                        "GoalScore": candidate.get("goal_score", ""),
                        "PreferenceStrength": candidate.get("preference_strength", ""),
                        "PathwayRelevance": candidate.get("pathway_relevance", ""),
                        "KeggPathwayStatus": (candidate.get("pathway_evidence") or {}).get(
                            "status", ""
                        ),
                        "LinkedPathways": "; ".join(
                            str(item.get("name") or item.get("id") or "")
                            for item in (candidate.get("pathway_evidence") or {}).get(
                                "pathways", []
                            )
                        ),
                        "TargetReason": candidate.get("target_reason", ""),
                        "StructuralConflict": "; ".join(
                            str(value) for value in candidate.get("structural_conflicts") or []
                        ),
                        "HMDB": candidate.get("hmdb", "NA"),
                        "KEGG": candidate.get("kegg", "NA"),
                        "PubChem": candidate.get("pubchem", "NA"),
                        "ChEBI": candidate.get("chebi", "NA"),
                        "MetLin": candidate.get("metlin", "NA"),
                        "AISelected": ai.get("selected_index", ""),
                        "AIConfidence": ai.get("confidence", ""),
                        "Reason": reason,
                    }
                )


def write_goal_coverage(
    path: Path,
    research_goal: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
) -> None:
    """Summarize whether each requested goal was supported by verified selections."""

    fields = [
        "GoalType",
        "Goal",
        "Status",
        "Query",
        "SelectedCandidate",
        "KEGG",
        "LinkedPathways",
        "Evidence",
        "PreferenceStrength",
        "AIConfidence",
        "IdentityConfidence",
        "TargetAlignment",
        "GoalScore",
    ]
    items = list(records)

    def key(value: object) -> str:
        return " ".join(str(value or "").casefold().split())

    def candidate_matches(candidate: Mapping[str, Any], query: str, goal_type: str, goal: str) -> bool:
        matched = candidate.get("matched_targets") or {}
        bucket = {
            "compound": "compounds",
            "class": "classes",
            "pathway": "pathways",
        }[goal_type]
        if any(key(value) == key(goal) for value in matched.get(bucket) or []):
            return True
        if goal_type == "compound":
            return key(candidate.get("name")) == key(goal) or key(query) == key(goal)
        return False

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for goal_type, bucket in (
            ("compound", "compounds"),
            ("class", "classes"),
            ("pathway", "pathways"),
        ):
            for goal in research_goal.get(bucket) or []:
                matches: list[tuple[Mapping[str, Any], Mapping[str, Any], bool]] = []
                for record in items:
                    decision_candidate = (record.get("decision") or {}).get("candidate") or {}
                    candidates = [decision_candidate] if decision_candidate else record.get("candidates") or []
                    for candidate in candidates:
                        if candidate_matches(candidate, str(record.get("query") or ""), goal_type, str(goal)):
                            matches.append((record, candidate, bool(record.get("verified"))))
                verified = next((item for item in matches if item[2]), None)
                pending = next(iter(matches), None)
                selected = verified or pending
                if verified:
                    record, candidate, _ = verified
                    evidence = candidate.get("pathway_evidence") or {}
                    if goal_type == "pathway" and candidate.get("target_pathway_match"):
                        status = "verified_in_target_pathway"
                    elif evidence.get("status") == "linked":
                        status = "pathway_ready"
                    elif evidence.get("status") == "id_only":
                        status = "selected_with_kegg_id"
                    else:
                        status = "selected_without_pathway_link"
                elif pending:
                    record, candidate, _ = pending
                    evidence = candidate.get("pathway_evidence") or {}
                    status = "review_required"
                else:
                    record, candidate, evidence = {}, {}, {}
                    status = "not_found"
                writer.writerow(
                    {
                        "GoalType": goal_type,
                        "Goal": goal,
                        "Status": status,
                        "Query": record.get("query", ""),
                        "SelectedCandidate": candidate.get("name", ""),
                        "KEGG": candidate.get("kegg", "NA") if candidate else "NA",
                        "LinkedPathways": "; ".join(
                            str(item.get("name") or item.get("id") or "")
                            for item in evidence.get("pathways") or []
                        ),
                        "Evidence": candidate.get("target_reason", "") if candidate else "",
                        "PreferenceStrength": research_goal.get("strength", 80),
                        "AIConfidence": (record.get("ai") or {}).get("confidence", ""),
                        "IdentityConfidence": candidate.get("identity_confidence", "") if candidate else "",
                        "TargetAlignment": candidate.get("target_alignment", "") if candidate else "",
                        "GoalScore": candidate.get("goal_score", "") if candidate else "",
                    }
                )
