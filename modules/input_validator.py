"""Validation and safe rewriting for MetaboAnalyst concentration tables."""

from __future__ import annotations

import csv
import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class InputValidationError(ValueError):
    """Raised when a concentration table cannot be uploaded safely."""


@dataclass(frozen=True)
class ValidationResult:
    path: Path
    sha256: str
    kind: str
    headers: tuple[str, ...]
    feature_column: str
    sample_names: tuple[str, ...]
    groups: tuple[str, ...]
    feature_names: tuple[str, ...]
    source_mapping: tuple[dict[str, str], ...]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_rows(path: Path) -> tuple[list[str], list[list[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except UnicodeDecodeError as exc:
        raise InputValidationError("CSV must be UTF-8 encoded") from exc

    if not rows:
        raise InputValidationError("CSV is empty")
    headers = [cell.strip() for cell in rows[0]]
    data = rows[1:]
    return headers, data


def validate_concentration_table(path: str | Path) -> ValidationResult:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InputValidationError(f"file does not exist: {source}")
    if source.suffix.lower() not in {".csv", ".txt"}:
        raise InputValidationError("input must be a .csv or .txt concentration table")

    headers, rows = _read_rows(source)
    if len(headers) < 3:
        raise InputValidationError("table needs one feature column and at least two samples")
    if any(not value for value in headers):
        raise InputValidationError("column names cannot be empty")
    if len(set(headers)) != len(headers):
        raise InputValidationError("sample/column names must be unique")
    if len(rows) < 2:
        raise InputValidationError("table needs a group row followed by metabolite rows")

    width = len(headers)
    for line_no, row in enumerate(rows, start=2):
        if len(row) != width:
            raise InputValidationError(
                f"line {line_no} has {len(row)} columns; expected {width}"
            )

    group_row = rows[0]
    group_marker = group_row[0].strip().casefold()
    if group_marker not in {"group", "class", "label"}:
        raise InputValidationError(
            "the second line must be the group row (first cell: group, class, or label)"
        )
    groups = tuple(value.strip() for value in group_row[1:])
    if any(not value for value in groups):
        raise InputValidationError("group labels cannot be empty")
    if len(set(groups)) < 2:
        raise InputValidationError("discrete analysis requires at least two groups")

    feature_names: list[str] = []
    for line_no, row in enumerate(rows[1:], start=3):
        feature = row[0].strip()
        if not feature:
            raise InputValidationError(f"line {line_no} has an empty metabolite name")
        feature_names.append(feature)
        for column_no, raw in enumerate(row[1:], start=2):
            try:
                value = float(raw)
            except ValueError as exc:
                raise InputValidationError(
                    f"line {line_no}, column {column_no} is not numeric: {raw!r}"
                ) from exc
            if not math.isfinite(value):
                raise InputValidationError(
                    f"line {line_no}, column {column_no} must be a finite number"
                )

    if len(set(feature_names)) != len(feature_names):
        seen: set[str] = set()
        duplicate = next(name for name in feature_names if name in seen or seen.add(name))
        raise InputValidationError(f"metabolite names must be unique; duplicate: {duplicate}")

    return ValidationResult(
        path=source,
        sha256=file_sha256(source),
        kind="concentration",
        headers=tuple(headers),
        feature_column=headers[0],
        sample_names=tuple(headers[1:]),
        groups=tuple(dict.fromkeys(groups)),
        feature_names=tuple(feature_names),
        source_mapping=(),
    )


def validate_mapping_table(path: str | Path) -> ValidationResult:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InputValidationError(f"file does not exist: {source}")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = tuple(reader.fieldnames or ())
            rows = [dict(row) for row in reader]
    except UnicodeDecodeError as exc:
        raise InputValidationError("mapping CSV must be UTF-8 encoded") from exc
    required = {"Query", "Comment"}
    if not required.issubset(headers):
        raise InputValidationError("mapping CSV requires Query and Comment columns")
    queries = [str(row.get("Query") or "").strip() for row in rows]
    if any(not query for query in queries):
        raise InputValidationError("mapping CSV contains an empty Query")
    if len(set(queries)) != len(queries):
        raise InputValidationError("mapping Query values must be unique")
    invalid = sorted({str(row.get("Comment") or "").strip() for row in rows} - {"0", "1"})
    if invalid:
        raise InputValidationError(f"mapping Comment values must be 0 or 1; found: {invalid}")
    unmatched = tuple(
        str(row["Query"]).strip() for row in rows if str(row.get("Comment") or "").strip() == "0"
    )
    return ValidationResult(
        path=source,
        sha256=file_sha256(source),
        kind="mapping",
        headers=headers,
        feature_column="Query",
        sample_names=(),
        groups=(),
        feature_names=unmatched,
        source_mapping=tuple(rows),
    )


def validate_input(path: str | Path) -> ValidationResult:
    """Auto-detect a website mapping CSV or a concentration table."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise InputValidationError(f"file does not exist: {source}")
    headers, _ = _read_rows(source)
    if {"Query", "Comment"}.issubset(headers):
        return validate_mapping_table(source)
    return validate_concentration_table(source)


def write_standardized_table(
    source: str | Path,
    destination: str | Path,
    confirmed_names: Mapping[str, str],
) -> None:
    """Copy a table while replacing only explicitly confirmed feature names."""

    source_path = Path(source)
    destination_path = Path(destination)
    headers, rows = _read_rows(source_path)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with destination_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for index, row in enumerate(rows):
            copied = list(row)
            if index > 0:
                original = copied[0].strip()
                copied[0] = confirmed_names.get(original, original)
            writer.writerow(copied)
