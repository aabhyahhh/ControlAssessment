"""
Step 1 — RCM intake. The redesigned flow does NO risk analysis: the RCM only
has to carry a Control ID, and everything else is reconciled from the SOP in
step 2. So this module is now just a completeness view over the loaded
controls — no risk-level inference, no heatmap, no priority queue.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("engines.risk_scorer")

# Fields that make an RCM row "complete". Absence is reported, never inferred.
REQUIRED_FOR_COMPLETENESS = [
    "control_owner",
    "control_description",
    "control_frequency",
    "control_type",
    "process",
]


def compute_completeness(control: dict[str, Any]) -> float:
    present = sum(1 for f in REQUIRED_FOR_COMPLETENESS if str(control.get(f) or "").strip())
    return round(present / len(REQUIRED_FOR_COMPLETENESS), 4)


def missing_fields(control: dict[str, Any]) -> list[str]:
    return [f for f in REQUIRED_FOR_COMPLETENESS if not str(control.get(f) or "").strip()]


def build_rcm_analytics(controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Field-level completeness composition — the dynamic source for the Step
    1 visual. One entry per field in REQUIRED_FOR_COMPLETENESS (never
    hardcoded downstream): how many controls have it populated vs blank, and
    exactly which Control IDs are blank so the UI can drill straight to them.

    This reports population composition, not a quality score — there is no
    banding, no colour threshold computed here. That judgment (if any) is a
    rendering concern, and the brief is explicit that blank *optional* RCM
    fields are reconciliation scope for step 2, not a deficiency.
    """
    n = len(controls)
    fields: list[dict[str, Any]] = []
    for f in REQUIRED_FOR_COMPLETENESS:
        blank_ids = [c["control_id"] for c in controls if not str(c.get(f) or "").strip()]
        fields.append({
            "field": f,
            "populated": n - len(blank_ids),
            "blank": len(blank_ids),
            "blank_control_ids": blank_ids,
        })

    controls_with_blanks = sum(1 for c in controls if missing_fields(c))
    fields_requiring_reconciliation = [f["field"] for f in fields if f["blank"] > 0]

    return {
        "control_population": {"total": n},
        "rcm_completeness": {
            "fields": fields,
            "total_controls": n,
            "controls_with_blanks": controls_with_blanks,
            "fields_requiring_reconciliation": fields_requiring_reconciliation,
        },
    }


def score_controls(controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Step 1 result payload: control inventory + per-field completeness.
    `controls` are overlay-resolved control dicts."""
    n = len(controls)
    completeness_values = [compute_completeness(c) for c in controls]
    avg_completeness = round(sum(completeness_values) / n, 4) if n else 0.0

    missing_attrs = [
        {"control_id": c["control_id"], "missing_fields": missing_fields(c)}
        for c in controls
        if missing_fields(c)
    ]

    return {
        "stats": {
            "controls_in_racm": n,
            "racm_completeness_pct": avg_completeness,
        },
        "completeness_pct": avg_completeness,
        "missing_attributes": missing_attrs,
        "controls": [
            {
                "control_id": c["control_id"],
                "control_description": c.get("control_description") or "",
                "completeness_pct": compute_completeness(c),
                "missing_fields": missing_fields(c),
            }
            for c in controls
        ],
        "analytics": build_rcm_analytics(controls),
    }
