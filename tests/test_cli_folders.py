from pathlib import Path
from types import SimpleNamespace

import pytest

from main import _discover_input
from modules.input_validator import InputValidationError
from modules.run_state import RunState
from modules.workflow import _publish_outputs


def test_discover_input_accepts_exactly_one_csv(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "README.md").write_text("instructions", encoding="utf-8")
    expected = input_dir / "name_map.csv"
    expected.write_text("Query,Comment\nA,0\n", encoding="utf-8")
    assert _discover_input(input_dir) == expected.resolve()


def test_discover_input_never_guesses_between_files(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "one.csv").write_text("x\n", encoding="utf-8")
    (input_dir / "two.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(InputValidationError, match="multiple input files"):
        _discover_input(input_dir)


def test_publish_outputs_copies_operator_files_to_output_run_folder(tmp_path):
    input_path = tmp_path / "name_map.csv"
    input_path.write_text("Query,Comment\nA,0\n", encoding="utf-8")
    state = RunState.create(tmp_path / "runs", input_path, "b" * 64)
    state.paths.mapping_final.write_text("Query,Comment\nA,1\n", encoding="utf-8")
    state.paths.review_queue.write_text("Query,Status\n", encoding="utf-8")
    validation = SimpleNamespace(kind="mapping", path=input_path)

    published = _publish_outputs(validation, state, tmp_path / "output")

    processed = Path(published["processed"])
    review = Path(published["review_queue"])
    assert processed.parent.name == state.data["run_id"]
    assert processed.name == "name_map_processed.csv"
    assert processed.read_text(encoding="utf-8") == "Query,Comment\nA,1\n"
    assert review.is_file()
    assert Path(published["goal_coverage"]).is_file()
    explanation = Path(published["explanation"])
    assert explanation.is_file()
    assert "AIConfidence" in explanation.read_text(encoding="utf-8")
