import json

from modules.research_goal import ResearchGoal
from modules.run_state import RunState
from modules.workflow import _inspect_one


class FakeBrowser:
    def __init__(self):
        self.applied = None

    def inspect_candidates(self, _query):
        return [
            {"name": "Target acid A", "kegg": "C00001", "pubchem": "NA"},
            {"name": "Desired target acid", "kegg": "C00002", "pubchem": "NA"},
        ]

    def apply_candidate(self, query, candidate):
        self.applied = candidate
        return {"Query": query, "Match": candidate["name"], "Comment": "1"}


class FakeAI:
    def judge_candidates(self, _query, candidates, research_goal):
        assert candidates[0]["name"] == "Target acid A"
        assert research_goal["strength"] == 80
        return {
            "selected_index": 2,
            "confidence": 0.96,
            "reasoning": "customer target",
            "abstain": False,
            "candidate_assessments": [
                {"index": 1, "identity_confidence": 0.95, "target_alignment": 0.10},
                {
                    "index": 2,
                    "identity_confidence": 0.90,
                    "target_alignment": 0.96,
                    "pathway_relevance": 0.90,
                    "matched_classes": ["Desired acids"],
                    "reasoning": "fits requested class",
                },
            ],
        }


class FakePubChem:
    def synonyms(self, _cid):
        return []


class FakeKegg:
    def __init__(self):
        self.cache = {}

    def evidence(self, value):
        result = {"status": "id_only", "kegg_ids": [value], "pathways": [], "error": ""}
        self.cache[value] = result
        return result


def test_goal_priority_decision_is_applied_and_audited(tmp_path):
    input_path = tmp_path / "input.csv"
    input_path.write_text("Query,Comment\nTarget acid,0\n", encoding="utf-8")
    state = RunState.create(tmp_path / "runs", input_path, "c" * 64)
    browser = FakeBrowser()

    _inspect_one(
        "Target acid",
        browser,
        state,
        FakeAI(),
        FakePubChem(),
        FakeKegg(),
        {},
        ResearchGoal.create(classes=["Desired acids"], strength=80),
    )

    record = state.records["Target acid"]
    assert record["status"] == "auto_applied"
    assert record["decision"]["source"] == "automatic_goal_priority"
    assert browser.applied["name"] == "Desired target acid"
    events = [
        json.loads(line)["event"]
        for line in state.paths.audit.read_text(encoding="utf-8").splitlines()
    ]
    assert "automatic_goal_priority_ready" in events
    assert "automatic_goal_priority_applied" in events
