"""
Phase 3 — timeline-sufficiency check: is the evidence uploaded in Phase 2
sufficient given the audit period defined at project creation. Genuinely
new logic, no ControlIris precedent. Never defaults an undetermined date
read to "compliant" — an absence of evidence dates is its own status, not
silently treated as passing.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.timeline_sufficiency")

_DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-_](0[1-9]|1[0-2])[-_](0[1-9]|[12]\d|3[01])"),  # 2026-01-31 / 2026_01_31
    re.compile(r"(0[1-9]|1[0-2])[-_](0[1-9]|[12]\d|3[01])[-_](20\d{2})"),  # 01-31-2026
    re.compile(r"(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"),  # 20260131
]

_FREQUENCY_INTERVAL_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 91,
    "annual": 365,
    "annually": 365,
    "yearly": 365,
}


def _date_from_filename(filename: str) -> date | None:
    # finditer, not search: a filename can contain a syntactically-valid but
    # nonexistent date (e.g. 2025-02-30) ahead of a real one, and stopping at
    # the first match would discard the usable date entirely.
    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(filename):
            groups = m.groups()
            try:
                if len(groups[0]) == 4:  # YYYY-MM-DD or YYYYMMDD
                    year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                else:  # MM-DD-YYYY
                    month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
                return date(year, month, day)
            except ValueError:
                continue
    return None


def _llm_infer_dates(control_id: str, filenames: list[str]) -> list[date]:
    # Shared, connection-pooled client (see evidence_gap_engine).
    client, deployment = get_llm_client()
    if client is None or not filenames:
        return []

    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit-evidence dating assistant. Given a list of evidence filenames "
                        "for one control, infer the transaction/evidence date implied by each filename if "
                        "possible (e.g. a filename referencing a month name, quarter, or period). If a "
                        "filename gives no date signal at all, omit it. "
                        'Return ONLY JSON: {"dates": ["YYYY-MM-DD", ...]}'
                    ),
                },
                {"role": "user", "content": f"Control: {control_id}\nFilenames:\n" + "\n".join(filenames[:50])},
            ],
            # Reasoning-model budget — see risk_scorer.py's
            # _llm_infer_risk_level for why this needs real headroom.
            max_completion_tokens=1500,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="timeline_sufficiency._llm_infer_dates")
        out = []
        for d in parsed.get("dates", []):
            try:
                out.append(date.fromisoformat(d))
            except (ValueError, TypeError):
                continue
        return out
    except Exception as e:
        logger.warning("LLM date inference failed for %s: %s", control_id, e)
        return []


def _extract_evidence_dates(control_id: str, filenames: list[str]) -> list[date]:
    """Cheap filename-regex pass first; only falls back to an LLM call for
    filenames the regex couldn't resolve."""
    found: list[date] = []
    unresolved: list[str] = []
    for f in filenames:
        d = _date_from_filename(f)
        if d:
            found.append(d)
        else:
            unresolved.append(f)

    if unresolved:
        found.extend(_llm_infer_dates(control_id, unresolved))
    return found


_EVENT_DRIVEN_FREQUENCIES = ("event-driven", "event driven", "as needed", "ad hoc", "ad-hoc", "as required")

# For high-frequency (daily/weekly) controls, evidence can be evenly spaced
# yet still far too sparse to evidence the stated cadence. Below this share
# of expected instances the control is flagged even with no single large gap.
_SPARSE_COVERAGE_THRESHOLD = 0.9


def _classify_frequency(control_frequency: str | None) -> str:
    """'cadence'    — a known periodic frequency; run the full cadence check.
    'event_driven' — legitimately has no cadence; in-window presence is enough.
    'unknown'      — frequency missing or unrecognized. This is NOT the same as
                     event-driven: we cannot judge cadence, so the result must
                     be 'undetermined', never silently 'sufficient'."""
    if not control_frequency or not control_frequency.strip():
        return "unknown"
    freq = control_frequency.strip().lower()
    if freq in _EVENT_DRIVEN_FREQUENCIES:
        return "event_driven"
    return "cadence" if freq in _FREQUENCY_INTERVAL_DAYS else "unknown"


# Calendar-period frequencies bucket by real calendar units, not by
# fixed day counts. Using days/30 for "monthly" mis-buckets real month-end
# evidence (months are 28-31 days), so twelve perfect month-end
# reconciliations would collide into 11 buckets and be reported as a
# coverage gap — a false deficiency on the most common SOX case there is.
_CALENDAR_BUCKETERS = {
    "monthly": lambda d: (d.year, d.month),
    "quarterly": lambda d: (d.year, (d.month - 1) // 3),
    "annual": lambda d: (d.year,),
    "annually": lambda d: (d.year,),
    "yearly": lambda d: (d.year,),
}


def _calendar_bucket_count(freq: str, start: date, end: date) -> int:
    """Number of distinct calendar buckets the audit period spans."""
    bucketer = _CALENDAR_BUCKETERS[freq]
    buckets = set()
    # Walk month-by-month; every bucket kind above is month-aligned or coarser.
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        buckets.add(bucketer(date(year, month, 1)))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return max(1, len(buckets))


def _expected_instances(control_frequency: str | None, start: date, end: date) -> int | None:
    """None means no countable cadence expectation (event-driven or unknown)."""
    if _classify_frequency(control_frequency) != "cadence":
        return None
    freq = control_frequency.strip().lower()
    if freq in _CALENDAR_BUCKETERS:
        return _calendar_bucket_count(freq, start, end)
    interval = _FREQUENCY_INTERVAL_DAYS[freq]
    total_days = (end - start).days + 1
    return max(1, round(total_days / interval))


def check_timeline_sufficiency(
    control_id: str,
    filenames: list[str],
    audit_period_start: date,
    audit_period_end: date,
    control_frequency: str | None,
) -> dict[str, Any]:
    dates = sorted(_extract_evidence_dates(control_id, filenames))

    if not dates:
        return {
            "control_id": control_id,
            "status": "undetermined",
            "flags": ["undetermined"],
            "earliest_evidence_date": None,
            "latest_evidence_date": None,
            "expected_instances": _expected_instances(control_frequency, audit_period_start, audit_period_end),
            "evidence_instances_found": 0,
            "coverage_pct": 0.0,
        }

    flags: list[str] = []
    in_window = [d for d in dates if audit_period_start <= d <= audit_period_end]
    out_of_window = [d for d in dates if d not in in_window]
    if out_of_window and not in_window:
        flags.append("out_of_period")
    elif out_of_window:
        flags.append("partial_coverage")

    expected = _expected_instances(control_frequency, audit_period_start, audit_period_end)
    freq = (control_frequency or "").strip().lower()
    frequency_kind = _classify_frequency(control_frequency)

    if frequency_kind == "unknown":
        # Frequency missing or unrecognized — we genuinely cannot judge whether
        # this evidence covers the period, so say so rather than defaulting to
        # sufficient. In-window presence is still reported for context.
        coverage_pct = 1.0 if in_window else 0.0
        flags.append("undetermined")
        if not in_window:
            flags.append("gap")
    elif frequency_kind == "event_driven":
        # Legitimately has no cadence — only check some evidence falls inside
        # the window; no gap counting.
        coverage_pct = 1.0 if in_window else 0.0
        if not in_window:
            flags.append("gap")
    elif freq in ("daily", "weekly"):
        interval_days = _FREQUENCY_INTERVAL_DAYS[freq]
        max_gap = timedelta(days=interval_days * 1.5)
        has_large_gap = False
        checkpoints = [audit_period_start] + sorted(in_window) + [audit_period_end]
        for prev, nxt in zip(checkpoints, checkpoints[1:]):
            if nxt - prev > max_gap:
                has_large_gap = True
                break
        if has_large_gap:
            flags.append("gap")
        coverage_pct = round(min(len(in_window) / expected, 1.0), 4) if expected else 0.0
        # Cadence gaps alone aren't enough: evidence can be evenly spaced yet
        # far too sparse (e.g. a weekly control with evidence every 10 days
        # never trips the 1.5x gap check but covers only ~71% of the weeks).
        if coverage_pct < _SPARSE_COVERAGE_THRESHOLD and "gap" not in flags:
            flags.append("partial_coverage")
    else:
        # Monthly/Quarterly/Annual — at least one evidence instance per
        # CALENDAR period-bucket in [start, end]. Calendar bucketing (not
        # days // 30) is what makes real month-end evidence land one per
        # bucket instead of colliding.
        bucketer = _CALENDAR_BUCKETERS[freq]
        buckets_covered = {bucketer(d) for d in in_window}
        coverage_pct = round(min(len(buckets_covered) / expected, 1.0), 4) if expected else 0.0
        if coverage_pct < 1.0:
            flags.append("gap" if coverage_pct == 0 else "partial_coverage")

    if not flags:
        status = "sufficient"
    elif "undetermined" in flags:
        status = "undetermined"
    else:
        status = "insufficient"

    return {
        "control_id": control_id,
        "status": status,
        "flags": sorted(set(flags)),
        "earliest_evidence_date": dates[0].isoformat(),
        "latest_evidence_date": dates[-1].isoformat(),
        "expected_instances": expected,
        "evidence_instances_found": len(dates),
        "coverage_pct": coverage_pct,
    }


def run_timeline_sufficiency_check(
    controls: list[dict[str, Any]],
    filenames_by_control: dict[str, list[str]],
    audit_period_start: date,
    audit_period_end: date,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(
                check_timeline_sufficiency,
                c["control_id"],
                filenames_by_control.get(c["control_id"], []),
                audit_period_start,
                audit_period_end,
                c.get("control_frequency"),
            ): c["control_id"]
            for c in controls
        }
        for future in as_completed(futures):
            control_id = futures[future]
            try:
                results.append(future.result())
            except Exception as e:
                logger.warning("Timeline sufficiency check raised for %s: %s", control_id, e)
                results.append({
                    "control_id": control_id, "status": "undetermined", "flags": ["undetermined"],
                    "earliest_evidence_date": None, "latest_evidence_date": None,
                    "expected_instances": None, "evidence_instances_found": 0, "coverage_pct": 0.0,
                })

    order = {c["control_id"]: i for i, c in enumerate(controls)}
    results.sort(key=lambda r: order.get(r["control_id"], 0))
    return results
