"""
Per-sample remediation ranking.

Every FAILED sample of an ineffective (or effective-with-exceptions) control
becomes its own remediation item, scored and ordered so the team knows what
to fix first. Two determinants, both already computed earlier in the run:

  1. The control's RISK LEVEL from Phase 1 — a failure on a Critical control
     matters more than the same failure on a Low one.
  2. Whether the control is COVERED BY THE SOP and aligned with it
     (Phase 3). A control the SOP describes is one the organisation has
     committed to operating a particular way, so a deviation there is a
     control breakdown rather than an undocumented practice. A *misaligned*
     control scores higher still: the SOP and the RCM disagree, so the
     failure may be a design problem, not just an execution one.

Ranking on the control's risk alone would order whole controls, not samples,
and give no way to separate two failures inside the same control — which is
exactly the case a remediation owner has to triage.
"""

from __future__ import annotations

from typing import Any

# Risk weights. The gaps are deliberately wide: a Critical failure should
# outrank any amount of SOP evidence on a Low-risk control.
_RISK_POINTS = {"critical": 50, "high": 38, "medium": 20, "low": 8}
_RISK_DEFAULT = 20

# SOP alignment contribution.
_ALIGNMENT_POINTS = {
    "misaligned": 22,  # SOP and RCM disagree — possible design defect
    "partial": 12,
    "aligned": 8,  # documented and agreed, so a real operating breakdown
}
_NO_SOP_COVERAGE = 0

# A control whose verdict is outright ineffective carries more urgency than
# one that merely had exceptions.
_VERDICT_POINTS = {"Not Effective": 18, "Effective with Exceptions": 6}

_BANDS = [(70, "P1"), (45, "P2"), (0, "P3")]


def _risk_points(risk_level: str | None) -> int:
    return _RISK_POINTS.get((risk_level or "").strip().lower(), _RISK_DEFAULT)


def _band(score: int) -> str:
    for threshold, label in _BANDS:
        if score >= threshold:
            return label
    return "P3"


def build_remediation_plan(
    control_results: list[dict[str, Any]],
    controls_by_id: dict[str, dict[str, Any]],
    alignment_by_control: dict[str, str],
    sop_covered_controls: set[str],
) -> list[dict[str, Any]]:
    """One entry per FAILED sample, highest priority first.

    `alignment_by_control` maps control_id -> "aligned"/"partial"/
    "misaligned" from Phase 3; `sop_covered_controls` is the set the SOP
    actually mentions. Both may be empty when Phase 3 hasn't run — the score
    then rests on risk and verdict alone rather than the function failing.
    """
    items: list[dict[str, Any]] = []

    for result in control_results:
        verdict = result.get("effectiveness_status") or ""
        if verdict in ("Effective", "Not Tested"):
            continue

        control_id = result.get("control_id", "")
        control = controls_by_id.get(control_id, {})
        risk_level = control.get("risk_level") or "Medium"
        alignment = alignment_by_control.get(control_id)
        in_sop = control_id in sop_covered_controls

        risk_pts = _risk_points(risk_level)
        align_pts = _ALIGNMENT_POINTS.get(alignment or "", _NO_SOP_COVERAGE) if in_sop else _NO_SOP_COVERAGE
        verdict_pts = _VERDICT_POINTS.get(verdict, 0)

        for sample in result.get("sample_results") or []:
            # NOT_EVALUATED samples are an infrastructure problem, not a
            # control deviation — remediating them means fixing the evidence,
            # which is a different workflow. Excluded here deliberately.
            if sample.get("result") != "FAIL":
                continue

            failed_attrs = [
                aid for aid, answer in (sample.get("attribute_results") or {}).items()
                if str(answer).strip().lower() == "no"
            ]
            score = risk_pts + align_pts + verdict_pts

            drivers = [f"{risk_level} risk control"]
            if in_sop and alignment:
                drivers.append(
                    "SOP misaligned with RCM" if alignment == "misaligned"
                    else "partially aligned to SOP" if alignment == "partial"
                    else "documented in the SOP"
                )
            else:
                drivers.append("not covered by the SOP")
            drivers.append(verdict.lower())

            items.append({
                "control_id": control_id,
                "sample_id": sample.get("sample_id", ""),
                "priority": _band(score),
                "score": score,
                "risk_level": risk_level,
                "sop_alignment": alignment if in_sop else None,
                "in_sop": in_sop,
                "verdict": verdict,
                "failed_attributes": failed_attrs,
                "why": ", ".join(drivers).capitalize() + ".",
                "remarks": (sample.get("remarks") or "").strip(),
            })

    # Highest score first; ties resolved by control then sample so the order
    # is stable across runs rather than depending on dict iteration.
    items.sort(key=lambda i: (-i["score"], i["control_id"], i["sample_id"]))
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return items
