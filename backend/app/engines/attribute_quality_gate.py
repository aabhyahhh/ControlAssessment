"""
Deterministic (non-LLM) quality gate for control testing attribute schemas —
a direct port of ATTRIBUTE_GENERATION_ENGINE_SPEC.md Section 4.

Kept in its own module because, per that spec's Defect #1 (the single most
likely cause of "attributes look right after generation but wrong after any
edit"), this gate must run on EVERY mutation path — fresh generation, chat
edits, and Excel re-upload — not just at generation time. Being importable
standalone makes that hard to forget.
"""

from __future__ import annotations

import re
from typing import Any

# Section 4 thresholds. The "policy" variants apply when a process policy
# document grounded the generation (more source material legitimately
# supports more attributes). This build has no per-process policy upload
# yet, so `policy_used` is always False today — the wider ranges are kept
# because the SOP ingested in Phase 3 is the natural future source for it,
# and the generation prompts already state the narrow limits verbatim.
WORKSTEP_RANGE = (3, 5)
WORKSTEP_RANGE_POLICY = (3, 10)
ATTRIBUTE_RANGE = (2, 7)
ATTRIBUTE_RANGE_POLICY = (2, 25)
SAMPLE_COLUMN_RANGE = (3, 6)
SAMPLE_COLUMN_RANGE_POLICY = (3, 10)

GENERIC_NAME_BLOCKLIST = {
    "properly approved",
    "review done",
    "reviewed documentation",
    "evidence sufficient",
    "authorization obtained",
    "control performed",
    "status check",
    "checked control",
}

# Matched as word-stem PREFIXES, not exact tokens — an attribute saying
# "dated", "approval", "signed", or "matched" is just as evidence-anchored
# as one saying "date"/"approve"/"sign"/"match". Exact-token matching here
# produced false positives on well-written attributes, which trains users
# to ignore the gate's findings.
EVIDENCE_ANCHOR_STEMS = (
    "timestamp", "date", "dated", "user", "log", "report", "workflow",
    "approv", "sign", "amount", "number", "threshold", "limit", "referenc",
    "linkage", "trace", "source", "verif", "document", "validat", "comply",
    "complian", "doa", "support", "restrict", "obtain", "maintain", "process",
    "record", "classif", "match", "mark", "initial", "authoriz", "attach",
    "identif", "balance", "invoice", "statement", "schedule", "receipt",
)

# Short stems that would over-match as substrings (e.g. "id" inside
# "evidence") are checked as whole tokens only.
EVIDENCE_ANCHOR_EXACT = {"id", "ids"}

CONDITIONAL_KEYWORDS = (
    "discrepanc", "variance", "escalat", "exception", "resolution", "mismatch", "dispute",
)

THRESHOLD_LANGUAGE = (">", "<", "threshold", "limit", "minimum", "maximum", "within", "%")

_STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "for", "in", "is", "are", "be", "on", "per"}

_MIN_NAME_WORDS = 2
_MIN_DESCRIPTION_CHARS = 35
_JACCARD_OVERLAP_THRESHOLD = 0.75

# Appended by the engine for every control (spec Section 2.5), not chosen by
# the LLM — so it must not count against the LLM's sample-column budget,
# which would otherwise make every schema fail the ceiling by one.
SYSTEM_SAMPLE_COLUMN_KEY = "evidence_files_reviewed"


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _states_when_na_applies(description: str) -> bool:
    """Accepts every ordinary spelling of "not applicable". Matching only the
    literal "n/a" false-flags correctly-written attributes ("NA if none
    existed", "Not applicable when ..."), which trains users to ignore the
    gate's findings."""
    lowered = description.lower()
    if "n/a" in lowered or "not applicable" in lowered:
        return True
    return "na" in _tokens(lowered)


def _has_evidence_anchor(description: str) -> bool:
    tokens = _tokens(description)
    if tokens & EVIDENCE_ANCHOR_EXACT:
        return True
    return any(token.startswith(stem) for token in tokens for stem in EVIDENCE_ANCHOR_STEMS)


def check_schema_quality(
    schema: dict[str, Any],
    control_text: str = "",
    *,
    policy_used: bool = False,
) -> list[str]:
    """Returns a list of human-readable issue strings — empty means clean.
    Never raises and never mutates the schema; callers decide what to do
    with the findings (repair pass, surface to the user, or both)."""
    issues: list[str] = []

    worksteps = schema.get("worksteps") or []
    attributes = schema.get("attributes") or []
    sample_columns = schema.get("sample_columns") or []
    authored_columns = [c for c in sample_columns if (c.get("key") or "") != SYSTEM_SAMPLE_COLUMN_KEY]

    ws_min, ws_max = WORKSTEP_RANGE_POLICY if policy_used else WORKSTEP_RANGE
    at_min, at_max = ATTRIBUTE_RANGE_POLICY if policy_used else ATTRIBUTE_RANGE
    sc_min, sc_max = SAMPLE_COLUMN_RANGE_POLICY if policy_used else SAMPLE_COLUMN_RANGE

    if not (ws_min <= len(worksteps) <= ws_max):
        issues.append(f"Worksteps count is {len(worksteps)}; expected between {ws_min} and {ws_max}.")
    if not (at_min <= len(attributes) <= at_max):
        issues.append(f"Attributes count is {len(attributes)}; expected between {at_min} and {at_max}.")
    if not (sc_min <= len(authored_columns) <= sc_max):
        issues.append(
            f"Sample columns count is {len(authored_columns)}; expected between {sc_min} and {sc_max} "
            f"(excluding the auto-added '{SYSTEM_SAMPLE_COLUMN_KEY}' column)."
        )

    # ── Per-attribute checks ──────────────────────────────────────────
    for i, attr in enumerate(attributes, start=1):
        name = (attr.get("name") or "").strip()
        description = (attr.get("description") or "").strip()
        label = f"Attribute {i} ('{name or 'unnamed'}')"

        if len(name.split()) < _MIN_NAME_WORDS:
            issues.append(f"{label}: name must be at least {_MIN_NAME_WORDS} words.")

        if name.lower() in GENERIC_NAME_BLOCKLIST:
            issues.append(f"{label}: name is generic — it must reference this control's specific action/system/threshold.")

        if len(description) < _MIN_DESCRIPTION_CHARS:
            issues.append(
                f"{label}: description is {len(description)} characters; must be at least {_MIN_DESCRIPTION_CHARS}."
            )

        if not _has_evidence_anchor(description):
            issues.append(
                f"{label}: description names no concrete evidence anchor "
                "(e.g. a date, approval, report, amount, threshold, or reference to look for)."
            )

        combined = f"{name} {description}".lower()
        if any(k in combined for k in CONDITIONAL_KEYWORDS) and not _states_when_na_applies(description):
            issues.append(
                f"{label}: reads as conditional but its description never says when N/A applies "
                "— that produces false 'No' verdicts on samples where the condition never triggers."
            )

    # ── Cross-attribute overlap ───────────────────────────────────────
    for i in range(len(attributes)):
        for j in range(i + 1, len(attributes)):
            name_i = (attributes[i].get("name") or "").strip()
            name_j = (attributes[j].get("name") or "").strip()
            if _jaccard(_tokens(name_i), _tokens(name_j)) >= _JACCARD_OVERLAP_THRESHOLD:
                issues.append(
                    f"Attributes {i + 1} ('{name_i}') and {j + 1} ('{name_j}') overlap heavily — "
                    "attributes must be mutually exclusive."
                )

    # ── Threshold-hint coverage ───────────────────────────────────────
    lowered_control = (control_text or "").lower()
    if any(t in lowered_control for t in THRESHOLD_LANGUAGE):
        mentions_threshold = any(
            any(t in (a.get("description") or "").lower() for t in THRESHOLD_LANGUAGE) for a in attributes
        )
        if not mentions_threshold:
            issues.append(
                "The control text states a threshold/limit, but no attribute description references it — "
                "an evaluator can't distinguish 'checked but failed the bar' from 'not checked'."
            )

    return issues
