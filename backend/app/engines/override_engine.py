"""
Applies user edits from a re-uploaded RCM workbook as non-destructive
overlays (control_overlays; the original upload is never mutated, so it stays
the audit trail).

Merge semantics are deliberate:
  - A control PRESENT in the sheet is updated.
  - A control ABSENT from the sheet is left alone — never deleted.
  - A blank cell means "no change", not "clear this field". Clearing needs an
    explicit "-" so it can't happen by accident.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("engines.override_engine")

CLEAR_TOKEN = "-"

# Sheet header -> canonical control field.
_RCM_FIELD_HEADERS = {
    "control id": "control_id",
    "control description": "control_description",
    "risk description": "risk_description",
    "risk level": "risk_level",
    "control type": "control_type",
    "control nature": "control_nature",
    "control frequency": "control_frequency",
    "control owner": "control_owner",
    "process": "process",
}

OVERRIDABLE_FIELDS = [f for f in _RCM_FIELD_HEADERS.values() if f != "control_id"]


def _read_sheet(file_path: Path) -> pd.DataFrame:
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(file_path, dtype=str).fillna("")
    return pd.read_excel(file_path, sheet_name=0, dtype=str).fillna("")


def _normalize_headers(df: pd.DataFrame, mapping: dict[str, str]) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in mapping:
            resolved[col] = mapping[key]
    return resolved


def parse_rcm_overrides(file_path: Path, known_control_ids: set[str]) -> dict[str, Any]:
    """Returns {overrides: {control_id: {field: value}}, unknown_control_ids,
    cleared, skipped_no_change}. `value = None` means clear the field."""
    df = _read_sheet(file_path)
    header_map = _normalize_headers(df, _RCM_FIELD_HEADERS)
    if "control_id" not in header_map.values():
        raise ValueError("The sheet needs a 'Control ID' column so edits can be matched to controls.")

    overrides: dict[str, dict[str, Any]] = {}
    unknown: list[str] = []
    cleared = 0

    for _, row in df.iterrows():
        control_id = ""
        values: dict[str, Any] = {}
        for col, field in header_map.items():
            raw = str(row.get(col, "")).strip()
            if field == "control_id":
                control_id = raw
                continue
            if not raw:
                continue  # blank = no change
            if raw == CLEAR_TOKEN:
                values[field] = None
                cleared += 1
            else:
                values[field] = raw

        if not control_id:
            continue
        if control_id not in known_control_ids:
            unknown.append(control_id)
            continue
        if values:
            overrides[control_id] = values

    return {
        "overrides": overrides,
        "unknown_control_ids": sorted(set(unknown)),
        "cleared_fields": cleared,
    }
