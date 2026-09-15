"""
Step 2 — Adequacy Assessment.

Inputs are the SOPs and monthly workpapers uploaded as one folder-per-control
(plus any project-wide SOP). For each control this engine:

  1. Parses SOP text into discrete process steps.
  2. Reconciles the RCM row against the SOP + workpaper text — which RCM
     fields the documents corroborate, contradict, or don't mention. Because
     the redesigned RCM only requires a Control ID, this is where the rest of
     the control's shape ("owned by X, performed monthly, preventive") is
     actually established.
  3. Checks monthly workpaper coverage against the audit period — one
     workpaper per calendar month is expected; missing months are flagged.
  4. Judges design alignment (SOP vs RCM) and classifies deficiencies.
  5. Finds SOP steps with no matching control (whole-process coverage gaps).

Every LLM call is per-control and parallelized with isolated failures.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Callable

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.sop_adequacy_engine")

ALIGNMENT_FIELDS = ["control_description", "control_frequency", "control_owner", "control_type", "control_nature"]

# Fields the reconciliation tries to establish from the documents. Superset of
# ALIGNMENT_FIELDS because reconciliation also cares about risk context.
RECONCILE_FIELDS = [
    "control_description",
    "control_owner",
    "control_frequency",
    "control_type",
    "control_nature",
    "risk_description",
    "process",
]


def _get_llm_client():
    return get_llm_client()


# ═══════════════════════════════════════════════════════════════════════════
#  1. SOP ingestion — parse extracted text into discrete process steps
# ═══════════════════════════════════════════════════════════════════════════


def parse_sop_steps(extracted_text: str) -> list[dict[str, Any]]:
    """One LLM call parses the SOP body into {step_id, description,
    mentions_control_ids}. Falls back to a naive paragraph split if the LLM
    is unavailable/fails — never silently returns nothing."""
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
#  2. Per-control reconciliation — establish the RCM row from the documents
# ═══════════════════════════════════════════════════════════════════════════


def _relevant_doc_text(
    control: dict[str, Any], sop_steps: list[dict[str, Any]], control_docs_text: str
) -> tuple[str, bool]:
    """Returns (text, control_specific).

    `control_specific` is True only when the text is actually about THIS
    control — an explicit control-ID mention in the SOP, or a per-control
    SOP/workpaper. A generic word-overlap match against the whole SOP does
    NOT count: it's context for the LLM, not evidence the control is
    documented.
    """
    control_id = control["control_id"]
    explicit = [s for s in sop_steps if control_id in s.get("mentions_control_ids", [])]
    control_specific = bool(explicit) or bool(control_docs_text.strip())

    if explicit:
        step_text = "\n".join(s["description"] for s in explicit)
    else:
        control_text = (control.get("control_description") or "").lower()
        control_words = {w for w in re.findall(r"[a-z]{4,}", control_text)}
        if control_words:
            scored = []
            for s in sop_steps:
                step_words = set(re.findall(r"[a-z]{4,}", s["description"].lower()))
                overlap = len(control_words & step_words)
                if overlap > 0:
                    scored.append((overlap, s["description"]))
            scored.sort(key=lambda t: -t[0])
            step_text = "\n".join(desc for _, desc in scored[:4])
            if scored:
                control_specific = True  # a real word-overlap hit on a described control
        else:
            step_text = "\n".join(s["description"] for s in sop_steps[:4])

    parts = []
    if step_text.strip():
        parts.append("RELEVANT SOP STEPS:\n" + step_text)
    if control_docs_text.strip():
        parts.append("CONTROL DOCUMENTS (SOP / workpapers):\n" + control_docs_text[:6000])
    return "\n\n".join(parts), control_specific


def _reconcile_control(control: dict[str, Any], doc_text: str, control_specific: bool) -> dict[str, Any]:
    """Per-field: does the documentation support / contradict / not mention
    the RCM value? For a field blank in the RCM, the doc value the LLM reads
    is captured as `doc_value` so step 2 can surface what the RCM should say.

    `reconciliation_pct` is None when it can't be assessed (no LLM, or no
    control-specific text) — the gap engine treats None as "undetermined",
    not as a failure.
    """
    control_id = control["control_id"]
    rcm_fields = {f: (control.get(f) or "") for f in RECONCILE_FIELDS}

    if not doc_text.strip() or not control_specific:
        return {
            "control_id": control_id,
            "reconciliation_pct": 0.0 if not doc_text.strip() else None,
            "described_in_docs": False,
            "fields": {
                f: {"rcm_value": rcm_fields[f], "doc_value": "", "status": "absent"}
                for f in RECONCILE_FIELDS
            },
        }

    client, model = _get_llm_client()
    if client is None:
        return {
            "control_id": control_id,
            "reconciliation_pct": None,
            "described_in_docs": True,
            "fields": {
                f: {"rcm_value": rcm_fields[f], "doc_value": "", "status": "undetermined"}
                for f in RECONCILE_FIELDS
            },
        }

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit control-documentation assistant. You are given a control's RCM "
                        "(Risk Control Matrix) field values — some may be blank — and the relevant SOP / "
                        "workpaper text for that control. For EACH field decide:\n"
                        "  'supported'  — the documents state a value consistent with the RCM value;\n"
                        "  'contradicted' — the documents clearly state a different value;\n"
                        "  'absent' — the documents don't address this field.\n"
                        "When the RCM value is blank, still read the value the documents imply and put it "
                        "in doc_value; status is 'absent' only if the documents say nothing about it, "
                        "otherwise 'supported' with the doc value.\n"
                        "Also return described_in_docs: true if the documents describe this control at all.\n"
                        'Return ONLY JSON: {"described_in_docs": true, "fields": {"control_owner": '
                        '{"status": "supported|contradicted|absent", "doc_value": "..."}, ...}}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"CONTROL ID: {control_id}\n\n"
                        f"RCM FIELDS:\n{json.dumps(rcm_fields)}\n\n{doc_text[:6000]}"
                    ),
                },
            ],
            max_completion_tokens=3000,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="sop_adequacy_engine._reconcile_control")
        raw_fields = parsed.get("fields") or {}
        fields: dict[str, Any] = {}
        supported = 0
        assessable = 0  # fields the docs actually spoke to, or the RCM has a value for
        for f in RECONCILE_FIELDS:
            entry = raw_fields.get(f) or {}
            status = entry.get("status") if entry.get("status") in ("supported", "contradicted", "absent") else "absent"
            doc_value = str(entry.get("doc_value") or "").strip()
            fields[f] = {"rcm_value": rcm_fields[f], "doc_value": doc_value, "status": status}
            if rcm_fields[f] or status != "absent":
                assessable += 1
            if status == "supported":
                supported += 1
        return {
            "control_id": control_id,
            "reconciliation_pct": round(supported / assessable, 4) if assessable else None,
            "described_in_docs": bool(parsed.get("described_in_docs", True)),
            "fields": fields,
        }
    except Exception as e:
        logger.warning("Reconciliation failed for %s: %s", control_id, e)
        return {
            "control_id": control_id,
            "reconciliation_pct": None,
            "described_in_docs": True,
            "fields": {
                f: {"rcm_value": rcm_fields[f], "doc_value": "", "status": "undetermined"}
                for f in RECONCILE_FIELDS
            },
        }


# ═══════════════════════════════════════════════════════════════════════════
#  3. Monthly workpaper coverage vs the audit period
# ═══════════════════════════════════════════════════════════════════════════


def _months_in_period(start: date, end: date) -> list[str]:
    """Every calendar month the audit period touches, as 'YYYY-MM'."""
    months: list[str] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def build_workpaper_coverage(
    controls: list[dict[str, Any]],
    workpaper_months_by_control: dict[str, list[str]],
    audit_period_start: date,
    audit_period_end: date,
) -> list[dict[str, Any]]:
    """One row per control: which audit-period months have a workpaper and
    which are missing. `workpaper_months_by_control` maps control_id -> list
    of 'YYYY-MM' strings (a month with an un-dateable workpaper contributes
    nothing here and is reported via workpapers_without_month)."""
    expected = _months_in_period(audit_period_start, audit_period_end)
    rows: list[dict[str, Any]] = []
    for c in controls:
        cid = c["control_id"]
        present = sorted(set(m for m in workpaper_months_by_control.get(cid, []) if m in expected))
        missing = [m for m in expected if m not in present]
        rows.append({
            "control_id": cid,
            "months_expected": expected,
            "months_present": present,
            "months_missing": missing,
            "coverage_pct": round(len(present) / len(expected), 4) if expected else 0.0,
        })
    return rows


# ═══════════════════════════════════════════════════════════════════════════
#  4. Per-control design-field alignment (SOP vs RCM)
# ═══════════════════════════════════════════════════════════════════════════


def _alignment_for_control(control: dict[str, Any], doc_text: str, control_specific: bool) -> dict[str, Any]:
    control_id = control["control_id"]
    # No documentation about this control at all — that's a real finding.
    if not doc_text.strip() or not control_specific:
        return {"control_id": control_id, "alignment": "misaligned", "mismatches": [
            {"field": "control_description", "rcm_value": control.get("control_description") or "", "sop_value": "(not described in the SOP or workpapers)"},
        ]}

    client, model = _get_llm_client()
    if client is None:
        # Can't judge alignment without the LLM — say so rather than guess.
        return {"control_id": control_id, "alignment": "not_assessed", "mismatches": []}

    rcm_fields = {f: (control.get(f) or "") for f in ALIGNMENT_FIELDS}
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit control-design assistant. Compare a control's RCM field values "
                        "against the relevant SOP / workpaper text for the same process. Judge whether the "
                        "documentation supports each RCM field value. "
                        "alignment: 'aligned' if all fields the documents address match, 'partial' if some "
                        "match and others don't or aren't addressed, 'misaligned' if the documents clearly "
                        "contradict the RCM on one or more fields. Only report a mismatch for a field when "
                        "the documents state something different — do not invent a value for a field the "
                        "documents simply don't mention. "
                        'Return ONLY JSON: {"alignment": "aligned|partial|misaligned", '
                        '"mismatches": [{"field": "control_frequency", "sop_value": "..."}]}'
                    ),
                },
                {
                    "role": "user",
                    "content": f"RCM FIELDS:\n{json.dumps(rcm_fields)}\n\n{doc_text[:3500]}",
                },
            ],
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
        return {"control_id": control_id, "alignment": "not_assessed", "mismatches": []}


# ═══════════════════════════════════════════════════════════════════════════
#  5. Whole-process coverage gaps — SOP steps with no matching control
# ═══════════════════════════════════════════════════════════════════════════


def find_coverage_gaps(controls: list[dict[str, Any]], sop_steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
#  6. Deficiency classification
# ═══════════════════════════════════════════════════════════════════════════


# Each design dimension maps to the one RCM field that documents it. No
# numeric weight or score is attached to a dimension — its state per control
# is one of four real, objectively-determined categories (see
# `_dimension_state`), and portfolio-level analytics count those categories
# rather than average an invented number.
_DIMENSION_FIELD = {
    "ownership": "control_owner",
    "frequency": "control_frequency",
    "automation": "control_nature",
    "exception_management": "control_type",
    "evidence_design": "control_description",
}


def _dimension_state(control: dict[str, Any], mismatches: list[dict[str, Any]], alignment: str) -> dict[str, str]:
    """Per dimension, one of:
      'contradicted'   — the SOP/workpapers state something different from the RCM field
      'undocumented'   — the RCM field is blank, OR the documents don't affirmatively
                         corroborate a populated field (see the 'partial' note below)
      'not_assessed'   — no LLM verdict could be reached for this control at all
      'supported'      — the documents corroborate a populated field
    Derived entirely from `control_alignment`'s own mismatches list — no
    numeric scoring, no averaging.

    The prompt behind `alignment` allows 'partial' to mean "some fields match
    and others AREN'T ADDRESSED" while instructing the LLM to report a
    mismatch only for a field the documents actively contradict — so a
    'partial' verdict can carry an empty `mismatches` list. Treating every
    non-mismatched, populated field as 'supported' in that case would let a
    control the LLM itself judged only partially aligned come out as fully
    "Adequate" with zero weak dimensions. So under 'partial' a populated
    field with no reported mismatch is 'undocumented' (not affirmatively
    corroborated), not 'supported' — the same distinction 'aligned' fields
    always got.
    """
    mismatched_fields = {m["field"] for m in mismatches}
    states: dict[str, str] = {}
    for dim, field in _DIMENSION_FIELD.items():
        has_value = bool((control.get(field) or "").strip())
        if alignment == "not_assessed":
            states[dim] = "not_assessed"
        elif field in mismatched_fields:
            states[dim] = "contradicted"
        elif not has_value:
            states[dim] = "undocumented"
        elif alignment == "partial":
            states[dim] = "undocumented"
        else:
            states[dim] = "supported"
    return states


def _verdict_for_states(states: dict[str, str]) -> str:
    """Rules-based band over real states — not a threshold on an invented
    number. Any contradiction is disqualifying (the SOP disagrees with the
    RCM); undocumented dimensions without contradiction are a lesser gap;
    an all-not_assessed control has no verdict to give."""
    values = states.values()
    if all(v == "not_assessed" for v in values):
        return "Not assessed"
    if any(v == "contradicted" for v in values):
        return "Inadequate"
    if any(v == "undocumented" for v in values):
        return "Partially adequate"
    return "Adequate"


def classify_deficiencies(control_alignment: list[dict[str, Any]], controls_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    deficiencies = []
    for row in control_alignment:
        control = controls_by_id.get(row["control_id"], {})
        states = _dimension_state(control, row["mismatches"], row["alignment"])
        weak_dimensions = [dim for dim, state in states.items() if state in ("contradicted", "undocumented")]
        deficiencies.append({
            "control_id": row["control_id"],
            "verdict": _verdict_for_states(states),
            "weak_dimensions": weak_dimensions,
            "dimension_states": states,
        })
    return deficiencies


def build_design_profile(deficiencies: list[dict[str, Any]]) -> dict[str, Any]:
    """Portfolio-level counts per design dimension — the dynamic source for
    the re-grounded radar. Each dimension's axis value (computed by the
    frontend) is `supported / (total - not_assessed)`: the share of the
    ASSESSABLE population the documentation actually corroborates. This is a
    real ratio over a real population, never an invented score."""
    dims = list(_DIMENSION_FIELD.keys())
    counts = {
        dim: {"supported": 0, "contradicted": 0, "undocumented": 0, "not_assessed": 0}
        for dim in dims
    }
    for d in deficiencies:
        states = d.get("dimension_states") or {}
        for dim in dims:
            state = states.get(dim, "not_assessed")
            counts[dim][state] += 1

    total = len(deficiencies)
    any_assessed = any(
        counts[dim]["not_assessed"] < total for dim in dims
    ) if total else False

    return {
        "dimensions": [{"dimension": dim, **counts[dim]} for dim in dims],
        "total_controls": total,
        "assessed": any_assessed,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  7. Derived analytics — reconciliation exceptions + workpaper rollup
# ═══════════════════════════════════════════════════════════════════════════


def build_reconciliation_summary(reconciliation: list[dict[str, Any]]) -> dict[str, Any]:
    """Portfolio view of RCM<->documentation exceptions, over ASSESSABLE
    cells only: a cell is assessable when the RCM has a value for that field
    or the documents said something about it (the same `assessable` gate the
    per-control reconciliation_pct uses). Cells from controls that could not
    be assessed at all (no LLM) are excluded from the percentages, not
    counted as a failure."""
    counts = {"supported": 0, "contradicted": 0, "undocumented": 0, "undetermined": 0}
    contradictions_by_field: dict[str, list[str]] = {}
    exceptions_by_control: dict[str, dict[str, int]] = {}
    # Per-field breakdown: same four buckets as the portfolio totals above,
    # but kept separately for each RCM field so the UI can render one bar per
    # field ("what the documents establish") instead of only a portfolio-wide
    # rollup. Field keys come entirely from whatever the reconciliation rows
    # actually carry — never a hardcoded field list.
    by_field: dict[str, dict[str, Any]] = {}

    def _field_bucket(field: str) -> dict[str, Any]:
        return by_field.setdefault(
            field,
            {
                "supported": 0, "contradicted": 0, "undocumented": 0, "undetermined": 0,
                "control_ids": {"supported": [], "contradicted": [], "undocumented": [], "undetermined": []},
            },
        )

    for r in reconciliation:
        cid = r["control_id"]
        for field, cell in (r.get("fields") or {}).items():
            status = cell.get("status", "absent")
            bucket = _field_bucket(field)
            if status == "undetermined":
                counts["undetermined"] += 1
                bucket["undetermined"] += 1
                bucket["control_ids"]["undetermined"].append(cid)
            elif status == "contradicted":
                counts["contradicted"] += 1
                contradictions_by_field.setdefault(field, []).append(cid)
                exceptions_by_control.setdefault(cid, {"contradicted": 0, "undetermined": 0})
                exceptions_by_control[cid]["contradicted"] += 1
                bucket["contradicted"] += 1
                bucket["control_ids"]["contradicted"].append(cid)
            elif status == "absent":
                # Whether the RCM field itself was blank or populated, the
                # documents didn't address it either way — undocumented
                # scope, not a disagreement to bucket as "supported" or
                # count against the reconciled percentage.
                counts["undocumented"] += 1
                bucket["undocumented"] += 1
                bucket["control_ids"]["undocumented"].append(cid)
            else:  # supported
                counts["supported"] += 1
                bucket["supported"] += 1
                bucket["control_ids"]["supported"].append(cid)

        undetermined_here = sum(
            1 for cell in (r.get("fields") or {}).values() if cell.get("status") == "undetermined"
        )
        if undetermined_here:
            exceptions_by_control.setdefault(cid, {"contradicted": 0, "undetermined": 0})
            exceptions_by_control[cid]["undetermined"] = undetermined_here

    total_cells = sum(counts.values())
    pct = (lambda k: round(counts[k] / total_cells, 4) if total_cells else None)

    most_contradicted_fields = sorted(
        (
            {"field": f, "control_count": len(set(ids))}
            for f, ids in contradictions_by_field.items()
        ),
        key=lambda x: -x["control_count"],
    )
    controls_by_exception_count = sorted(
        (
            {"control_id": cid, "contradicted": v["contradicted"], "undetermined": v["undetermined"]}
            for cid, v in exceptions_by_control.items()
            if v["contradicted"] or v["undetermined"]
        ),
        key=lambda x: (-x["contradicted"], -x["undetermined"]),
    )

    # Field order follows RECONCILE_FIELDS (the order the engine itself
    # walks fields in) for any field that appears there, then any other
    # field the documents happened to address, appended after — so the row
    # order is stable across runs without hardcoding which fields exist.
    field_order = {f: i for i, f in enumerate(RECONCILE_FIELDS)}
    by_field_list = [
        {
            "field": field,
            "supported": b["supported"],
            "contradicted": b["contradicted"],
            "undocumented": b["undocumented"],
            "undetermined": b["undetermined"],
            "control_ids": b["control_ids"],
        }
        for field, b in sorted(by_field.items(), key=lambda kv: field_order.get(kv[0], len(field_order)))
    ]

    return {
        "cell_counts": counts,
        "pct_supported": pct("supported"),
        "pct_contradicted": pct("contradicted"),
        "pct_undocumented": pct("undocumented"),
        "pct_undetermined": pct("undetermined"),
        "most_contradicted_fields": most_contradicted_fields,
        "controls_by_exception_count": controls_by_exception_count,
        "by_field": by_field_list,
    }


def build_workpaper_analytics(workpaper_coverage: list[dict[str, Any]]) -> dict[str, Any]:
    """Portfolio rollup over the per-control monthly coverage rows. A missing
    month means documentation coverage is incomplete for that control-month —
    it is never read here (or anywhere downstream) as the control having
    failed."""
    if not workpaper_coverage:
        return {
            "controls_complete": 0,
            "controls_with_missing": 0,
            "total_missing_control_months": 0,
            "overall_coverage_pct": None,
            "months_most_missing": [],
        }

    controls_complete = sum(1 for w in workpaper_coverage if not w["months_missing"])
    controls_with_missing = sum(1 for w in workpaper_coverage if w["months_missing"])
    total_missing = sum(len(w["months_missing"]) for w in workpaper_coverage)
    total_present = sum(len(w["months_present"]) for w in workpaper_coverage)
    total_expected = total_present + total_missing

    missing_by_month: dict[str, int] = {}
    for w in workpaper_coverage:
        for m in w["months_missing"]:
            missing_by_month[m] = missing_by_month.get(m, 0) + 1
    months_most_missing = sorted(
        ({"month": m, "missing_control_count": n} for m, n in missing_by_month.items()),
        key=lambda x: (-x["missing_control_count"], x["month"]),
    )

    return {
        "controls_complete": controls_complete,
        "controls_with_missing": controls_with_missing,
        "total_missing_control_months": total_missing,
        "overall_coverage_pct": round(total_present / total_expected, 4) if total_expected else None,
        "months_most_missing": months_most_missing,
    }


def build_adequacy_analytics(
    reconciliation: list[dict[str, Any]],
    workpaper_coverage: list[dict[str, Any]],
    deficiencies: list[dict[str, Any]],
    counts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "adequacy_summary": {
            "adequate": counts["adequate_count"],
            "partially_adequate": counts["partially_adequate_count"],
            "inadequate": counts["inadequate_count"],
            "not_in_docs": counts["unreconciled_count"],
            "total": len(deficiencies),
        },
        "reconciliation_summary": build_reconciliation_summary(reconciliation),
        "workpaper_coverage": build_workpaper_analytics(workpaper_coverage),
        "design_profile": build_design_profile(deficiencies),
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Top-level entry point
# ═══════════════════════════════════════════════════════════════════════════


def run_sop_adequacy_assessment(
    controls: list[dict[str, Any]],
    project_sop_text: str,
    docs_text_by_control: dict[str, str],
    workpaper_months_by_control: dict[str, list[str]],
    audit_period_start: date,
    audit_period_end: date,
    on_progress: Callable[[str, int, int, str | None], None] | None = None,
) -> dict[str, Any]:
    """`project_sop_text` is any SOP uploaded without a control_id (whole
    process). `docs_text_by_control` is the concatenated text of every
    SOP/workpaper filed under that control. `workpaper_months_by_control`
    maps control_id -> ['YYYY-MM', ...] for its dated workpapers."""
    sop_steps = parse_sop_steps(project_sop_text) if project_sop_text.strip() else []

    controls_by_id = {c["control_id"]: c for c in controls}
    total = len(controls)

    # Per-control doc text = the control's own docs, plus a small slice of the
    # whole-process SOP for context. `control_specific` says whether the text
    # is genuinely about this control (explicit mention / per-control doc /
    # real word-overlap) vs a generic SOP fallback.
    doc_text_for = {
        c["control_id"]: _relevant_doc_text(c, sop_steps, docs_text_by_control.get(c["control_id"], ""))
        for c in controls
    }

    reconciliation: list[dict[str, Any]] = []
    control_alignment: list[dict[str, Any]] = []
    done = 0

    def _report(cid: str, activity: str) -> None:
        if not on_progress:
            return
        try:
            on_progress(cid, done, total * 2, activity)
        except Exception:
            logger.debug("adequacy progress callback failed", exc_info=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        # Reconciliation and design-alignment calls for every control are
        # submitted together and run concurrently on the same worker pool —
        # they are not two sequential phases, so the activity label says
        # "and" rather than implying reconciliation finishes before
        # alignment starts. Announced before any result lands: with an LLM
        # in the loop the first completion can be tens of seconds away, and
        # a bar with no update at all reads as hung, not busy.
        if controls:
            _report(controls[0]["control_id"], "Reconciling against SOPs and checking design alignment")
        recon_futs = {
            pool.submit(_reconcile_control, c, *doc_text_for[c["control_id"]]): c["control_id"]
            for c in controls
        }
        align_futs = {
            pool.submit(_alignment_for_control, c, *doc_text_for[c["control_id"]]): c["control_id"]
            for c in controls
        }
        for future in as_completed(list(recon_futs)):
            cid = recon_futs[future]
            try:
                reconciliation.append(future.result())
            except Exception as e:
                logger.warning("Reconciliation task raised for %s: %s", cid, e)
            done += 1
            _report(cid, "Reconciled against SOPs and workpapers")
        for future in as_completed(list(align_futs)):
            cid = align_futs[future]
            try:
                control_alignment.append(future.result())
            except Exception as e:
                logger.warning("Alignment task raised for %s: %s", cid, e)
                control_alignment.append({"control_id": cid, "alignment": "not_assessed", "mismatches": []})
            done += 1
            _report(cid, "Checked design alignment")

    order = {c["control_id"]: i for i, c in enumerate(controls)}
    reconciliation.sort(key=lambda r: order.get(r["control_id"], 0))
    control_alignment.sort(key=lambda r: order.get(r["control_id"], 0))

    coverage_gaps = find_coverage_gaps(controls, sop_steps)
    deficiencies = classify_deficiencies(control_alignment, controls_by_id)
    workpaper_coverage = build_workpaper_coverage(
        controls, workpaper_months_by_control, audit_period_start, audit_period_end
    )

    adequate_count = sum(1 for d in deficiencies if d["verdict"] == "Adequate")
    partially_adequate_count = sum(1 for d in deficiencies if d["verdict"] == "Partially adequate")
    inadequate_count = sum(1 for d in deficiencies if d["verdict"] == "Inadequate")
    workpaper_gap_count = sum(1 for w in workpaper_coverage if w["months_missing"])
    unreconciled_count = sum(1 for r in reconciliation if not r["described_in_docs"])

    counts = {
        "adequate_count": adequate_count,
        "partially_adequate_count": partially_adequate_count,
        "inadequate_count": inadequate_count,
        "uncovered_sop_steps": len(coverage_gaps),
        "workpaper_gap_count": workpaper_gap_count,
        "unreconciled_count": unreconciled_count,
    }

    return {
        "reconciliation": reconciliation,
        "control_alignment": control_alignment,
        "coverage_gaps": coverage_gaps,
        "deficiencies": deficiencies,
        "workpaper_coverage": workpaper_coverage,
        "counts": counts,
        "analytics": build_adequacy_analytics(reconciliation, workpaper_coverage, deficiencies, counts),
    }
