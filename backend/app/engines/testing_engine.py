"""
Phase 4 — control effectiveness testing. Multi-sample (TOE-style) ONLY, per
this build's explicit deviation from the generalized spec: there is no
single-sample/design-test path. Controls whose evidence isn't organized into
samples are skipped and reported separately, never defaulted to pass/fail.

The evaluation prompt carries the 5 consistency rules verbatim from
ATTRIBUTE_GENERATION_ENGINE_SPEC.md Section 1, and attribute_results is
keyed by the attribute `id`s frozen at approval time — resequencing after
freeze would desynchronize those keys, which is why mutation is blocked
once a schema is approved.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from app.engines.evidence_router import is_junk_path
from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.testing_engine")

# deviation_rate bands -> deficiency severity (configurable defaults).
DEFAULT_DEFICIENCY_BANDS = [(0.10, "Deficiency"), (0.20, "Significant Deficiency")]
_MATERIAL_WEAKNESS = "Material Weakness"

# A sample that could not be evaluated at all (no LLM available, no readable
# evidence content). This is deliberately NOT "FAIL": an infrastructure
# problem must never be recorded as a control deviation, or a transient
# outage would manufacture Material Weaknesses across a whole engagement.
NOT_EVALUATED = "NOT_EVALUATED"

_MAX_EVIDENCE_CHARS_PER_SAMPLE = 6000

# Testing is nested: controls in parallel, and samples within each control in
# parallel. Peak concurrent calls is the product, so these are kept modest —
# 4 x 4 = 16 in flight, enough to keep the endpoint busy without tripping
# rate limits and turning a fast run into a retry storm.
_CONTROL_WORKERS = 4
_SAMPLE_WORKERS = 4

_CONSISTENCY_RULES = """CONSISTENCY RULES — these are absolute:
1. If ANY attribute = "No" -> result MUST be "FAIL"
2. If result = "PASS" -> ALL attributes MUST be "Yes" or "N/A" (never "No")
3. If result = "FAIL" -> at least ONE attribute MUST be "No"
4. Remarks MUST be consistent with the result
5. If ALL attributes are "Yes" or "N/A" (none "No") -> result MUST be "PASS". N/A is not a failure."""


def _get_llm_client():
    return get_llm_client()


def _read_sample_evidence(paths: list[Path]) -> str:
    """Best-effort text for one sample. Binary/unreadable files are listed
    by name rather than dropped, so the evaluator still knows they exist."""
    parts: list[str] = []
    for p in paths:
        if not p.exists() or not p.is_file() or is_junk_path([p.name]):
            continue
        suffix = p.suffix.lower()
        try:
            if suffix in (".txt", ".csv", ".md", ".json"):
                parts.append(f"--- {p.name} ---\n{p.read_text(encoding='utf-8', errors='replace')}")
            elif suffix in (".docx", ".pdf"):
                from app.engines.text_extraction import extract_text

                parts.append(f"--- {p.name} ---\n{extract_text(p)}")
            else:
                parts.append(f"--- {p.name} (binary/unsupported type — filename only) ---")
        except Exception as e:
            logger.warning("Could not read evidence file %s: %s", p, e)
            parts.append(f"--- {p.name} (unreadable: {e}) ---")
    return "\n\n".join(parts)[:_MAX_EVIDENCE_CHARS_PER_SAMPLE]


def _enforce_consistency(result: str, attribute_results: dict[str, str]) -> str:
    """Rules 1/3/5 enforced in code, not just prompt — the LLM's own verdict
    is overridden if it contradicts its per-attribute answers, so pass/fail
    and the deviation rate can never disagree with the attribute grid."""
    values = [str(v).strip().lower() for v in attribute_results.values()]
    if any(v == "no" for v in values):
        return "FAIL"
    if values and all(v in ("yes", "n/a", "na") for v in values):
        return "PASS"
    return "FAIL" if str(result).strip().upper() == "FAIL" else "PASS"


def evaluate_sample(
    control: dict[str, Any],
    schema: dict[str, Any],
    sample_id: str,
    evidence_paths: list[Path],
) -> dict[str, Any]:
    attributes = schema.get("attributes") or []
    sample_columns = schema.get("sample_columns") or []
    attribute_ids = [a["id"] for a in attributes]

    client, model = _get_llm_client()
    evidence_text = _read_sample_evidence(evidence_paths)

    if client is None or not evidence_text.strip():
        # An infrastructure problem is NOT a control failure. Returning FAIL
        # here would be indistinguishable from a real deviation and would
        # inflate the deviation rate into a fabricated Material Weakness, so
        # this is its own state that aggregation excludes from the counts.
        reason = "No LLM configured" if client is None else "No readable evidence content in this sample"
        return {
            "control_id": control["control_id"], "sample_id": sample_id, "result": NOT_EVALUATED,
            "attribute_results": {}, "attribute_reasoning": {aid: reason for aid in attribute_ids},
            "sample_details": {}, "remarks": f"Could not evaluate: {reason}.",
        }

    attributes_block = "\n".join(
        f'  "{a["id"]}": {a["name"]} — {a["description"]}' for a in attributes
    )
    columns_block = ", ".join(f'{c["header"]} (key: {c["key"]})' for c in sample_columns)

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit evidence evaluator. For ONE sample of ONE control, answer each "
                        "testing attribute Yes / No / N/A strictly from the evidence provided, then give an "
                        "overall PASS/FAIL result.\n\n"
                        "Answer 'Yes' only if the evidence positively supports it. Answer 'No' if the evidence "
                        "contradicts it or the required evidence is absent. Answer 'N/A' ONLY when the "
                        "attribute's own description says N/A applies and that condition holds here.\n\n"
                        f"{_CONSISTENCY_RULES}\n\n"
                        "Also extract the requested descriptive sample columns as free text (use \"Not found\" "
                        "if absent). If result is FAIL, remarks must be a non-empty explanation.\n\n"
                        'Return ONLY JSON: {"result": "PASS|FAIL", '
                        '"attribute_results": {"1": "Yes|No|N/A", ...}, '
                        '"attribute_reasoning": {"1": "why", ...}, '
                        '"sample_details": {"column_key": "value", ...}, "remarks": "..."}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"CONTROL: {control.get('control_id')} — {control.get('control_description') or ''}\n"
                        f"RISK: {control.get('risk_description') or 'n/a'}\n\n"
                        f"ATTRIBUTES (answer each by its id):\n{attributes_block}\n\n"
                        f"SAMPLE COLUMNS TO EXTRACT: {columns_block}\n\n"
                        f"SAMPLE ID: {sample_id}\n"
                        f"EVIDENCE:\n{evidence_text}"
                    ),
                },
            ],
            max_completion_tokens=6000,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="testing_engine.evaluate_sample")

        raw_results = parsed.get("attribute_results") or {}
        # Only keep ids that exist in the frozen schema; any attribute the
        # model skipped counts as "No" rather than silently vanishing from
        # the pass/fail computation.
        attribute_results = {}
        for aid in attribute_ids:
            value = str(raw_results.get(aid, "")).strip()
            attribute_results[aid] = value if value.lower() in ("yes", "no", "n/a", "na") else "No"

        result = _enforce_consistency(parsed.get("result", ""), attribute_results)
        remarks = (parsed.get("remarks") or "").strip()
        if result == "FAIL" and not remarks:
            failed = [aid for aid, v in attribute_results.items() if v.lower() == "no"]
            remarks = f"Failed attribute(s): {', '.join(failed)}."

        return {
            "control_id": control["control_id"], "sample_id": sample_id, "result": result,
            "attribute_results": attribute_results,
            "attribute_reasoning": {k: str(v) for k, v in (parsed.get("attribute_reasoning") or {}).items()},
            "sample_details": {k: str(v) for k, v in (parsed.get("sample_details") or {}).items()},
            "remarks": remarks,
        }
    except Exception as e:
        logger.warning("Sample evaluation failed for %s/%s: %s", control["control_id"], sample_id, e)
        return {
            "control_id": control["control_id"], "sample_id": sample_id, "result": "FAIL",
            "attribute_results": {aid: "No" for aid in attribute_ids},
            "attribute_reasoning": {aid: f"Evaluation error: {e}" for aid in attribute_ids},
            "sample_details": {}, "remarks": f"Evaluation failed: {e}",
        }


def _deficiency_for_rate(deviation_rate: float, bands=None) -> str | None:
    bands = bands or DEFAULT_DEFICIENCY_BANDS
    if deviation_rate <= 0:
        return None
    for threshold, label in bands:
        if deviation_rate <= threshold:
            return label
    return _MATERIAL_WEAKNESS


def _effectiveness_status(failed: int, total: int) -> str:
    if total == 0:
        return "Not Tested"
    if failed == 0:
        return "Effective"
    if failed == total:
        return "Not Effective"
    return "Effective with Exceptions"


def aggregate_control_result(control_id: str, sample_results: list[dict[str, Any]]) -> dict[str, Any]:
    # Samples that couldn't be evaluated are excluded from the pass/fail
    # arithmetic entirely — counting them either way would misstate the
    # deviation rate, and the rate drives deficiency severity.
    not_evaluated = [s for s in sample_results if s["result"] == NOT_EVALUATED]
    evaluated = [s for s in sample_results if s["result"] != NOT_EVALUATED]

    total = len(evaluated)
    failed = sum(1 for s in evaluated if s["result"] == "FAIL")
    passed = total - failed
    deviation_rate = round(failed / total, 4) if total else 0.0
    status = _effectiveness_status(failed, total)
    deficiency = _deficiency_for_rate(deviation_rate) if total else None

    if total == 0:
        remarks = f"No sample could be evaluated ({len(not_evaluated)} sample(s) unreadable or un-evaluable)."
    elif failed == 0:
        remarks = f"All {total} evaluated sample(s) passed."
    else:
        remarks = f"{failed} of {total} evaluated sample(s) failed (deviation rate {deviation_rate:.0%})."
    if not_evaluated and total > 0:
        remarks += f" {len(not_evaluated)} further sample(s) could not be evaluated and are excluded."

    return {
        "control_id": control_id,
        "test_mode": "multi_sample",
        "total_samples": total,
        "passed_samples": passed,
        "failed_samples": failed,
        "not_evaluated_samples": len(not_evaluated),
        "deviation_rate": deviation_rate,
        "effectiveness_status": status,
        "deficiency_type": deficiency,
        "overall_remarks": remarks,
        "sample_results": sample_results,
    }


def test_control(
    control: dict[str, Any],
    schema: dict[str, Any],
    samples: dict[str, list[Path]],
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Evaluates every sample for one control, then aggregates.

    Samples run concurrently. Evaluating them in sequence made the control
    pool's width the only source of parallelism, so a 12-control x 5-sample
    engagement issued 60 calls but never had more than 4 in flight — the
    samples behind each control queued up one at a time. Sample evaluations
    are independent (each returns a self-contained verdict and aggregation
    happens afterwards), so there is nothing to serialize them for.
    """
    control_id = control["control_id"]
    sample_ids = sorted(samples.keys())
    total = len(sample_ids)
    if not sample_ids:
        return aggregate_control_result(control_id, [])

    results_by_id: dict[str, dict[str, Any]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=min(_SAMPLE_WORKERS, total)) as pool:
        futures = {
            pool.submit(evaluate_sample, control, schema, sid, samples[sid]): sid
            for sid in sample_ids
        }
        for future in as_completed(futures):
            sid = futures[future]
            try:
                results_by_id[sid] = future.result()
            except Exception as e:
                # An infrastructure failure on one sample must not fail the
                # control or, worse, be recorded as a deviation — same rule
                # evaluate_sample applies internally. NOT_EVALUATED is
                # excluded from the deviation rate.
                logger.warning("Sample evaluation raised for %s/%s: %s", control_id, sid, e)
                results_by_id[sid] = {
                    "control_id": control_id,
                    "sample_id": sid,
                    "result": NOT_EVALUATED,
                    "attribute_results": {},
                    "attribute_reasoning": {},
                    "sample_details": {},
                    "remarks": f"Could not evaluate: {e}.",
                }
            done += 1
            if progress_callback:
                progress_callback(control_id, done, total)

    # Aggregate in sample order, not completion order — sample_results is
    # rendered as an ordered list in the workpaper.
    sample_results = [results_by_id[sid] for sid in sample_ids]
    return aggregate_control_result(control_id, sample_results)


def run_batch_testing(
    controls: list[dict[str, Any]],
    schemas_by_control: dict[str, dict[str, Any]],
    samples_by_control: dict[str, dict[str, list[Path]]],
    modes_by_control: dict[str, str],
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (control_results, format_issues). Controls whose evidence
    isn't sample-organized are never tested and never defaulted to a
    verdict — they come back in format_issues so the run summary can report
    them separately from controls that were actually evaluated."""
    testable: list[dict[str, Any]] = []
    format_issues: list[dict[str, Any]] = []

    for control in controls:
        control_id = control["control_id"]
        mode = modes_by_control.get(control_id, "no_evidence")
        if mode != "multi_sample":
            format_issues.append({
                "control_id": control_id,
                "detected_mode": mode,
                "message": (
                    "No sample1/sample2 structure found — evidence must be reorganized into per-sample "
                    "subfolders or sample_N-named files before testing."
                    if mode == "invalid_format"
                    else "No evidence uploaded for this control."
                ),
            })
            continue
        if not (schemas_by_control.get(control_id, {}).get("attributes")):
            format_issues.append({
                "control_id": control_id,
                "detected_mode": mode,
                "message": "No approved testing attributes for this control — generate and approve attributes first.",
            })
            continue
        # A control classified multi_sample but carrying no resolvable sample
        # files must not be "tested": aggregating zero samples would report
        # "All 0 sample(s) passed" while still occupying the health-score
        # denominator. Report it as untestable instead.
        if not samples_by_control.get(control_id):
            format_issues.append({
                "control_id": control_id,
                "detected_mode": mode,
                "message": "No readable evidence samples found for this control — re-upload its evidence folder.",
            })
            continue
        testable.append(control)

    control_results: list[dict[str, Any]] = []
    if testable:
        # Progress is reported per CONTROL here, not per sample. Passing the
        # caller's callback straight into test_control would have each control
        # report its own 1..N sample count, so a shared progress bar would
        # restart on every control instead of advancing once per control.
        total_controls = len(testable)
        completed = 0
        with ThreadPoolExecutor(max_workers=_CONTROL_WORKERS) as pool:
            futures = {
                pool.submit(
                    test_control,
                    c,
                    schemas_by_control[c["control_id"]],
                    samples_by_control.get(c["control_id"], {}),
                ): c["control_id"]
                for c in testable
            }
            for future in as_completed(futures):
                control_id = futures[future]
                if progress_callback:
                    completed += 1
                    try:
                        progress_callback(control_id, completed, total_controls)
                    except Exception:
                        logger.debug("testing progress callback failed", exc_info=True)
                try:
                    control_results.append(future.result())
                except Exception as e:
                    logger.warning("Control testing raised for %s: %s", control_id, e)
                    format_issues.append({
                        "control_id": control_id, "detected_mode": "multi_sample",
                        "message": f"Testing failed with an error: {e}",
                    })

    order = {c["control_id"]: i for i, c in enumerate(controls)}
    control_results.sort(key=lambda r: order.get(r["control_id"], 0))
    format_issues.sort(key=lambda r: order.get(r["control_id"], 0))
    return control_results, format_issues
