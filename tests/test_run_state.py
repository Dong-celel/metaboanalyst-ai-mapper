import csv
import json

from modules.run_state import RunState, write_goal_coverage, write_review_queue


def test_state_is_checkpointed_and_reloadable(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("x\n", encoding="utf-8")
    state = RunState.create(tmp_path / "runs", input_path, "a" * 64)
    state.update_record("Fumaric acid", status="queued", candidates=[])
    state.audit("test_event", query="Fumaric acid")

    loaded = RunState.load(tmp_path / "runs", state.data["run_id"])
    assert loaded.records["Fumaric acid"]["status"] == "queued"
    audit = [json.loads(line) for line in loaded.paths.audit.read_text(encoding="utf-8").splitlines()]
    assert audit[0]["event"] == "test_event"


def test_review_queue_keeps_no_candidate_items(tmp_path):
    destination = tmp_path / "review.csv"
    write_review_queue(
        destination,
        [{"query": "Unknown compound", "status": "no_candidates", "candidates": []}],
    )
    with destination.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["Query"] == "Unknown compound"
    assert rows[0]["Status"] == "no_candidates"
    assert rows[0]["Reason"] == "website returned no candidates"
    assert rows[0]["TargetAlignment"] == ""
    assert rows[0]["KeggPathwayStatus"] == ""


def test_goal_coverage_reports_verified_target_pathway(tmp_path):
    destination = tmp_path / "goal.csv"
    candidate = {
        "name": "D-Glucose",
        "kegg": "C00031",
        "target_alignment": 0.97,
        "target_reason": "central glycolysis compound",
        "matched_targets": {"pathways": ["Glycolysis"]},
        "target_pathway_match": True,
        "pathway_evidence": {
            "status": "linked",
            "pathways": [{"id": "map00010", "name": "Glycolysis / Gluconeogenesis"}],
        },
    }
    write_goal_coverage(
        destination,
        {"pathways": ["Glycolysis"]},
        [
            {
                "query": "Glucose",
                "verified": True,
                "decision": {"candidate": candidate},
            }
        ],
    )
    with destination.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["Status"] == "verified_in_target_pathway"
    assert row["SelectedCandidate"] == "D-Glucose"
