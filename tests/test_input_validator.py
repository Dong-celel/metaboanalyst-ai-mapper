import csv

import pytest

from modules.input_validator import (
    InputValidationError,
    validate_concentration_table,
    validate_input,
    write_standardized_table,
)


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def test_validate_fixture():
    result = validate_concentration_table("tests/fixtures/pathway_small.csv")
    assert len(result.feature_names) == 12
    assert result.sample_names == (
        "control_1",
        "control_2",
        "control_3",
        "experiment_1",
        "experiment_2",
        "experiment_3",
    )
    assert result.groups == ("control", "experiment")
    assert result.kind == "concentration"


def test_mapping_input_uploads_only_comment_zero_queries():
    result = validate_input("tests/fixtures/name_map_small.csv")
    assert result.kind == "mapping"
    assert len(result.source_mapping) == 12
    assert len(result.feature_names) == 10
    assert "Deoxyuridine" not in result.feature_names
    assert "Fumaric acid" not in result.feature_names


def test_rejects_duplicate_features(tmp_path):
    path = tmp_path / "duplicate.csv"
    write_csv(path, [["samples", "a", "b"], ["group", "x", "y"], ["same", 1, 2], ["same", 3, 4]])
    with pytest.raises(InputValidationError, match="duplicate"):
        validate_concentration_table(path)


def test_rejects_non_numeric_cell(tmp_path):
    path = tmp_path / "bad.csv"
    write_csv(path, [["samples", "a", "b"], ["group", "x", "y"], ["metabolite", 1, "missing"]])
    with pytest.raises(InputValidationError, match="not numeric"):
        validate_concentration_table(path)


def test_standardized_copy_changes_only_confirmed_names(tmp_path):
    destination = tmp_path / "standardized.csv"
    write_standardized_table(
        "tests/fixtures/pathway_small.csv",
        destination,
        {"Beta-Alanine": "beta-Alanine"},
    )
    with destination.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "samples"
    assert rows[1][0] == "group"
    assert next(row for row in rows if row[0] == "beta-Alanine")[1:] == [
        "41",
        "39",
        "40",
        "44",
        "45",
        "43",
    ]
    assert any(row[0] == "No Match" for row in rows)
