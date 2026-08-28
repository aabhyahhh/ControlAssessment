"""
Applies user edits from a re-uploaded workbook.

Two round-trips are supported:
  - RCM overrides  -> control_overlays (non-destructive; the original upload
                      is never mutated, so it stays the audit trail)
  - Attribute edits -> control_attributes, re-run through the quality gate

Merge semantics are deliberate (ATTRIBUTE_GENERATION_ENGINE_SPEC Section 5.4
warns that the reference implementation's defaults surprise people):
  - A control PRESENT in the sheet is updated.
  - A control ABSENT from the sheet is left alone — never deleted. Silent
    delete-by-omission is too easy to trigger by accident and too costly.
  - A blank cell means "no change", not "clear this field". Clearing needs
    an explicit "-" so it can't happen by accident.
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

_ATTR_HEADERS = {
    "control id": "control_id",
    "attribute #": "attribute_no",
    "attribute name": "name",
    "attribute description": "description",
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


def parse_attribute_overrides(file_path: Path, known_control_ids: set[str]) -> dict[str, Any]:
    """Returns {attributes: {control_id: [{id,name,description}]},
    unknown_control_ids}. Row ORDER within a control is authoritative for
    attribute order/IDs — the 'Attribute #' column is read but not trusted,
    matching the export's own contract."""
    df = _read_sheet(file_path)
    header_map = _normalize_headers(df, _ATTR_HEADERS)
    fields = set(header_map.values())
    if "control_id" not in fields or "name" not in fields:
        raise ValueError("The sheet needs 'Control ID' and 'Attribute Name' columns.")

    by_control: dict[str, list[dict[str, str]]] = {}
    unknown: list[str] = []

    for _, row in df.iterrows():
        record: dict[str, str] = {}
        for col, field in header_map.items():
            record[field] = str(row.get(col, "")).strip()

        control_id = record.get("control_id", "")
        name = record.get("name", "")
        if not control_id or not name:
            continue
        if control_id not in known_control_ids:
            unknown.append(control_id)
            continue
        by_control.setdefault(control_id, []).append(
            {"name": name, "description": record.get("description", "")}
        )

    # IDs are positional strings, assigned from row order.
    attributes = {
        cid: [{"id": str(i), "name": a["name"], "description": a["description"]} for i, a in enumerate(rows, start=1)]
        for cid, rows in by_control.items()
    }
    return {"attributes": attributes, "unknown_control_ids": sorted(set(unknown))}
