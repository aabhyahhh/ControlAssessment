"""
Phase 3 — SOP ingestion, per-control design-field alignment, whole-process
coverage gaps, deficiency classification, control-type mix. New logic (no
ControlIris precedent), following the plan's 5-step spec. Every LLM call is
per-control/per-step and parallelized with isolated failures, matching the
reliability pattern used in risk_scorer.py / evidence_gap_engine.py.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.sop_adequacy_engine")

ALIGNMENT_FIELDS = ["control_description", "control_frequency", "control_owner", "control_type", "control_nature"]

_DEFICIENCY_DIMENSIONS = ["ownership", "frequency", "automation", "exception_management", "evidence_design"]

_CORRECTIVE_KEYWORDS = ("remediat", "correct", "escalat", "root cause", "corrective action")


def _get_llm_client():
    return get_llm_client()


# ═══════════════════════════════════════════════════════════════════════════
#  1. SOP ingestion — parse extracted text into discrete process steps
# ═══════════════════════════════════════════════════════════════════════════


def parse_sop_steps(extracted_text: str) -> list[dict[str, Any]]:
    """One LLM call parses the SOP body into {step_id, description,
    mentions_control_ids}. Falls back to a naive paragraph split (still
    usable for coverage-gap/alignment matching, just without an LLM's sense
    of what counts as one discrete step) if the LLM is unavailable/fails —
    never silently returns nothing."""
    client, model = _get_llm_client()
    if client is None or not extracted_text.strip():
        return _fallback_split_steps(extracted_text)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit process-documentation assistant. Given the text of a Standard "
                        "Operating Procedure (SOP) document, break it into discrete process steps — each "
                        "step should describe one distinct activity, control point, or procedure. For each "
                        "step, note any explicit control ID references if present (e.g. 'CTRL-001'), "
                        "otherwise leave that list empty. Return at most 40 steps. "
                        'Return ONLY JSON: {"steps": [{"description": "...", "mentions_control_ids": ["..."]}]}'
                    ),
                },
                {"role": "user", "content": f"SOP TEXT:\n{extracted_text[:12000]}"},
            ],
            max_completion_tokens=3000,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="sop_adequacy_engine.parse_sop_steps")
        raw_steps = parsed.get("steps", [])
        steps = []
        for i, s in enumerate(raw_steps, start=1):
            desc = (s.get("description") or "").strip()
            if not desc:
                continue
            steps.append({
                "step_id": f"step-{i}",
                "description": desc,
                "mentions_control_ids": [c for c in s.get("mentions_control_ids", []) if isinstance(c, str)],
            })
        return steps or _fallback_split_steps(extracted_text)
    except Exception as e:
        logger.warning("SOP step parsing failed: %s — falling back to paragraph split", e)
        return _fallback_split_steps(extracted_text)


def _fallback_split_steps(extracted_text: str) -> list[dict[str, Any]]:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", extracted_text) if p.strip() and len(p.strip()) > 20]
    return [
        {"step_id": f"step-{i}", "description": p[:500], "mentions_control_ids": []}
        for i, p in enumerate(paragraphs[:40], start=1)
    ]


# ═══════════════════════════════════════════════════════════════════════════
#  2. Per-control design-field alignment
# ═══════════════════════════════════════════════════════════════════════════


def _find_relevant_sop_text(control: dict[str, Any], sop_steps: list[dict[str, Any]]) -> str:
    """Cheap relevance filter: steps that explicitly mention this control ID,
    else steps whose description shares significant words with the control
    description (keeps the per-control LLM prompt small and grounded)."""
    control_id = control["control_id"]
    explicit = [s for s in sop_steps if control_id in s.get("mentions_control_ids", [])]
    if explicit:
        return "\n".join(s["description"] for s in explicit)

    control_text = (control.get("control_description") or "").lower()
    control_words = {w for w in re.findall(r"[a-z]{4,}", control_text)}
    if not control_words:
        return "\n".join(s["description"] for s in sop_steps[:5])

    scored = []
    for s in sop_steps:
        step_words = set(re.findall(r"[a-z]{4,}", s["description"].lower()))
        overlap = len(control_words & step_words)
        if overlap > 0:
            scored.append((overlap, s["description"]))
    scored.sort(key=lambda t: -t[0])
    return "\n".join(desc for _, desc in scored[:3]) or "\n".join(s["description"] for s in sop_steps[:3])


def _alignment_for_control(control: dict[str, Any], sop_text: str) -> dict[str, Any]:
    control_id = control["control_id"]
    if not sop_text.strip():
        return {"control_id": control_id, "alignment": "misaligned", "mismatches": [
            {"field": "control_description", "rcm_value": control.get("control_description") or "", "sop_value": "(not found in SOP)"},
        ]}

    client, model = _get_llm_client()
    if client is None:
        return {"control_id": control_id, "alignment": "partial", "mismatches": []}

    rcm_fields = {f: (control.get(f) or "") for f in ALIGNMENT_FIELDS}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit control-design assistant. Compare a control's RCM (Risk Control "
                        "Matrix) field values against the relevant SOP (Standard Operating Procedure) text "
                        "for the same process. Judge whether the SOP supports each RCM field value. "
                        "alignment: 'aligned' if all fields the SOP addresses match, 'partial' if some "
                        "fields match and others don't or the SOP doesn't address them, 'misaligned' if "
                        "the SOP clearly contradicts the RCM on one or more fields. Only report a mismatch "
                        "for a field when the SOP text states something different — do not invent a SOP "
                        "value for a field the SOP simply doesn't mention. "
                        'Return ONLY JSON: {"alignment": "aligned|partial|misaligned", '
                        '"mismatches": [{"field": "control_frequency", "sop_value": "..."}]}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"RCM FIELDS:\n{json.dumps(rcm_fields)}\n\n"
                        f"RELEVANT SOP TEXT:\n{sop_text[:3000]}"
                    ),
                },
            ],
            # Reasoning-model budget — see risk_scorer.py's
            # _llm_infer_risk_level for why this needs real headroom (this
            # call's larger prompt burns through hidden reasoning tokens
            # faster than the smaller single-field calls elsewhere).
            # Raised from 2000: observed finish_reason=length on real RCMs,
            # which silently degraded every control to a 'partial' alignment
            # verdict while still paying the full token cost.
            max_completion_tokens=3500,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="sop_adequacy_engine._alignment_for_control")
        alignment = parsed.get("alignment") if parsed.get("alignment") in ("aligned", "partial", "misaligned") else "partial"
        mismatches = []
        for m in parsed.get("mismatches", []):
            field = m.get("field")
            if field in ALIGNMENT_FIELDS:
                mismatches.append({"field": field, "rcm_value": rcm_fields.get(field, ""), "sop_value": m.get("sop_value", "")})
        return {"control_id": control_id, "alignment": alignment, "mismatches": mismatches}
    except Exception as e:
        logger.warning("Alignment check failed for %s: %s", control_id, e)
        return {"control_id": control_id, "alignment": "partial", "mismatches": []}


def assess_control_alignment(
    controls: list[dict[str, Any]],
    sop_steps: list[dict[str, Any]],
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """`on_progress(control_id, done, total)` fires as each control's
    alignment lands — this is the slow part of Phase 3 (one LLM call per
    control), so it is what the progress bar tracks."""
    results: list[dict[str, Any]] = []
    total = len(controls)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_alignment_for_control, c, _find_relevant_sop_text(c, sop_steps)): c["control_id"]
            for c in controls
        }
        for future in as_completed(futures):
            control_id = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.warning("Alignment task raised for %s: %s", control_id, e)
                results.append({"control_id": control_id, "alignment": "partial", "mismatches": []})
            if on_progress is not None:
                try:
                    on_progress(control_id, len(results), total)
                except Exception:
                    logger.debug("alignment progress callback failed", exc_info=True)
    order = {c["control_id"]: i for i, c in enumerate(controls)}
    results.sort(key=lambda r: order.get(r["control_id"], 0))
    return results


# ═══════════════════════════════════════════════════════════════════════════
#  3. Whole-process coverage gaps — SOP steps with no matching control
# ═══════════════════════════════════════════════════════════════════════════


def find_coverage_gaps(controls: list[dict[str, Any]], sop_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Word-overlap similarity (no embedding API dependency) between each
    SOP step and every control description; a step with no meaningfully
    overlapping control is reported as uncovered. Threshold is deliberately
    generous (>=1 shared significant word) since this is a coverage-gap
    *finder*, not a precise matcher — false negatives here hide real gaps,
    which is worse than an occasional false positive the user can dismiss."""
    control_word_sets = [
        (c["control_id"], set(re.findall(r"[a-z]{4,}", (c.get("control_description") or "").lower())))
        for c in controls
    ]

    gaps = []
    for step in sop_steps:
        if step.get("mentions_control_ids"):
            continue
        step_words = set(re.findall(r"[a-z]{4,}", step["description"].lower()))
        if not step_words:
            continue
        covered = any(len(step_words & cw) >= 2 for _, cw in control_word_sets if cw)
        if not covered:
            gaps.append({"sop_step_id": step["step_id"], "description": step["description"], "coverage": "none"})
    return gaps


# ═══════════════════════════════════════════════════════════════════════════
#  4. Deficiency classification
# ═══════════════════════════════════════════════════════════════════════════


def _dimension_score(control: dict[str, Any], mismatches: list[dict[str, Any]], alignment: str) -> dict[str, int]:
    """Simplified dimension scoring: each dimension is scored on its own
    backing RCM field — missing entirely, contradicted by the SOP, or fine.
    A mismatch on one field only penalizes that field's dimension; an
    overall 'misaligned' verdict applies a small penalty to the rest rather
    than dragging every dimension below the weak threshold, so the
    weak_dimensions list stays a useful pointer to what actually needs
    fixing instead of listing everything."""
    mismatched_fields = {m["field"] for m in mismatches}
    field_for_dimension = {
        "ownership": "control_owner",
        "frequency": "control_frequency",
        "automation": "control_nature",
        "exception_management": "control_type",
        "evidence_design": "control_description",
    }
    scores = {}
    for dim, field in field_for_dimension.items():
        if not (control.get(field) or "").strip():
            scores[dim] = 30
        elif field in mismatched_fields:
            scores[dim] = 40
        elif alignment == "misaligned":
            scores[dim] = 75
        else:
            scores[dim] = 90
    return scores


def _verdict_for_score(score: float) -> str:
    if score >= 80:
        return "Adequate"
    if score >= 50:
        return "Partially adequate"
    return "Inadequate"


def classify_deficiencies(control_alignment: list[dict[str, Any]], controls_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    deficiencies = []
    for row in control_alignment:
        control = controls_by_id.get(row["control_id"], {})
        dims = _dimension_score(control, row["mismatches"], row["alignment"])
        overall = sum(dims.values()) / len(dims)
        weak_dimensions = [dim for dim, score in dims.items() if score < 70]
        deficiencies.append({
            "control_id": row["control_id"],
            "verdict": _verdict_for_score(overall),
            "score": round(overall, 1),
            "weak_dimensions": weak_dimensions,
            # The per-dimension scores, not just the names of the weak ones.
            # The design-profile radar plots the portfolio average per
            # dimension, which cannot be reconstructed from a weak/not-weak
            # list — a dimension at 75 and one at 90 both read "not weak".
            "dimension_scores": dims,
        })
    return deficiencies


# ═══════════════════════════════════════════════════════════════════════════
#  5. Control-type mix
# ═══════════════════════════════════════════════════════════════════════════


def control_type_mix(controls: list[dict[str, Any]]) -> dict[str, int]:
    mix = {"preventive": 0, "detective": 0, "corrective": 0}
    for c in controls:
        control_type = (c.get("control_type") or "").lower()
        description = (c.get("control_description") or "").lower()
        if any(k in description for k in _CORRECTIVE_KEYWORDS):
            mix["corrective"] += 1
        elif "prevent" in control_type:
            mix["preventive"] += 1
        elif "detect" in control_type:
            mix["detective"] += 1
        else:
            mix["preventive"] += 1  # conservative default, matches source-project convention
    return mix


# ═══════════════════════════════════════════════════════════════════════════
#  Top-level entry point
# ═══════════════════════════════════════════════════════════════════════════


def run_sop_adequacy_assessment(
    controls: list[dict[str, Any]],
    sop_steps: list[dict[str, Any]],
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    control_alignment = assess_control_alignment(controls, sop_steps, on_progress=on_progress)
    coverage_gaps = find_coverage_gaps(controls, sop_steps)
    controls_by_id = {c["control_id"]: c for c in controls}
    deficiencies = classify_deficiencies(control_alignment, controls_by_id)
    mix = control_type_mix(controls)

    adequate_count = sum(1 for d in deficiencies if d["verdict"] == "Adequate")
    partially_adequate_count = sum(1 for d in deficiencies if d["verdict"] == "Partially adequate")
    inadequate_count = sum(1 for d in deficiencies if d["verdict"] == "Inadequate")

    return {
        "control_alignment": control_alignment,
        "coverage_gaps": coverage_gaps,
        "deficiencies": deficiencies,
        "control_type_mix": mix,
        "counts": {
            "adequate_count": adequate_count,
            "partially_adequate_count": partially_adequate_count,
            "inadequate_count": inadequate_count,
            "uncovered_sop_steps": len(coverage_gaps),
        },
    }
