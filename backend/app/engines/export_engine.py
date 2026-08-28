"""
Excel exports — the per-control attribute workbook (layout fixed by
ATTRIBUTE_GENERATION_ENGINE_SPEC.md Section 6) and the multi-sheet final
report covering all four phases.

The final report is universe-preserving: every control in the RCM appears
exactly once on the summary sheet, including controls that were never
tested. A control missing from an audit deliverable is worse than one
marked untested, so untested controls carry an explicit reason rather than
being filtered out.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger("engines.export_engine")

_HEADER_FILL = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
_BODY_ALIGN = Alignment(vertical="top", wrap_text=True)
_THIN = Side(style="thin", color="B4C6E7")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _write_sheet(ws, headers: list[str], widths: list[int], rows: list[list[Any]]) -> None:
    for col, (header, width) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = _HEADER_ALIGN
        cell.border = _BORDER
        ws.column_dimensions[get_column_letter(col)].width = width

    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            cell = ws.cell(row=r, column=c, value=value)
            cell.alignment = _BODY_ALIGN
            cell.border = _BORDER
    ws.freeze_panes = "A2"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def build_attributes_workbook(schemas: list[dict[str, Any]], dest_dir: Path) -> Path:
    """Layout is fixed by the spec: one sheet named "Attributes", one row per
    ATTRIBUTE (not per control), exact column order and widths."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Attributes"

    rows: list[list[Any]] = []
    for schema in sorted(schemas, key=lambda s: s["control_id"]):
        for i, attr in enumerate(schema.get("attributes") or [], start=1):
            rows.append([schema["control_id"], i, attr.get("name", ""), attr.get("description", "")])

    _write_sheet(
        ws,
        ["Control ID", "Attribute #", "Attribute Name", "Attribute Description"],
        [16, 12, 35, 60],
        rows,
    )

    control_ids = sorted(s["control_id"] for s in schemas)
    if len(control_ids) <= 5:
        id_part = "_".join(control_ids) or "no_controls"
    else:
        id_part = "_".join(control_ids[:3]) + f"_and_{len(control_ids) - 3}_more"
    safe_id_part = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in id_part)[:80]

    dest = dest_dir / f"Editable_Attributes_{safe_id_part}_{_timestamp()}.xlsx"
    wb.save(dest)
    return dest


def build_phase_workbook(phase: int, controls: list[dict[str, Any]], result: dict[str, Any], dest_dir: Path) -> Path:
    """One workbook per phase, in the same shape the user can edit and
    re-upload as an override. Column A is always Control ID so the
    round-trip has a stable key."""
    wb = Workbook()
    ws = wb.active

    if phase == 1:
        ws.title = "Phase 1 - Risk"
        risk_by_control = {c["control_id"]: (c.get("risk_level") or "") for c in controls}
        missing = {m["control_id"]: ", ".join(m["missing_fields"]) for m in (result.get("missing_attributes") or [])}
        rows = [
            [
                r["control_id"], r["rank"], r["risk_rating"],
                f"{round(r['completeness_pct'] * 100)}%",
                missing.get(r["control_id"], ""), r["description"],
            ]
            for r in (result.get("priority_queue") or [])
        ] or [[c["control_id"], "", risk_by_control.get(c["control_id"], ""), "", "", c.get("control_description") or ""] for c in controls]
        _write_sheet(
            ws,
            ["Control ID", "Rank", "Risk Level", "Completeness", "Missing Fields", "Control Description"],
            [16, 8, 14, 14, 30, 60],
            rows,
        )
    elif phase == 2:
        ws.title = "Phase 2 - Evidence"
        required = result.get("required_documents") or {}
        missing_docs = {m["control_id"]: ", ".join(m["missing"]) for m in (result.get("missing_documents") or [])}
        gaps = {g["control_id"]: g for g in (result.get("escalated_gaps") or [])}
        _write_sheet(
            ws,
            ["Control ID", "Evidence Score", "Band", "Severity", "Expected Documents", "Missing Documents"],
            [16, 14, 12, 20, 55, 55],
            [
                [
                    e["control_id"], e["score"], e["band"],
                    (gaps.get(e["control_id"]) or {}).get("severity", ""),
                    ", ".join(required.get(e["control_id"], [])),
                    missing_docs.get(e["control_id"], ""),
                ]
                for e in (result.get("evidence_scores") or [])
            ],
        )
    elif phase == 3:
        ws.title = "Phase 3 - Adequacy"
        alignment = {a["control_id"]: a for a in (result.get("control_alignment") or [])}
        timeline = {t["control_id"]: t for t in (result.get("timeline_sufficiency") or [])}
        _write_sheet(
            ws,
            ["Control ID", "SOP Alignment", "Mismatches", "Design Verdict", "Weak Dimensions",
             "Timeline Status", "Timeline Flags", "Evidence Date Range"],
            [16, 16, 50, 20, 28, 16, 26, 26],
            [
                [
                    d["control_id"],
                    (alignment.get(d["control_id"]) or {}).get("alignment", ""),
                    "; ".join(
                        f"{m['field']}: RCM='{m['rcm_value']}' vs SOP='{m['sop_value']}'"
                        for m in (alignment.get(d["control_id"]) or {}).get("mismatches", [])
                    ),
                    d.get("verdict", ""), ", ".join(d.get("weak_dimensions") or []),
                    (timeline.get(d["control_id"]) or {}).get("status", ""),
                    ", ".join((timeline.get(d["control_id"]) or {}).get("flags") or []),
                    _date_range(timeline.get(d["control_id"])),
                ]
                for d in (result.get("deficiencies") or [])
            ],
        )
        if result.get("coverage_gaps"):
            _write_sheet(
                wb.create_sheet("SOP Gaps"),
                ["SOP Step", "Description", "Coverage"],
                [14, 90, 14],
                [[g["sop_step_id"], g["description"], g["coverage"]] for g in result["coverage_gaps"]],
            )
    else:
        ws.title = "Phase 4 - Summary"
        _write_sheet(
            ws,
            ["Control ID", "Frequency", "Samples", "Fails", "Deviation Rate", "Verdict", "Deficiency"],
            [16, 16, 12, 10, 16, 26, 24],
            [
                [s["control_id"], s["frequency"], s["sample_size"], s["fails"],
                 f"{round(s['deviation_rate'] * 100)}%", s["verdict"], s.get("deficiency_type") or ""]
                for s in (result.get("sampling_results") or [])
            ],
        )
        sample_rows = []
        for r in (result.get("control_results") or []):
            for s in r.get("sample_results") or []:
                sample_rows.append([
                    r["control_id"], s["sample_id"], s["result"],
                    "; ".join(f"{k}={v}" for k, v in (s.get("attribute_results") or {}).items()),
                    s.get("remarks", ""),
                ])
        _write_sheet(
            wb.create_sheet("Samples"),
            ["Control ID", "Sample", "Result", "Attribute Results", "Remarks"],
            [16, 16, 12, 40, 70],
            sample_rows,
        )
        if result.get("format_issues"):
            _write_sheet(
                wb.create_sheet("Untestable"),
                ["Control ID", "Detected Mode", "Reason"],
                [16, 18, 80],
                [[f["control_id"], f["detected_mode"], f["message"]] for f in result["format_issues"]],
            )

    dest = dest_dir / f"Phase{phase}_{ws.title.replace(' ', '_').replace('-', '')}_{_timestamp()}.xlsx"
    wb.save(dest)
    return dest


def build_rcm_workbook(controls: list[dict[str, Any]], dest_dir: Path) -> Path:
    """The working RCM as it stands after normalization and any overrides —
    editable and re-uploadable to correct field values."""
    wb = Workbook()
    ws = wb.active
    ws.title = "RCM"
    fields = [
        ("control_id", "Control ID"), ("control_description", "Control Description"),
        ("risk_description", "Risk Description"), ("risk_level", "Risk Level"),
        ("control_type", "Control Type"), ("control_nature", "Control Nature"),
        ("control_frequency", "Control Frequency"), ("control_owner", "Control Owner"),
        ("process", "Process"),
    ]
    _write_sheet(
        ws,
        [label for _, label in fields],
        [16, 55, 45, 12, 16, 16, 18, 20, 20],
        [[c.get(key) or "" for key, _ in fields] for c in sorted(controls, key=lambda x: x["control_id"])],
    )
    dest = dest_dir / f"RCM_Working_Copy_{_timestamp()}.xlsx"
    wb.save(dest)
    return dest


def build_final_report(
    project: dict[str, Any],
    controls: list[dict[str, Any]],
    phase_results: dict[int, dict[str, Any]],
    attribute_schemas: list[dict[str, Any]],
    dest_dir: Path,
) -> Path:
    """Multi-sheet workbook: control universe summary + one sheet per phase."""
    wb = Workbook()

    p1 = phase_results.get(1) or {}
    p2 = phase_results.get(2) or {}
    p3 = phase_results.get(3) or {}
    p4 = phase_results.get(4) or {}

    # ── Sheet 1: control universe (every control exactly once) ────────
    risk_by_control = {c["control_id"]: (c.get("risk_level") or "") for c in controls}
    evidence_score = {e["control_id"]: e["score"] for e in (p2.get("evidence_scores") or [])}
    adequacy = {d["control_id"]: d for d in (p3.get("deficiencies") or [])}
    timeline = {t["control_id"]: t for t in (p3.get("timeline_sufficiency") or [])}
    testing = {r["control_id"]: r for r in (p4.get("control_results") or [])}
    format_issue = {f["control_id"]: f for f in (p4.get("format_issues") or [])}

    universe_rows = []
    for c in sorted(controls, key=lambda x: x["control_id"]):
        cid = c["control_id"]
        test = testing.get(cid)
        if test:
            verdict = test["effectiveness_status"]
            detail = f"{test['failed_samples']}/{test['total_samples']} sample(s) failed"
        elif cid in format_issue:
            verdict = "Not tested"
            detail = format_issue[cid]["message"]
        else:
            verdict = "Not tested"
            detail = "No testing result recorded for this control."

        universe_rows.append([
            cid,
            c.get("control_description") or "",
            c.get("process") or "",
            risk_by_control.get(cid, ""),
            c.get("control_frequency") or "",
            c.get("control_owner") or "",
            evidence_score.get(cid, ""),
            (adequacy.get(cid) or {}).get("verdict", ""),
            (timeline.get(cid) or {}).get("status", ""),
            verdict,
            (test or {}).get("deficiency_type") or "",
            detail,
        ])

    ws = wb.active
    ws.title = "Control Universe"
    _write_sheet(
        ws,
        ["Control ID", "Control Description", "Process", "Risk Level", "Frequency", "Owner",
         "Evidence Score", "Design Adequacy", "Timeline", "Effectiveness", "Deficiency", "Detail"],
        [16, 50, 18, 12, 14, 18, 14, 18, 14, 22, 22, 48],
        universe_rows,
    )

    # ── Sheet 2: Phase 1 risk prioritization ──────────────────────────
    _write_sheet(
        wb.create_sheet("Phase 1 - Risk"),
        ["Rank", "Control ID", "Risk Rating", "Completeness", "Description"],
        [8, 16, 14, 14, 60],
        [
            [r["rank"], r["control_id"], r["risk_rating"], f"{round(r['completeness_pct'] * 100)}%", r["description"]]
            for r in (p1.get("priority_queue") or [])
        ],
    )

    # ── Sheet 3: Phase 2 evidence gaps ────────────────────────────────
    missing_by_control = {m["control_id"]: ", ".join(m["missing"]) for m in (p2.get("missing_documents") or [])}
    gap_by_control = {g["control_id"]: g for g in (p2.get("escalated_gaps") or [])}
    _write_sheet(
        wb.create_sheet("Phase 2 - Evidence"),
        ["Control ID", "Evidence Score", "Band", "Escalated Severity", "Missing Documents"],
        [16, 14, 12, 20, 70],
        [
            [
                e["control_id"], e["score"], e["band"],
                (gap_by_control.get(e["control_id"]) or {}).get("severity", ""),
                missing_by_control.get(e["control_id"], ""),
            ]
            for e in (p2.get("evidence_scores") or [])
        ],
    )

    # ── Sheet 4: Phase 3 adequacy + timeline ──────────────────────────
    alignment = {a["control_id"]: a for a in (p3.get("control_alignment") or [])}
    _write_sheet(
        wb.create_sheet("Phase 3 - Adequacy"),
        ["Control ID", "SOP Alignment", "Mismatches", "Design Verdict", "Weak Dimensions",
         "Timeline Status", "Timeline Flags", "Evidence Date Range"],
        [16, 16, 50, 20, 28, 16, 26, 26],
        [
            [
                d["control_id"],
                (alignment.get(d["control_id"]) or {}).get("alignment", ""),
                "; ".join(
                    f"{m['field']}: RCM='{m['rcm_value']}' vs SOP='{m['sop_value']}'"
                    for m in (alignment.get(d["control_id"]) or {}).get("mismatches", [])
                ),
                d.get("verdict", ""),
                ", ".join(d.get("weak_dimensions") or []),
                (timeline.get(d["control_id"]) or {}).get("status", ""),
                ", ".join((timeline.get(d["control_id"]) or {}).get("flags") or []),
                _date_range(timeline.get(d["control_id"])),
            ]
            for d in (p3.get("deficiencies") or [])
        ],
    )

    if p3.get("coverage_gaps"):
        _write_sheet(
            wb.create_sheet("Phase 3 - SOP Gaps"),
            ["SOP Step", "Description", "Coverage"],
            [14, 90, 14],
            [[g["sop_step_id"], g["description"], g["coverage"]] for g in p3["coverage_gaps"]],
        )

    # ── Sheet 5: Phase 4 testing, one row per SAMPLE ──────────────────
    sample_rows = []
    for r in (p4.get("control_results") or []):
        for s in r.get("sample_results") or []:
            sample_rows.append([
                r["control_id"], s["sample_id"], s["result"],
                "; ".join(f"{k}={v}" for k, v in (s.get("attribute_results") or {}).items()),
                s.get("remarks", ""),
            ])
    _write_sheet(
        wb.create_sheet("Phase 4 - Samples"),
        ["Control ID", "Sample", "Result", "Attribute Results", "Remarks"],
        [16, 16, 12, 40, 70],
        sample_rows,
    )

    _write_sheet(
        wb.create_sheet("Phase 4 - Summary"),
        ["Control ID", "Frequency", "Samples", "Fails", "Deviation Rate", "Verdict", "Deficiency"],
        [16, 16, 12, 10, 16, 26, 24],
        [
            [s["control_id"], s["frequency"], s["sample_size"], s["fails"],
             f"{round(s['deviation_rate'] * 100)}%", s["verdict"], s.get("deficiency_type") or ""]
            for s in (p4.get("sampling_results") or [])
        ],
    )

    # ── Remediation plan ──────────────────────────────────────────────
    # One row per failed sample in priority order — the action list a
    # remediation owner works from, so it belongs in the filed workpaper
    # rather than only on screen.
    remediation = p4.get("remediation_priorities") or []
    if remediation:
        _write_sheet(
            wb.create_sheet("Remediation Plan"),
            ["Rank", "Priority", "Control ID", "Sample", "Risk Level", "SOP Alignment",
             "Testing Verdict", "Failed Attributes", "Why This Ranking", "Remarks"],
            [8, 10, 16, 14, 13, 16, 26, 20, 52, 52],
            [
                [
                    r.get("rank", ""), r.get("priority", ""), r.get("control_id", ""),
                    r.get("sample_id", ""), r.get("risk_level", ""),
                    (r.get("sop_alignment") or ("covered" if r.get("in_sop") else "not in SOP")),
                    r.get("verdict", ""), ", ".join(r.get("failed_attributes") or []),
                    r.get("why", ""), r.get("remarks", ""),
                ]
                for r in remediation
            ],
        )

    # ── Sheet 6: approved attributes ──────────────────────────────────
    attr_rows = []
    for schema in sorted(attribute_schemas, key=lambda s: s["control_id"]):
        for i, attr in enumerate(schema.get("attributes") or [], start=1):
            attr_rows.append([schema["control_id"], i, attr.get("name", ""), attr.get("description", "")])
    _write_sheet(
        wb.create_sheet("Attributes"),
        ["Control ID", "Attribute #", "Attribute Name", "Attribute Description"],
        [16, 12, 35, 60],
        attr_rows,
    )

    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (project.get("name") or "project"))[:60]
    dest = dest_dir / f"Final_Report_{safe_name}_{_timestamp()}.xlsx"
    wb.save(dest)
    return dest


def _date_range(timeline_row: dict[str, Any] | None) -> str:
    if not timeline_row:
        return ""
    earliest, latest = timeline_row.get("earliest_evidence_date"), timeline_row.get("latest_evidence_date")
    return f"{earliest} to {latest}" if earliest and latest else "No dated evidence"
