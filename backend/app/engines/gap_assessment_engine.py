"""
Step 4 — Gap Assessment.

No test-of-effectiveness workpaper. This step aggregates what the first three
steps found into a single per-control gap picture and a portfolio rollup,
which the export renders as an Excel summary:

  received vs expected  — evidence documents matched vs the generated list
  where the gap lies     — RCM fields, SOP alignment, missing workpaper months,
                           missing/undeclared evidence
  severity               — critical | high | medium | low, per control
  summary                — one line against RCM + SOP + evidence

Severity is rules-based (the flow does no risk-level analysis):
  critical — no evidence at all AND (not described in SOP OR no workpapers)
  high     — evidence largely missing, or SOP contradicts the RCM
  medium   — partial evidence / partial reconciliation / some months missing
  low      — only cosmetic RCM-field gaps, everything else in order
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("engines.gap_assessment_engine")

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}


def _worst(*severities: str | None) -> str | None:
    present = [s for s in severities if s is not None]
    if not present:
        return None
    return min(present, key=lambda s: _SEVERITY_RANK.get(s, 4))


def _evidence_severity(row: dict[str, Any] | None) -> str | None:
    return (row or {}).get("severity")


def _reconciliation_severity(recon: dict[str, Any] | None) -> str | None:
    if not recon:
        return "high"  # step 2 produced nothing for this control at all
    if not recon.get("described_in_docs"):
        return "high"
    contradicted = sum(1 for f in (recon.get("fields") or {}).values() if f.get("status") == "contradicted")
    if contradicted:
        return "high"
    pct = recon.get("reconciliation_pct")
    if pct is None:
        return None  # could not be assessed (no LLM) — not a gap
    if pct >= 0.85:
        return None
    if pct >= 0.5:
        return "low"
    return "medium"


def _alignment_severity(alignment: dict[str, Any] | None) -> str | None:
    a = (alignment or {}).get("alignment")
    if a == "misaligned":
        return "high"
    if a == "partial":
        return "medium"
    return None  # 'aligned', 'not_assessed', or absent


def _workpaper_severity(coverage: dict[str, Any] | None) -> str | None:
    if not coverage:
        return None
    missing = coverage.get("months_missing") or []
    expected = coverage.get("months_expected") or []
    if not expected:
        return None
    if not missing:
        return None
    ratio_missing = len(missing) / len(expected)
    if ratio_missing >= 0.5:
        return "high"
    if ratio_missing >= 0.25:
        return "medium"
    return "low"


def _build_coverage_funnel(
    controls: list[dict[str, Any]],
    recon_by_control: dict[str, Any],
    workpaper_by_control: dict[str, Any],
    evidence_by_control: dict[str, Any],
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Real population narrowing across four gates. `count` at each stage is
    a STRICT subset of `count` at the stage before it — only a control that
    is CONFIRMED to have passed every prior gate is eligible to be counted
    here, which is what keeps the counts monotonically non-increasing and
    genuinely comparable (never independently computed totals plotted as if
    they narrowed each other).

    A control that could not be assessed at gate N (no data — e.g. no LLM
    available) is excluded from gate N's `count`, same as a control that
    genuinely failed the gate — the funnel cannot claim a control "passed"
    something it never actually evaluated. What it does NOT do is hide that
    exclusion: `unassessed` at each stage is the count of controls that were
    still eligible going into this gate (i.e. passed every earlier one) but
    couldn't be evaluated here, so a reviewer can tell "excluded because it
    doesn't qualify" apart from "excluded because we don't know" — without
    that undetermined population ever being allowed to inflate a later
    stage's confirmed count.
    """
    total = len(controls)
    in_scope = {c["control_id"] for c in controls}

    def _gate(candidates: set[str], assess: Any) -> tuple[set[str], set[str]]:
        """Splits `candidates` into (passed, unassessed) using `assess(cid)`,
        which returns True/False/None (None = cannot be determined). A
        control that fails outright is in neither set — it genuinely didn't
        pass, which is different from not being assessable."""
        passed: set[str] = set()
        unassessed: set[str] = set()
        for cid in candidates:
            result = assess(cid)
            if result is None:
                unassessed.add(cid)
            elif result:
                passed.add(cid)
        return passed, unassessed

    def _described(cid: str) -> bool | None:
        recon = recon_by_control.get(cid)
        if recon is None:
            return None
        return bool(recon.get("described_in_docs"))

    def _workpapers_complete(cid: str) -> bool | None:
        wp = workpaper_by_control.get(cid)
        if wp is None or not wp.get("months_expected"):
            return None
        return not wp.get("months_missing")

    def _evidence_complete(cid: str) -> bool | None:
        ev = evidence_by_control.get(cid)
        if ev is None or not ev.get("required"):
            return None
        return not ev.get("missing") and not ev.get("declared_not_uploaded")

    described, described_unassessed = _gate(in_scope, _described)
    workpapers_complete, workpapers_unassessed = _gate(described, _workpapers_complete)
    evidence_complete, evidence_unassessed = _gate(workpapers_complete, _evidence_complete)

    fully_covered = {r["control_id"] for r in rows if r["severity"] is None} & evidence_complete

    return [
        {"stage": "Controls in scope", "count": total, "unassessed": 0},
        {"stage": "Described in SOP/workpapers", "count": len(described), "unassessed": len(described_unassessed)},
        {"stage": "Monthly workpapers complete", "count": len(workpapers_complete), "unassessed": len(workpapers_unassessed)},
        {"stage": "Required evidence complete", "count": len(evidence_complete), "unassessed": len(evidence_unassessed)},
        {"stage": "Fully covered — no gap", "count": len(fully_covered), "unassessed": 0},
    ]


# Each entry in a row's `gap_areas` list is free text with a row-specific
# count baked in (e.g. "3 evidence document(s) missing", "RCM fields blank:
# control_owner, process") — so areas are grouped by matching a stable
# prefix rather than the exact string, and the label shown here is the
# category name, not the original sentence.
_GAP_AREA_CATEGORIES: list[tuple[str, str]] = [
    ("evidence document(s) missing", "Evidence documents missing"),
    ("RCM fields blank", "RCM fields blank"),
    ("SOP contradicts the RCM", "SOP contradicts the RCM"),
    ("SOP only partially supports the RCM", "SOP only partially supports the RCM"),
    ("control not described in the SOP/workpapers", "Control not described in the SOP/workpapers"),
    ("of RCM fields reconciled to the documentation", "Low reconciliation to the documentation"),
    ("workpaper month(s) missing", "Workpaper months missing"),
]


def _build_gap_area_concentration(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How many controls carry each kind of gap, across the whole assessed
    population — tells a reviewer where to look first. Reuses `gap_areas`
    (already built, per control, from the exact same branches this function
    would otherwise have to re-derive) as the single source of truth, rather
    than re-deriving categories independently from `align`/`recon`/etc — so
    this can never drift out of sync with what `build_gap_assessment` above
    actually decided the gap areas are."""
    buckets: dict[str, list[str]] = {}
    for r in rows:
        cid = r["control_id"]
        for area_text in r.get("gap_areas") or []:
            label = next((lbl for marker, lbl in _GAP_AREA_CATEGORIES if marker in area_text), area_text)
            buckets.setdefault(label, [])
            if cid not in buckets[label]:
                buckets[label].append(cid)

    concentration = [
        {"area": label, "control_count": len(control_ids), "control_ids": control_ids}
        for label, control_ids in buckets.items()
    ]
    concentration.sort(key=lambda x: -x["control_count"])
    return concentration


def build_gap_analytics(rows: list[dict[str, Any]], funnel: list[dict[str, Any]]) -> dict[str, Any]:
    severity_distribution = {"critical": 0, "high": 0, "medium": 0, "low": 0, "none": 0}
    for r in rows:
        severity_distribution[r["severity"] or "none"] += 1

    return {
        "severity_distribution": severity_distribution,
        "coverage_funnel": funnel,
        "gap_area_concentration": _build_gap_area_concentration(rows),
    }


def build_gap_assessment(
    controls: list[dict[str, Any]],
    step1_result: dict[str, Any],
    step2_result: dict[str, Any],
    step3_result: dict[str, Any],
) -> dict[str, Any]:
    completeness_by_control = {
        r["control_id"]: r for r in (step1_result.get("controls") or [])
    }
    recon_by_control = {r["control_id"]: r for r in (step2_result.get("reconciliation") or [])}
    align_by_control = {r["control_id"]: r for r in (step2_result.get("control_alignment") or [])}
    deficiency_by_control = {d["control_id"]: d for d in (step2_result.get("deficiencies") or [])}
    workpaper_by_control = {w["control_id"]: w for w in (step2_result.get("workpaper_coverage") or [])}
    evidence_by_control = {r["control_id"]: r for r in (step3_result.get("per_control") or [])}

    rows: list[dict[str, Any]] = []
    for c in controls:
        cid = c["control_id"]
        comp = completeness_by_control.get(cid, {})
        recon = recon_by_control.get(cid)
        align = align_by_control.get(cid)
        deficiency = deficiency_by_control.get(cid, {})
        workpaper = workpaper_by_control.get(cid)
        evidence = evidence_by_control.get(cid, {})

        expected = evidence.get("required", [])
        received = evidence.get("matched", [])
        missing_docs = evidence.get("missing", []) + evidence.get("declared_not_uploaded", [])
        rcm_field_gaps = comp.get("missing_fields", [])
        months_missing = (workpaper or {}).get("months_missing", [])

        ev_sev = _evidence_severity(evidence)
        recon_sev = _reconciliation_severity(recon)
        align_sev = _alignment_severity(align)
        wp_sev = _workpaper_severity(workpaper)

        severity = _worst(ev_sev, recon_sev, align_sev, wp_sev)
        # Nothing wrong anywhere except an incomplete RCM row -> low.
        if severity is None and rcm_field_gaps:
            severity = "low"

        gap_areas: list[str] = []
        if missing_docs:
            gap_areas.append(f"{len(missing_docs)} evidence document(s) missing")
        if rcm_field_gaps:
            gap_areas.append(f"RCM fields blank: {', '.join(rcm_field_gaps)}")
        if align and align.get("alignment") == "misaligned":
            gap_areas.append("SOP contradicts the RCM")
        elif align and align.get("alignment") == "partial":
            gap_areas.append("SOP only partially supports the RCM")
        recon_pct = (recon or {}).get("reconciliation_pct")
        if not recon or not recon.get("described_in_docs"):
            gap_areas.append("control not described in the SOP/workpapers")
        elif recon_pct is not None and recon_pct < 0.5:
            gap_areas.append(
                f"only {round(recon_pct * 100)}% of RCM fields reconciled to the documentation"
            )
        if months_missing:
            gap_areas.append(f"{len(months_missing)} workpaper month(s) missing")

        summary = _summarize(cid, expected, received, missing_docs, align, recon, months_missing, deficiency)

        rows.append({
            "control_id": cid,
            "control_description": c.get("control_description") or "",
            "severity": severity,
            "expected_documents": expected,
            "received_documents": received,
            "missing_documents": missing_docs,
            "rcm_field_gaps": rcm_field_gaps,
            "sop_alignment": (align or {}).get("alignment"),
            "reconciliation_pct": (recon or {}).get("reconciliation_pct"),
            "design_verdict": deficiency.get("verdict"),
            "workpaper_months_missing": months_missing,
            "gap_areas": gap_areas,
            "summary": summary,
        })

    order = {c["control_id"]: i for i, c in enumerate(controls)}
    rows.sort(key=lambda r: (_SEVERITY_RANK.get(r["severity"], 4), order.get(r["control_id"], 0)))

    rollup = {"critical": 0, "high": 0, "medium": 0, "low": 0, "none": 0}
    for r in rows:
        rollup[r["severity"] or "none"] += 1

    fully_covered = sum(1 for r in rows if r["severity"] is None)
    partial = sum(1 for r in rows if r["severity"] in ("low", "medium"))
    serious = sum(1 for r in rows if r["severity"] in ("critical", "high"))

    funnel = _build_coverage_funnel(controls, recon_by_control, workpaper_by_control, evidence_by_control, rows)

    return {
        "stats": {
            "controls_assessed": len(rows),
            "severity_rollup": rollup,
            "fully_covered": fully_covered,
            "partial": partial,
            "serious": serious,
        },
        "rows": rows,
        "analytics": build_gap_analytics(rows, funnel),
    }


def _summarize(
    control_id: str,
    expected: list[str],
    received: list[str],
    missing_docs: list[str],
    align: dict[str, Any] | None,
    recon: dict[str, Any] | None,
    months_missing: list[str],
    deficiency: dict[str, Any],
) -> str:
    parts: list[str] = []
    if expected:
        parts.append(f"{len(received)}/{len(expected)} expected evidence documents received")
    else:
        parts.append("no evidence checklist could be generated")

    if recon is not None:
        recon_pct = recon.get("reconciliation_pct")
        if not recon.get("described_in_docs"):
            parts.append("the control is not described in the SOP/workpapers")
        elif recon_pct is None:
            parts.append("RCM-vs-documentation reconciliation could not be assessed (no LLM available)")
        else:
            parts.append(f"{round(recon_pct * 100)}% of RCM fields reconciled to the documentation")

    a = (align or {}).get("alignment")
    if a == "misaligned":
        parts.append("the SOP contradicts the RCM on at least one field")
    elif a == "aligned":
        parts.append("design aligns with the SOP")
    elif a == "not_assessed":
        parts.append("design alignment not assessed")

    if months_missing:
        parts.append(f"{len(months_missing)} monthly workpaper(s) missing")

    verdict = deficiency.get("verdict")
    # "Not assessed" is already covered by the alignment clause above (both
    # derive from the same not-assessed alignment) — appending it again would
    # read as "design alignment not assessed; design assessed not assessed".
    if verdict and verdict != "Not assessed":
        parts.append(f"design assessed {verdict.lower()}")

    return f"{control_id}: " + "; ".join(parts) + "."
