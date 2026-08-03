from types import SimpleNamespace

from modules.ai_matcher import AIMatcher


class FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **_kwargs):
        self.kwargs = _kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def fake_client(content):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(content)))


def test_non_json_ai_response_abstains_instead_of_failing_run():
    matcher = AIMatcher(client=fake_client("not JSON"))
    result = matcher.judge_candidates("query", [{"name": "candidate"}])
    assert result["abstain"] is True
    assert result["selected_index"] == 0
    assert "JSONDecodeError" in result["reasoning"]


def test_out_of_range_ai_selection_is_forced_to_abstain():
    matcher = AIMatcher(
        client=fake_client(
            '{"selected_index": 3, "confidence": 0.99, "reasoning": "x", "abstain": false}'
        )
    )
    result = matcher.judge_candidates("query", [{"name": "candidate"}])
    assert result["abstain"] is True
    assert result["selected_index"] == 0


def test_goal_assessments_are_parsed_and_prompt_contains_no_sample_data():
    completions = FakeCompletions(
        '{"selected_index":2,"confidence":0.94,"reasoning":"goal fit",'
        '"abstain":false,"candidate_assessments":[{"index":2,'
        '"identity_confidence":0.82,"target_alignment":0.96,'
        '"pathway_relevance":0.9,"hard_conflict":false,'
        '"matched_classes":["Flavonoids"],"matched_pathway_ids":["map00941"]}]}'
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    matcher = AIMatcher(client=client)
    result = matcher.judge_candidates(
        "Query",
        [
            {"name": "A"},
            {
                "name": "B",
                "kegg": "C00001",
                "pathway_evidence": {
                    "status": "linked",
                    "pathways": [{"id": "map00941", "name": "Flavonoid biosynthesis"}],
                },
            },
        ],
        {"classes": ["Flavonoids"], "compounds": [], "pathways": []},
    )
    assert result["selected_index"] == 2
    assert result["candidate_assessments"][0]["target_alignment"] == 0.96
    prompt = completions.kwargs["messages"][1]["content"]
    assert "Flavonoids" in prompt
    assert "sample" not in prompt.casefold()
    assert "concentration" not in prompt.casefold()
    assert completions.kwargs["model"] == "deepseek-v4-pro"
    assert completions.kwargs["stream"] is False
    assert completions.kwargs["reasoning_effort"] == "high"
    assert completions.kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
