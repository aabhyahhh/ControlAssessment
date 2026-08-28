"""
Phase 4 — control testing attribute generation. Direct port of
ATTRIBUTE_GENERATION_ENGINE_SPEC.md's rulebook (Sections 1-4), with that
spec's confirmed defects deliberately NOT ported. Fixes applied here:

- Defect #1/#5: the deterministic quality gate runs on every mutation path,
  not just generation (see routes/attributes.py), and unresolved findings
  are surfaced rather than swallowed.
- Defect #2/#3: ONE shared generation module regardless of testing mode,
  with a single consistent style directive (evidence-oriented).
- Defect #4: risk_description / risk_level are passed into the prompt.
- Defect #8: remaining quality-gate issues are returned to the caller.
- Defect #13: generation failures are a first-class returned state
  (`generation_failed`), never a silently empty schema.

Worksteps / attributes / sample_columns are requested as three separately
instructed top-level keys (spec Section 9 checklist item 3) — blending them
is the documented cause of "confused" output.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from app.engines.attribute_quality_gate import check_schema_quality
from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.attribute_engine")

_MAX_GENERATION_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 1.0

# Worst-case wall clock for ONE control is the product of three multipliers:
#   _MAX_GENERATION_ATTEMPTS (3) x stages per attempt (3) x this timeout.
# At 90s that is ~13 minutes, and the SDK's own max_retries multiplies it
# again — which is why this call passes max_retries=0 and does its own
# retrying, where a failure is visible in the logs and counted against
# _MAX_GENERATION_ATTEMPTS rather than silently doubling the wait.
_SCHEMA_CALL_TIMEOUT_SECONDS = 90.0

# Controls generated concurrently. Each worker runs its control's 2-3 calls
# in sequence, so this is the concurrent-call count directly.
_CONTROL_WORKERS = 8

_OUTPUT_CONTRACT = """{
  "worksteps": ["1. ...", "2. ...", "3. ..."],
  "attributes": [
    {"id": "1", "name": "Short Name", "description": "Specific evidence to verify"}
  ],
  "sample_columns": [
    {"key": "snake_case_key", "header": "Column Header"}
  ]
}"""

_RULEBOOK = """You author control testing attributes for audit workpapers.

Produce THREE separate, sibling lists — never blend them:

── WORKSTEPS ──
3-5 numbered, past-tense steps describing what the auditor physically did.
GOOD: "1. Obtained the November bank reconciliation from the finance shared drive."
BAD:  "1. Checked the control." (vague, names no system or document)

── ATTRIBUTES (the core — these are the testable Yes/No/N/A conditions) ──
FIRST, before writing any attribute: list every distinct requirement stated in the
control description. Every requirement must be covered by at least one attribute.

Rules:
1. SCOPE: test only what the control description (or policy, if given) explicitly
   states. Never invent evidence sources, systems, or document names.
2. CONSOLIDATE, but never at the cost of coverage:
   - Multi-approver chains -> ONE "Approval per authority matrix" attribute.
   - Test outcomes, not process sub-steps.
   - Financial controls (provisions, journal entries, reconciliations) always need a
     linkage/traceability-to-source-documents attribute.
   - Preserve the control's exact audit terminology — if it says "authorized", use
     "authorized", do not paraphrase to "documentation reviewed".
   - Never merge genuinely independent dimensions (physical verification, system
     recording, and approval are three attributes, not one).
3. CONDITIONAL ATTRIBUTES: if a requirement only applies sometimes (e.g. "discrepancies
   are logged" — only if discrepancies exist), then the description MUST state exactly
   when N/A applies ("N/A if no discrepancies existed") and the name should hint at it
   ("Discrepancy Logged (if any)"). Do NOT phrase it as if it always applies — that
   produces false "No" verdicts on the majority of samples.
4. EQUIVALENCE: treat these as equivalent so you don't cause false failures —
   financial-health checks (D&B score / credit report / financial stability assessment);
   compliance checks (compliance-clear / ISO certification); reference checks (site
   visit / trade references). If a MINIMUM THRESHOLD is named (e.g. "D&B score > 60"),
   the attribute description must state that threshold explicitly, so an evaluator can
   tell "review done but failed the bar" from "review not done".
5. GRANULARITY: don't split one attribute per checklist sub-item when evidence confirms
   the checklist holistically — one "Checklist Completed" attribute is correct there.
6. PREVENTIVE/BLOCKING CONTROLS: test whether the block/rejection mechanism fired, not
   whether the correct transaction ultimately succeeded.
7. PER ATTRIBUTE: one specific aspect each; together they must fully cover the control
   (all-Yes => control effective); mutually exclusive (no overlap); name 3-6 words that
   fit a column header; description states what EVIDENCE to look for.
8. UNIQUENESS: never use generic names that could apply to any control ("Control
   Executed", "Process Followed", "Properly Approved", "Review Done", "Evidence
   Sufficient", "Authorization Obtained"). Every attribute must reference the specific
   action, system, threshold, or approver named in THIS control.

STYLE: descriptions are evidence-oriented — they say what to look for in the evidence.

── SAMPLE COLUMNS ──
Between 3 and 6 descriptive (non-Yes/No) transaction facts to extract per sample.
GOOD: "PR Number", "PO Amount", "Vendor Name", "Approval Date".
BAD: "Status", "Result" (those are outcomes, not sample details).

── HARD COUNT LIMITS (a schema outside these ranges is rejected) ──
worksteps: 3 to 5.  attributes: 2 to 7.  sample_columns: 3 to 6.
If you have more candidates than the limit allows, keep the most
audit-significant ones and drop the rest — do NOT exceed the limits.
Do not add an "evidence files reviewed" column; that one is appended
automatically and does not count toward your 6.

Return ONLY JSON in exactly this shape:
""" + _OUTPUT_CONTRACT

_CRITIC_RULEBOOK = """You are a strict quality reviewer for audit control testing attributes.

Review the draft schema against the control context and return an IMPROVED schema.

Checklist, in order:
1. COVERAGE FIRST: verify no requirement stated in the control description is
   unaddressed. Add an attribute if one is missing. NEVER delete the only attribute
   covering a requirement.
2. Consolidate approval-chain over-decomposition if present.
3. Remove any attribute testing something not stated in the control description
   (scope creep).
4. PRESERVE TERMINOLOGY — do not rephrase established audit terms.
5. Financial controls: confirm a linkage/traceability attribute exists.
6. Any attribute that is genuinely conditional must state when N/A applies in its
   description. Only add an N/A clause where the attribute really is conditional —
   do not add one just because a word like "exception" appears.
7. Descriptions must be evidence-oriented and name something concrete to look for
   (a date, approval, report, amount, threshold, identifier, or reference).

── HARD COUNT LIMITS (a schema outside these ranges is rejected) ──
worksteps: 3 to 5.  attributes: 2 to 7.  sample_columns: 3 to 6.
If the draft exceeds a limit, consolidate or drop the least audit-significant
entries until it fits — never return a schema outside these ranges.
Do not add an "evidence files reviewed" column; that one is appended
automatically and does not count toward your 6.

Return ONLY JSON in exactly this shape:
""" + _OUTPUT_CONTRACT


# A single generation is 3 chained LLM calls per control, so one stalled
# request stalls the whole batch. Without a timeout the SDK waits
# indefinitely: the preview POST never returns, the progress bar sits at 0/N,
# and the user has no way to tell a slow run from a dead one. Bounding each
# call turns that hang into a per-control `generation_failed` the retry loop
# and quality gate already know how to report.
def _get_llm_client():
    return get_llm_client(max_retries=0)


def _control_context(control: dict[str, Any]) -> str:
    """Defect #4 fix: risk_description and risk_level are included — knowing
    WHY a control matters (fraud vs completeness vs accuracy risk) should
    shape which attributes get emphasized."""
    fields = [
        ("Control ID", control.get("control_id")),
        ("Control Description", control.get("control_description")),
        ("Control Type", control.get("control_type")),
        ("Control Nature", control.get("control_nature")),
        ("Control Frequency", control.get("control_frequency")),
        ("Control Owner", control.get("control_owner")),
        ("Process", control.get("process")),
        ("Risk Description", control.get("risk_description")),
        ("Risk Level", control.get("risk_level")),
    ]
    return "\n".join(f"{label}: {value}" for label, value in fields if (value or "").strip())


def _normalize_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerces an LLM schema into the canonical shape, re-sequencing
    attribute ids positionally (ids are always positional strings — see
    spec Section 1's warning about key desynchronization) and force-adding
    the evidence_files_reviewed sample column (spec Section 2.5)."""
    worksteps = [str(w).strip() for w in (raw.get("worksteps") or []) if str(w).strip()]

    attributes = []
    for i, a in enumerate(raw.get("attributes") or [], start=1):
        name = (a.get("name") or "").strip()
        description = (a.get("description") or "").strip()
        if not name and not description:
            continue
        attributes.append({"id": str(i), "name": name, "description": description})

    sample_columns = []
    seen_keys = set()
    for c in raw.get("sample_columns") or []:
        key = (c.get("key") or "").strip()
        header = (c.get("header") or "").strip()
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        sample_columns.append({"key": key, "header": header or key})

    if "evidence_files_reviewed" not in seen_keys:
        sample_columns.append({"key": "evidence_files_reviewed", "header": "Evidence Files Reviewed"})

    return {"worksteps": worksteps, "attributes": attributes, "sample_columns": sample_columns}


def _llm_schema_call(client, model, system_prompt: str, user_prompt: str, caller: str) -> dict[str, Any]:
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        # Generous budget: this is a reasoning model and schema output is
        # substantial — see llm_utils.parse_json_response for why a tight
        # budget here silently yields empty content.
        max_completion_tokens=6000,
        response_format={"type": "json_object"},
        # Per-request override. The client-level timeout bounds each HTTP
        # attempt, but this call is the slowest in the codebase (a reasoning
        # model filling a 6000-token JSON schema), so it gets its own ceiling
        # rather than inheriting the shared default.
        timeout=_SCHEMA_CALL_TIMEOUT_SECONDS,
    )
    # NOTE: max_retries is pinned to 0 on the client used here — see the
    # comment on _SCHEMA_CALL_TIMEOUT_SECONDS for why SDK-level retries would
    # multiply an already-long worst case.
    return parse_json_response(resp, caller=caller)


def generate_attributes_for_control(control: dict[str, Any]) -> dict[str, Any]:
    """Runs the 3-stage pipeline for one control. Always returns a dict with
    worksteps/attributes/sample_columns/quality_issues/generation_failed —
    never raises, never returns a silently-empty schema without the
    generation_failed flag set (Defect #13 fix)."""
    control_id = control.get("control_id", "")
    control_text = " ".join(
        str(control.get(f) or "") for f in ("control_description", "risk_description")
    )
    context = _control_context(control)

    client, model = _get_llm_client()
    if client is None:
        return {
            "worksteps": [], "attributes": [], "sample_columns": [],
            "quality_issues": ["No LLM configured — attributes must be authored manually for this control."],
            "generation_failed": True,
        }

    last_error: str | None = None
    for attempt in range(1, _MAX_GENERATION_ATTEMPTS + 1):
        try:
            # ── Stage 1: draft ────────────────────────────────────────
            draft = _normalize_schema(
                _llm_schema_call(
                    client, model, _RULEBOOK, f"CONTROL CONTEXT:\n{context}",
                    caller="attribute_engine.draft",
                )
            )
            if not draft["attributes"] or not draft["worksteps"]:
                raise ValueError("draft returned empty worksteps or attributes")

            # ── Stage 2: critic / refine ──────────────────────────────
            try:
                critiqued = _normalize_schema(
                    _llm_schema_call(
                        client, model, _CRITIC_RULEBOOK,
                        f"CONTROL CONTEXT:\n{context}\n\nDRAFT SCHEMA:\n{draft}",
                        caller="attribute_engine.critic",
                    )
                )
                # Never let the critic pass empty out a valid draft.
                schema = critiqued if critiqued["attributes"] and critiqued["worksteps"] else draft
            except Exception as e:
                logger.warning("Critic pass failed for %s: %s — keeping draft", control_id, e)
                schema = draft

            # ── Stage 3: deterministic gate + conditional repair ──────
            issues = check_schema_quality(schema, control_text)
            if issues:
                schema, issues = _attempt_repair(client, model, schema, issues, context, control_text, control_id)

            return {**schema, "quality_issues": issues, "generation_failed": False}

        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Attribute generation attempt %d/%d failed for %s: %s",
                attempt, _MAX_GENERATION_ATTEMPTS, control_id, e,
            )
            if attempt < _MAX_GENERATION_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    return {
        "worksteps": [], "attributes": [], "sample_columns": [],
        "quality_issues": [f"Attribute generation failed after {_MAX_GENERATION_ATTEMPTS} attempts: {last_error}"],
        "generation_failed": True,
    }


def _attempt_repair(
    client, model, schema: dict[str, Any], issues: list[str],
    context: str, control_text: str, control_id: str,
) -> tuple[dict[str, Any], list[str]]:
    """One repair call with the specific issues listed. Adopts the repaired
    schema only if it strictly reduces the issue count — never regresses.
    Whatever issues remain are returned so the caller can surface them
    (Defect #8 fix: unresolved findings must stay visible)."""
    try:
        repaired = _normalize_schema(
            _llm_schema_call(
                client, model, _CRITIC_RULEBOOK,
                f"CONTROL CONTEXT:\n{context}\n\nCURRENT SCHEMA:\n{schema}\n\n"
                f"QUALITY ISSUES TO FIX:\n" + "\n".join(f"- {i}" for i in issues),
                caller="attribute_engine.repair",
            )
        )
        if not repaired["attributes"] or not repaired["worksteps"]:
            return schema, issues
        repaired_issues = check_schema_quality(repaired, control_text)
        if len(repaired_issues) < len(issues):
            return repaired, repaired_issues
    except Exception as e:
        logger.warning("Repair pass failed for %s: %s — keeping pre-repair schema", control_id, e)
    return schema, issues


def _dedupe_key(control: dict[str, Any]) -> str:
    """Fingerprint of everything that actually reaches the prompt.

    Two controls with identical descriptions/type/nature/frequency produce
    identical schemas, so generating both is pure waste. ControlIris keys its
    cache on Control ID and therefore misses this — on an RCM with repeated
    boilerplate controls it pays full price for every duplicate. Keyed on the
    prompt inputs rather than the ID, so it collapses them.
    """
    parts = [
        control.get("control_description"),
        control.get("control_type"),
        control.get("control_nature"),
        control.get("control_frequency"),
        control.get("risk_description"),
        control.get("risk_level"),
        control.get("process"),
    ]
    joined = "\x1f".join((p or "").strip().lower() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def generate_attributes(
    controls: list[dict[str, Any]],
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parallel generation across controls, isolated per-control failures.

    `on_progress(control_id, done, total)` fires as each control lands, so the
    caller can stream progress — generation is several LLM round-trips per
    control and can run for minutes, far too long to show the user nothing.
    A raising callback must not cost us a completed schema, so it's guarded.
    """
    results: dict[str, dict[str, Any]] = {}
    total = len(controls)

    # Collapse duplicates before spending anything. Controls whose prompt
    # inputs are byte-identical get one generation and share the result — an
    # RCM with repeated boilerplate ("Access is reviewed quarterly") would
    # otherwise pay full price per copy.
    by_key: dict[str, list[dict[str, Any]]] = {}
    for c in controls:
        by_key.setdefault(_dedupe_key(c), []).append(c)
    unique = [group[0] for group in by_key.values()]
    if len(unique) < total:
        logger.info(
            "Attribute generation: %d control(s) collapsed to %d unique schema(s)", total, len(unique)
        )

    done = 0

    def _record(control_id: str, schema: dict[str, Any]) -> None:
        nonlocal done
        results[control_id] = schema
        done += 1
        if on_progress is not None:
            try:
                on_progress(control_id, done, total)
            except Exception:
                logger.debug("attribute progress callback failed", exc_info=True)

    # Each worker runs a control's calls in SEQUENCE (draft -> critic ->
    # optional repair), so the pool width is the number of concurrent calls,
    # not a multiplier on it — unlike testing_engine, which nests two pools.
    with ThreadPoolExecutor(max_workers=min(_CONTROL_WORKERS, max(len(unique), 1))) as pool:
        futures = {pool.submit(generate_attributes_for_control, c): _dedupe_key(c) for c in unique}
        for future in as_completed(futures):
            key = futures[future]
            group = by_key[key]
            try:
                schema = future.result()
            except Exception as e:
                logger.warning("Attribute generation raised for %s: %s", group[0]["control_id"], e)
                schema = {
                    "worksteps": [], "attributes": [], "sample_columns": [],
                    "quality_issues": [f"Attribute generation raised: {e}"],
                    "generation_failed": True,
                }
            # Every control in the group gets its own copy: schemas are
            # mutated independently downstream (edits, approval, freezing),
            # so sharing one dict would let an edit on one control silently
            # rewrite its duplicates.
            for c in group:
                _record(c["control_id"], copy.deepcopy(schema))
    return results


def resequence_attribute_ids(attributes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attribute ids are positional strings, always. Any mutation that
    changes list order/length must call this — the evaluation LLM's
    attribute_results dict is keyed by these exact ids."""
    return [{**a, "id": str(i)} for i, a in enumerate(attributes, start=1)]
