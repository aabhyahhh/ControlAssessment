"""
Phase 1 — RACM completeness scoring + risk classification + heatmap +
priority queue. New logic (no ControlIris precedent for the heatmap/queue
shape), but the risk-level inference cascade (computed -> keyword -> LLM ->
default) follows the same reliability pattern as ControlIris's
infer_risk_level.py: isolate per-control LLM failures, never silently guess.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.risk_scorer")

REQUIRED_FOR_COMPLETENESS = [
    "control_owner",
    "control_description",
    "risk_level",
    "control_frequency",
    "control_type",
]

LIKELIHOOD_BANDS = ["Low", "Medium", "High"]
IMPACT_BANDS = ["Low", "Medium", "High"]

KEYWORD_RISK_MAP: dict[str, str] = {
    "material misstatement": "High",
    "fraud": "High",
    "regulatory": "High",
    "non-compliance": "High",
    "reconciliation": "Medium",
    "review": "Medium",
    "approval": "Medium",
    "monitoring": "Low",
    "informational": "Low",
}

_RISK_LEVEL_NORMALIZE = {
    "critical": "High", "high": "High", "significant": "High",
    "medium": "Medium", "moderate": "Medium",
    "low": "Low", "minor": "Low",
}


def _normalize_risk_level(raw: str | None) -> str | None:
    if not raw:
        return None
    key = str(raw).strip().lower()
    return _RISK_LEVEL_NORMALIZE.get(key)


def _keyword_infer(text: str) -> str | None:
    lowered = text.lower()
    for keyword, level in KEYWORD_RISK_MAP.items():
        if keyword in lowered:
            return level
    return None


def _llm_infer_risk_level(control_description: str, risk_description: str) -> dict[str, Any]:
    # Shared, connection-pooled client — this runs once per control in a
    # thread pool, so a per-call client would re-handshake every time.
    client, deployment = get_llm_client()
    if client is None:
        return {"value": "Medium", "source": "Default (LLM unavailable)", "confidence": "Low",
                "reasoning": "No Azure OpenAI credentials configured."}

    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit risk-assessment assistant. Given a control description "
                        "and risk description, classify the inherent risk level as exactly one of "
                        "Low, Medium, or High, and give a one-sentence reason. "
                        'Return ONLY JSON: {"risk_level": "Low|Medium|High", "reasoning": "..."}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"Control Description: {control_description}\nRisk Description: {risk_description}",
                },
            ],
            # Reasoning models spend part of this budget on hidden reasoning
            # tokens before any visible output — too low a budget here
            # silently truncates to empty content, which then falls through
            # to the "Medium/Default" branch below rather than raising, so
            # get this wrong and the LLM path looks like it's "working"
            # while actually just returning the fallback every time.
            max_completion_tokens=1500,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="risk_scorer._llm_infer_risk_level")
        level = _normalize_risk_level(parsed.get("risk_level")) or "Medium"
        return {"value": level, "source": "LLM", "confidence": "Medium", "reasoning": parsed.get("reasoning", "")}
    except Exception as e:
        logger.warning("LLM risk-level inference failed: %s", e)
        return {"value": "Medium", "source": "Default (LLM unavailable)", "confidence": "Low",
                "reasoning": f"LLM inference failed: {e}"}


def infer_risk_levels(controls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Returns {control_id: {value, source, confidence, reasoning}} only for
    controls missing risk_level. 3-tier cascade: direct value -> keyword ->
    LLM (parallelized, isolated failures)."""
    results: dict[str, dict[str, Any]] = {}
    needs_llm: list[dict[str, Any]] = []

    for c in controls:
        existing = _normalize_risk_level(c.get("risk_level"))
        if existing:
            continue

        text = f"{c.get('control_description') or ''} {c.get('risk_description') or ''}"
        keyword_hit = _keyword_infer(text) if text.strip() else None
        if keyword_hit:
            results[c["control_id"]] = {
                "value": keyword_hit, "source": "Keyword", "confidence": "Medium",
                "reasoning": "Matched keyword risk map.",
            }
        else:
            needs_llm.append(c)

    if needs_llm:
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                pool.submit(_llm_infer_risk_level, c.get("control_description") or "", c.get("risk_description") or ""): c
                for c in needs_llm
            }
            for future in as_completed(futures):
                c = futures[future]
                try:
                    results[c["control_id"]] = future.result()
                except Exception as e:
                    results[c["control_id"]] = {
                        "value": "Medium", "source": "Default (LLM unavailable)", "confidence": "Low",
                        "reasoning": f"Inference raised: {e}",
                    }

    return results


def compute_completeness(control: dict[str, Any]) -> float:
    present = sum(1 for f in REQUIRED_FOR_COMPLETENESS if str(control.get(f) or "").strip())
    return round(present / len(REQUIRED_FOR_COMPLETENESS), 4)


def missing_fields(control: dict[str, Any]) -> list[str]:
    return [f for f in REQUIRED_FOR_COMPLETENESS if not str(control.get(f) or "").strip()]


def _impact_band_from_risk_level(risk_level: str) -> str:
    return risk_level if risk_level in IMPACT_BANDS else "Medium"


def build_heatmap(controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Buckets controls into a likelihood x impact grid. Likelihood is
    approximated from risk_level directly (no separate probability/impact
    columns assumed in the generalized schema); impact mirrors risk_level.
    This keeps the heatmap meaningful even for RCMs with only a single
    risk_level column, while still reading distinct risk_probability /
    risk_impact passthrough columns when present."""
    cells: dict[tuple[str, str], dict[str, Any]] = {}
    for likelihood in LIKELIHOOD_BANDS:
        for impact in IMPACT_BANDS:
            cells[(likelihood, impact)] = {"likelihood": likelihood, "impact": impact, "count": 0, "control_ids": []}

    for c in controls:
        risk_level = _normalize_risk_level(c.get("risk_level")) or "Medium"
        raw = c.get("raw_row") or {}
        likelihood = _normalize_risk_level(raw.get("risk_probability")) or risk_level
        impact = _normalize_risk_level(raw.get("risk_impact")) or risk_level
        key = (likelihood, _impact_band_from_risk_level(impact))
        cells[key]["count"] += 1
        cells[key]["control_ids"].append(c["control_id"])

    return {
        "axes": {"likelihood": LIKELIHOOD_BANDS, "impact": IMPACT_BANDS},
        "cells": list(cells.values()),
    }


def build_priority_queue(controls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _rank_order = {"High": 0, "Medium": 1, "Low": 2}
    scored = []
    for c in controls:
        risk_level = _normalize_risk_level(c.get("risk_level")) or "Medium"
        completeness = compute_completeness(c)
        scored.append({
            "control_id": c["control_id"],
            "risk_rating": risk_level,
            "completeness_pct": completeness,
            "description": c.get("control_description") or "",
        })

    scored.sort(key=lambda r: (_rank_order.get(r["risk_rating"], 1), r["completeness_pct"]))
    for i, row in enumerate(scored, start=1):
        row["rank"] = i
    return scored


def build_exposure_metric(controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Groups controls by keyword-derived risk theme for the stat-tile
    exposure metric (a lightweight tag, not a full taxonomy)."""
    theme_counts: dict[str, int] = {}
    for c in controls:
        text = f"{c.get('control_description') or ''} {c.get('risk_description') or ''}".lower()
        matched = False
        for keyword in KEYWORD_RISK_MAP:
            if keyword in text:
                theme_counts[keyword] = theme_counts.get(keyword, 0) + 1
                matched = True
                break
        if not matched:
            theme_counts["other"] = theme_counts.get("other", 0) + 1

    top_theme = max(theme_counts.items(), key=lambda kv: kv[1]) if theme_counts else ("none", 0)
    return {"themes": theme_counts, "top_theme": top_theme[0], "top_theme_count": top_theme[1]}


def score_controls(controls: list[dict[str, Any]]) -> dict[str, Any]:
    """Top-level entry point: given normalized+overlaid control dicts
    (must include risk_level already resolved — see infer_risk_levels for
    the pending-approval path), compute the full Phase 1 result payload."""
    n = len(controls)
    completeness_values = [compute_completeness(c) for c in controls]
    avg_completeness = round(sum(completeness_values) / n, 4) if n else 0.0

    high_risk_count = sum(1 for c in controls if (_normalize_risk_level(c.get("risk_level")) or "Medium") == "High")

    missing_attrs = [
        {"control_id": c["control_id"], "missing_fields": missing_fields(c)}
        for c in controls
        if missing_fields(c)
    ]

    return {
        "stats": {
            "controls_in_racm": n,
            "racm_completeness_pct": avg_completeness,
            "high_risk_count": high_risk_count,
            "exposure_metric": build_exposure_metric(controls),
        },
        "completeness_pct": avg_completeness,
        "missing_attributes": missing_attrs,
        "heatmap": build_heatmap(controls),
        "priority_queue": build_priority_queue(controls),
    }
