"""
Step 3 — Evidence Requirements & Intake.

  1. generate_required_documents — one LLM call per control produces the list
     of document/evidence types an auditor would expect, informed by the RCM
     row and (where available) the SOP/workpaper text reconciled in step 2.
  2. assess_evidence_gaps — a three-way reconciliation per control:
       expected  (this engine's generated list)
       declared  (what the user says they hold, entered per-control in the UI)
       present   (what was actually uploaded)
     and the gaps between them.

Severity here is coverage-driven, not risk-driven: the redesigned flow does
no risk-level analysis.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.evidence_gap_engine")

_FALLBACK_CHECKLIST = ["Supporting documentation", "Approval evidence", "System/control output"]


def _generate_checklist_for_control(control_description: str, sop_context: str) -> list[str]:
    client, deployment = get_llm_client()
    if client is None or not (control_description.strip() or sop_context.strip()):
        return _FALLBACK_CHECKLIST

    try:
        user_content = f"Control Description: {control_description or '(not stated in RCM)'}"
        if sop_context.strip():
            user_content += f"\n\nSOP / workpaper context for this control:\n{sop_context[:3000]}"
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit evidence-planning assistant. Given a control description (and any "
                        "SOP/workpaper context), list the 3-6 specific document/evidence types an auditor "
                        "would expect to see to test this control (e.g. 'Approval email', 'System-generated "
                        "exception report', 'Signed reconciliation'). Be concrete, not generic. "
                        'Return ONLY JSON: {"documents": ["...", "..."]}'
                    ),
                },
                {"role": "user", "content": user_content},
            ],
            max_completion_tokens=2500,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="evidence_gap_engine._generate_checklist_for_control")
        docs = [d.strip() for d in parsed.get("documents", []) if isinstance(d, str) and d.strip()]
        return docs or _FALLBACK_CHECKLIST
    except Exception as e:
        logger.warning("Required-documents generation failed: %s", e)
        return _FALLBACK_CHECKLIST


def generate_required_documents(
    controls: list[dict[str, Any]],
    sop_context_by_control: dict[str, str] | None = None,
    on_progress: Callable[[str, int, int, str | None], None] | None = None,
) -> dict[str, list[str]]:
    """One LLM call per control, parallelized, isolated failures fall back to
    a generic checklist. `sop_context_by_control` (from step 2) sharpens the
    checklist when a control's RCM description is thin. `on_progress`, when
    given, is called as (control_id, done, total, activity) — once before
    any result lands (so a slow first LLM call doesn't look hung) and once
    per completed control after — same shape as
    `sop_adequacy_engine.run_sop_adequacy_assessment`'s callback, so the
    route can drive the same progress-polling UI."""
    sop_context_by_control = sop_context_by_control or {}
    total = len(controls)
    done = 0
    results: dict[str, list[str]] = {}

    def _report(control_id: str, activity: str) -> None:
        if not on_progress:
            return
        try:
            on_progress(control_id, done, total, activity)
        except Exception:
            logger.debug("evidence progress callback failed", exc_info=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        if controls:
            _report(controls[0]["control_id"], "Generating the expected-evidence checklist")
        futures = {
            pool.submit(
                _generate_checklist_for_control,
                c.get("control_description") or "",
                sop_context_by_control.get(c["control_id"], ""),
            ): c["control_id"]
            for c in controls
        }
        for future in as_completed(futures):
            control_id = futures[future]
            try:
                results[control_id] = future.result()
            except Exception as e:
                logger.warning("Checklist generation raised for %s: %s", control_id, e)
                results[control_id] = _FALLBACK_CHECKLIST
            done += 1
            _report(control_id, "Checklist generated")
    return results


def _tokens(s: str) -> set[str]:
    stopwords = {"the", "of", "a", "an", "for", "and", "or", "to", "on", "in", "with"}
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in s).split() if w and w not in stopwords}


def _fuzzy_covers(target: str, candidates: list[str]) -> bool:
    """A target document is 'covered' by a candidate list if any candidate
    shares a significant word with it (case-insensitive token overlap)."""
    t = _tokens(target)
    if not t:
        return False
    return any(t & _tokens(c) for c in candidates)


def _severity_for_coverage(expected_count: int, present_count: int, declared_present: bool, any_declared: bool) -> str | None:
    """critical  — control has expected docs and nothing was provided at all
    high      — <50% of expected present, and the user did declare holding
                evidence (so the gap is collection/upload, not a design gap)
    medium    — partial coverage
    low       — near-complete
    None      — fully covered."""
    if expected_count == 0:
        return None
    ratio = present_count / expected_count
    if ratio >= 1.0:
        return None
    if present_count == 0:
        return "critical" if not declared_present else "high"
    if ratio < 0.5:
        return "high" if any_declared else "medium"
    if ratio < 0.85:
        return "medium"
    return "low"


def build_evidence_analytics(per_control: list[dict[str, Any]]) -> dict[str, Any]:
    """Portfolio EXPECTED -> DECLARED -> UPLOADED -> COVERED reconciliation —
    the central concept for step 3. Every stage is counted at the DOCUMENT
    level (not control level) so the funnel narrows over a single, comparable
    population: individual expected evidence items.

      expected  = every document the engine generated for any control
      declared  = expected documents the user's declared list corresponds to
                  (matched-and-uploaded counts as declared too — you can't
                  have uploaded a document without holding it)
      uploaded  = expected documents matched to an actual uploaded file
      covered   = same as uploaded here: a document only counts as covered
                  once a file exists for it, not merely because it was
                  declared

    Each stage is a strict subset of the one before it by construction, so
    the funnel is a genuine population narrowing, not four independently
    computed numbers that happen to be plotted together.
    """
    expected_total = 0
    declared_total = 0
    uploaded_total = 0
    controls_fully_covered = 0
    controls_partial = 0
    controls_no_evidence = 0
    gap_by_severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    status_matrix: list[dict[str, Any]] = []

    for row in per_control:
        required = row.get("required", [])
        matched = row.get("matched", [])
        declared_not_uploaded = row.get("declared_not_uploaded", [])
        missing = row.get("missing", [])

        expected_total += len(required)
        uploaded_total += len(matched)
        declared_total += len(matched) + len(declared_not_uploaded)

        if not required:
            pass  # nothing to expect: not fully covered, not a gap either
        elif not missing and not declared_not_uploaded:
            controls_fully_covered += 1
        elif not matched and not declared_not_uploaded:
            controls_no_evidence += 1
        else:
            controls_partial += 1

        severity = row.get("severity")
        if severity in gap_by_severity:
            gap_by_severity[severity] += 1

        status_matrix.append({
            "control_id": row["control_id"],
            "expected": len(required),
            "received": len(matched),
            "declared_not_uploaded": len(declared_not_uploaded),
            "missing": len(missing),
        })

    gap_total = expected_total - uploaded_total

    return {
        "expected_total": expected_total,
        "declared_total": declared_total,
        "uploaded_total": uploaded_total,
        "covered_total": uploaded_total,
        "gap_total": gap_total,
        "controls_fully_covered": controls_fully_covered,
        "controls_partial": controls_partial,
        "controls_no_evidence": controls_no_evidence,
        "gap_by_severity": gap_by_severity,
        "status_matrix": status_matrix,
    }


def assess_evidence_gaps(
    controls: list[dict[str, Any]],
    required_documents: dict[str, list[str]],
    uploaded_filenames_by_control: dict[str, list[str]],
    declared_items_by_control: dict[str, list[str]],
    format_flags_by_control: dict[str, str],
) -> dict[str, Any]:
    """Three-way reconciliation per control.

    - required  = required_documents[control_id]
    - declared  = declared_items_by_control[control_id] (user's structured list)
    - present   = filenames actually uploaded

    A required doc is matched if it fuzzy-matches a present filename. It is
    'declared not uploaded' if it fuzzy-matches a declared item but no file.
    """
    evidence_scores: list[dict[str, Any]] = []
    per_control: list[dict[str, Any]] = []
    escalated_gaps: list[dict[str, Any]] = []
    controls_without_evidence = 0

    for c in controls:
        control_id = c["control_id"]
        required = required_documents.get(control_id, [])
        filenames = uploaded_filenames_by_control.get(control_id, [])
        declared = declared_items_by_control.get(control_id, [])

        matched, declared_not_uploaded, missing = [], [], []
        for doc in required:
            if _fuzzy_covers(doc, filenames):
                matched.append(doc)
            elif declared and _fuzzy_covers(doc, declared):
                declared_not_uploaded.append(doc)
            else:
                missing.append(doc)

        # Items the user declared that don't correspond to any expected doc —
        # not necessarily a problem, but surfaced for completeness.
        extra_declared = [d for d in declared if not _fuzzy_covers(d, required)]

        score = round((len(matched) / len(required)) * 100) if required else 0
        band = "good" if score >= 70 else "fair" if score >= 30 else "poor"

        if not filenames:
            controls_without_evidence += 1

        evidence_scores.append({"control_id": control_id, "score": score, "band": band})

        severity = _severity_for_coverage(
            expected_count=len(required),
            present_count=len(matched),
            declared_present=bool(declared),
            any_declared=bool(declared),
        )
        row = {
            "control_id": control_id,
            "required": required,
            "declared": declared,
            "uploaded_filenames": filenames,
            "matched": matched,
            "declared_not_uploaded": declared_not_uploaded,
            "missing": missing,
            "extra_declared": extra_declared,
            "score": score,
            "severity": severity,
        }
        per_control.append(row)

        if severity:
            if not filenames and not declared:
                explanation = "No evidence uploaded and none declared for this control."
            elif declared_not_uploaded:
                explanation = (
                    f"{len(declared_not_uploaded)} declared document(s) not yet uploaded; "
                    f"{len(missing)} expected document(s) neither declared nor uploaded."
                )
            else:
                explanation = f"Only {score}% of expected documents were matched to uploaded files ({len(matched)}/{len(required)})."
            escalated_gaps.append({
                "control_id": control_id,
                "severity": severity,
                "explanation": explanation,
            })

    n = len(controls)
    avg_score = round(sum(e["score"] for e in evidence_scores) / n) if n else 0

    severity_rollup = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for g in escalated_gaps:
        severity_rollup[g["severity"]] = severity_rollup.get(g["severity"], 0) + 1

    return {
        "stats": {
            "avg_evidence_score": avg_score,
            "controls_without_evidence": controls_without_evidence,
            "evidence_gaps_count": len(escalated_gaps),
            "severity_rollup": severity_rollup,
        },
        "required_documents": required_documents,
        "evidence_scores": evidence_scores,
        "per_control": per_control,
        "escalated_gaps": escalated_gaps,
        "format_flags": [
            {"control_id": cid, "detected_mode": mode}
            for cid, mode in format_flags_by_control.items()
            if mode in ("invalid_format",)
        ],
        "analytics": build_evidence_analytics(per_control),
    }
