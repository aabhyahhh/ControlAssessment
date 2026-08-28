"""
Phase 2 — required-documents checklist generation, evidence-vs-checklist
validation, gap escalation, and document-completeness aggregation. New
logic (no direct ControlIris precedent for this exact shape), but the
per-control LLM-call-in-a-thread-pool-with-isolated-failures pattern
mirrors risk_scorer.py / ControlIris's infer_risk_level.py.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.evidence_gap_engine")

_ESCALATION_THRESHOLD = 50

_FALLBACK_CHECKLIST = ["Supporting documentation", "Approval evidence", "System/control output"]


def _generate_checklist_for_control(control_description: str) -> list[str]:
    # Shared, connection-pooled client: this runs once per control inside a
    # thread pool, so building one here would pay a fresh TLS handshake for
    # every control in the RCM.
    client, deployment = get_llm_client()
    if client is None or not control_description.strip():
        return _FALLBACK_CHECKLIST

    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit evidence-planning assistant. Given a control description, "
                        "list the 3-6 specific document/evidence types an auditor would expect to see "
                        "to test this control (e.g. 'Approval email', 'System-generated exception report', "
                        "'Signed reconciliation'). Be concrete, not generic. "
                        'Return ONLY JSON: {"documents": ["...", "..."]}'
                    ),
                },
                {"role": "user", "content": f"Control Description: {control_description}"},
            ],
            # See risk_scorer.py's _llm_infer_risk_level for why this needs
            # real headroom on a reasoning model, not just enough for the
            # visible JSON output.
            # Raised from 1500: observed finish_reason=length, which silently
            # fell back to the generic checklist for that control.
            max_completion_tokens=2500,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="evidence_gap_engine._generate_checklist_for_control")
        docs = [d.strip() for d in parsed.get("documents", []) if isinstance(d, str) and d.strip()]
        return docs or _FALLBACK_CHECKLIST
    except Exception as e:
        logger.warning("Required-documents generation failed: %s", e)
        return _FALLBACK_CHECKLIST


def generate_required_documents(controls: list[dict[str, Any]]) -> dict[str, list[str]]:
    """One LLM call per control, parallelized, isolated failures fall back
    to a generic checklist rather than blocking the whole batch."""
    results: dict[str, list[str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_generate_checklist_for_control, c.get("control_description") or ""): c["control_id"]
            for c in controls
        }
        for future in as_completed(futures):
            control_id = futures[future]
            try:
                results[control_id] = future.result()
            except Exception as e:
                logger.warning("Checklist generation raised for %s: %s", control_id, e)
                results[control_id] = _FALLBACK_CHECKLIST
    return results


def _match_documents(required: list[str], uploaded_filenames: list[str]) -> tuple[list[str], list[str]]:
    """Lightweight fuzzy match: a required doc is 'matched' if any uploaded
    filename shares a significant word with it (case-insensitive). No LLM
    call per match (would be O(controls x filenames) LLM calls) — token
    overlap is cheap and good enough for a checklist-completeness signal."""
    if not uploaded_filenames:
        return [], list(required)

    stopwords = {"the", "of", "a", "an", "for", "and", "or", "to", "on"}

    def tokens(s: str) -> set[str]:
        return {w for w in "".join(c.lower() if c.isalnum() else " " for c in s).split() if w and w not in stopwords}

    filename_tokens = [tokens(f) for f in uploaded_filenames]

    matched, missing = [], []
    for doc in required:
        doc_tokens = tokens(doc)
        if doc_tokens and any(doc_tokens & ft for ft in filename_tokens):
            matched.append(doc)
        else:
            missing.append(doc)
    return matched, missing


def _band_for_score(score: int) -> str:
    if score >= 70:
        return "good"
    if score >= 30:
        return "fair"
    return "poor"


def _severity(risk_rating: str, score: int) -> str | None:
    """Escalation threshold is 50 for every risk rating — no control gets a
    free pass on a fair/poor evidence score just because a rating-specific
    band happened not to cover it. Within that, High-risk controls escalate
    higher for the same score (High/Serious below 30, Medium/Moderate from
    30 up to the threshold) than Medium-risk controls (Medium/Moderate
    throughout), matching the plan's risk-weighted severity model."""
    if score >= _ESCALATION_THRESHOLD:
        return None
    if risk_rating == "High":
        return "High/Serious" if score < 30 else "Medium/Moderate"
    if risk_rating == "Medium":
        return "Medium/Moderate"
    return "Low/Minor"


def assess_evidence_gaps(
    controls: list[dict[str, Any]],
    required_documents: dict[str, list[str]],
    uploaded_filenames_by_control: dict[str, list[str]],
    format_flags_by_control: dict[str, str],
) -> dict[str, Any]:
    """controls must carry risk_level (from Phase 1, overlay-resolved).
    uploaded_filenames_by_control: {control_id: [filename, ...]} — flat list
    of all filenames under that control's evidence folder, any mode.
    format_flags_by_control: {control_id: detected_mode} from evidence_router,
    for the invalid_format cross-reference (Phase 2 doesn't block on this,
    just surfaces it for early visibility ahead of Phase 4)."""
    risk_by_control = {c["control_id"]: (c.get("risk_level") or "Medium") for c in controls}

    evidence_scores: list[dict[str, Any]] = []
    missing_documents: list[dict[str, Any]] = []
    escalated_gaps: list[dict[str, Any]] = []
    total_matched = 0
    total_missing = 0
    controls_without_evidence = 0
    test_ready_controls = 0

    for c in controls:
        control_id = c["control_id"]
        required = required_documents.get(control_id, [])
        filenames = uploaded_filenames_by_control.get(control_id, [])
        matched, missing = _match_documents(required, filenames)

        score = round((len(matched) / len(required)) * 100) if required else 0
        band = _band_for_score(score)

        total_matched += len(matched)
        total_missing += len(missing)

        if not filenames:
            controls_without_evidence += 1
        if format_flags_by_control.get(control_id) == "multi_sample" and score >= _ESCALATION_THRESHOLD:
            test_ready_controls += 1

        evidence_scores.append({"control_id": control_id, "score": score, "band": band})

        if missing:
            missing_documents.append({"control_id": control_id, "missing": missing})

        risk_rating = risk_by_control.get(control_id, "Medium")
        severity = _severity(risk_rating, score)
        if severity:
            explanation = (
                f"No evidence uploaded for a {risk_rating.lower()}-risk control."
                if not filenames
                else f"Only {score}% of expected documents matched ({len(matched)}/{len(required)})."
            )
            escalated_gaps.append(
                {"control_id": control_id, "risk_rating": risk_rating, "severity": severity, "explanation": explanation},
            )

    n = len(controls)
    avg_score = round(sum(e["score"] for e in evidence_scores) / n) if n else 0

    return {
        "stats": {
            "avg_evidence_score": avg_score,
            "controls_without_evidence": controls_without_evidence,
            "evidence_gaps_count": len(escalated_gaps),
            "test_ready_controls": test_ready_controls,
        },
        "required_documents": required_documents,
        "evidence_scores": evidence_scores,
        "document_completeness_donut": {"matched": total_matched, "missing": total_missing},
        "missing_documents": missing_documents,
        "escalated_gaps": escalated_gaps,
        "format_flags": [
            {"control_id": cid, "detected_mode": mode}
            for cid, mode in format_flags_by_control.items()
            if mode in ("invalid_format",)
        ],
    }
