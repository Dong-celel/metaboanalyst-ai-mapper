import pytest

from modules.research_goal import ResearchGoal, parse_goal_line


def test_semicolon_parser_preserves_commas_in_chemical_names():
    assert parse_goal_line("2,4-Dihydroxybenzoic acid；Glucose") == (
        "2,4-Dihydroxybenzoic acid",
        "Glucose",
    )


def test_preference_strength_is_serialized_and_validated():
    goal = ResearchGoal.create(["葡萄糖"], ["糖类"], ["糖酵解"], 85)
    assert ResearchGoal.from_dict(goal.as_dict()) == goal
    assert goal.active
    with pytest.raises(ValueError):
        ResearchGoal.create(strength=101)
