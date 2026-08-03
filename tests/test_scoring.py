from modules.research_goal import ResearchGoal
from modules.scoring import (
    normalize_name,
    rank_candidates,
    rank_goal_candidates,
    should_auto_confirm,
    should_auto_confirm_goal,
    structural_conflicts,
)


def test_normalization_handles_greek_hyphen_and_case():
    assert normalize_name("β-Alanine") == normalize_name("Beta alanine")


def test_exact_synonym_and_ai_agreement_can_auto_confirm():
    ranked = rank_candidates(
        "Beta-Alanine",
        [
            {"name": "3-Aminopropanoic acid", "synonyms": ["β-Alanine"]},
            {"name": "L-Alanine", "synonyms": []},
        ],
    )
    allowed, reason = should_auto_confirm(
        ranked,
        {"selected_index": 1, "confidence": 0.96, "abstain": False},
    )
    assert allowed, reason
    assert ranked[0]["local_score"] == 0.98


def test_ai_only_or_small_margin_never_auto_confirms():
    ranked = rank_candidates("Test acid", [{"name": "Test acid A"}, {"name": "Test acid B"}])
    allowed, _ = should_auto_confirm(
        ranked,
        {"selected_index": 1, "confidence": 0.99, "abstain": False},
    )
    assert not allowed


def test_abstention_never_auto_confirms():
    ranked = rank_candidates("Fumaric acid", [{"name": "Fumaric acid"}])
    assert not should_auto_confirm(ranked, {"selected_index": 0, "confidence": 0, "abstain": True})[0]


def _goal_candidates():
    return [
        {
            "name": "Name-similar compound",
            "local_score": 0.95,
            "pathway_evidence": {"status": "no_link", "pathways": []},
        },
        {
            "name": "Target compound",
            "local_score": 0.60,
            "pathway_evidence": {
                "status": "linked",
                "pathways": [{"id": "map00010", "name": "Glycolysis"}],
            },
        },
    ]


def _goal_ai():
    return {
        "selected_index": 2,
        "confidence": 0.95,
        "abstain": False,
        "candidate_assessments": [
            {"index": 1, "identity_confidence": 0.95, "target_alignment": 0.10},
            {
                "index": 2,
                "identity_confidence": 0.85,
                "target_alignment": 0.95,
                "matched_classes": ["Carbohydrates"],
            },
        ],
    }


def test_preference_strength_can_move_goal_candidate_ahead():
    aggressive = ResearchGoal.create(classes=["Carbohydrates"], strength=80)
    ranked = rank_goal_candidates("Target compound", _goal_candidates(), _goal_ai(), aggressive)
    assert ranked[0]["name"] == "Target compound"
    allowed, reason = should_auto_confirm_goal(ranked, _goal_ai(), aggressive)
    assert allowed, reason

    strict = ResearchGoal.create(classes=["Carbohydrates"], strength=0)
    strict_ranked = rank_goal_candidates("Target compound", _goal_candidates(), _goal_ai(), strict)
    assert strict_ranked[0]["name"] == "Name-similar compound"
    assert not should_auto_confirm_goal(strict_ranked, _goal_ai(), strict)[0]


def test_explicit_position_conflict_blocks_below_full_automation():
    assert "position/locant mismatch" in structural_conflicts(
        "2-Hydroxysuberic Acid", "3-Hydroxysuberic acid", 0.79
    )
    goal = ResearchGoal.create(classes=["Hydroxy acids"], strength=80)
    candidate = {
        "name": "3-Hydroxysuberic acid",
        "local_score": 0.79,
        "pathway_evidence": {
            "status": "linked",
            "pathways": [{"id": "map00020", "name": "Citrate cycle"}],
        },
    }
    ai = {
        "selected_index": 1,
        "confidence": 0.99,
        "abstain": False,
        "candidate_assessments": [
            {"index": 1, "identity_confidence": 0.99, "target_alignment": 0.99}
        ],
    }
    ranked = rank_goal_candidates("2-Hydroxysuberic Acid", [candidate], ai, goal)
    allowed, reason = should_auto_confirm_goal(ranked, ai, goal)
    assert not allowed
    assert "position/locant" in reason


def test_strength_100_allows_ai_choice_without_kegg_or_structure_block():
    goal = ResearchGoal.create(classes=["Hydroxy acids"], strength=100)
    candidate = {
        "name": "3-Hydroxysuberic acid",
        "local_score": 0.79,
        "pathway_evidence": {"status": "no_link", "pathways": []},
    }
    ai = {
        "selected_index": 1,
        "confidence": 0.95,
        "abstain": False,
        "candidate_assessments": [
            {"index": 1, "identity_confidence": 0.80, "target_alignment": 0.95}
        ],
    }
    ranked = rank_goal_candidates("2-Hydroxysuberic Acid", [candidate], ai, goal)
    allowed, reason = should_auto_confirm_goal(ranked, ai, goal)
    assert allowed, reason


def test_strength_80_can_use_kegg_id_and_ai_pathway_inference():
    goal = ResearchGoal.create(pathways=["Glycolysis"], strength=80)
    candidate = {
        "name": "Target compound",
        "local_score": 0.70,
        "pathway_evidence": {"status": "id_only", "kegg_ids": ["C00031"], "pathways": []},
    }
    ai = {
        "selected_index": 1,
        "confidence": 0.95,
        "abstain": False,
        "candidate_assessments": [
            {
                "index": 1,
                "identity_confidence": 0.85,
                "target_alignment": 0.95,
                "pathway_relevance": 0.90,
                "matched_pathways": ["Glycolysis"],
            }
        ],
    }
    ranked = rank_goal_candidates("Target compound", [candidate], ai, goal)
    allowed, reason = should_auto_confirm_goal(ranked, ai, goal)
    assert allowed, reason
