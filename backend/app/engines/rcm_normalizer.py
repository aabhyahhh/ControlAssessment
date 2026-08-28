"""
RCM normalizer — header detection, marker normalization, and column mapping
to the generalized canonical schema. Ported from ControlIris's
flask-api/engines/rcm_reader.py, generalized: canonical targets are the
domain-agnostic Layer A field set (control_id, risk_level, ...) instead of
SOX-specific display names, and framework-specific aliases are dropped
rather than hardcoded.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import get_settings
from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.rcm_normalizer")

# ═══════════════════════════════════════════════════════════════════════════
#  Canonical schema (Layer A)
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED_FIELDS: dict[str, str] = {
    "control_id": "Control ID",
    "control_description": "Control Description",
}

RECOMMENDED_FIELDS: dict[str, str] = {
    "risk_description": "Risk Description",
    "risk_level": "Risk Level",
    "control_type": "Control Type",
    "control_nature": "Control Nature",
    "control_frequency": "Control Frequency",
    "control_owner": "Control Owner",
    "process": "Process",
}

ALL_FIELDS: dict[str, str] = {**REQUIRED_FIELDS, **RECOMMENDED_FIELDS}
REQUIRED_CANONICAL = list(REQUIRED_FIELDS.keys())
ALL_CANONICAL = list(ALL_FIELDS.keys())

# ═══════════════════════════════════════════════════════════════════════════
#  1. Header-row detection
# ═══════════════════════════════════════════════════════════════════════════

HEADER_HINTS = {
    "process", "sub process", "subprocess", "sub-process",
    "control objective", "risk id", "risk title",
    "risk description", "control id", "control description",
    "control owner", "control rating", "nature of control",
    "control type", "control frequency", "risk level",
    "count of samples", "entity", "location",
    "risk no", "risk number", "risk #",
    "control no", "control number", "control #",
    "control narrative", "control activity",
    "key or non key", "key or non key control",
    "key / non key", "key/non-key", "key control",
    "significant risk", "risk category", "risk rating",
    "performed by", "frequency", "preventive/detective",
    "p/d", "manual/automated", "automation",
    "sample size", "assertion",
}

HEADER_PARTIAL_TOKENS = (
    "process", "risk", "control", "frequency", "owner",
    "system", "assertion", "entity", "location", "objective",
    "description", "narrative", "key", "significant",
)


def _score_header_row(values: list[Any]) -> int:
    score = 0
    for v in values:
        s = str(v).strip().lower()
        if not s or s in ("nan", "none"):
            continue
        if s in HEADER_HINTS:
            score += 3
        elif any(tok in s for tok in HEADER_PARTIAL_TOKENS):
            score += 1
    return score


# ═══════════════════════════════════════════════════════════════════════════
#  2. Marker normalization
# ═══════════════════════════════════════════════════════════════════════════

_YES_MARKERS = frozenset({
    "●", "•", "⬤", "◉", "◆", "✓", "✔", "☑", "☒",
    "■", "▪", "▸", "►", "y", "yes", "true", "1", "x",
})
_NO_MARKERS = frozenset({"○", "◯", "◇", "□", "☐", "n", "no", "false", "0", "-"})

_MARKER_RE = re.compile(
    r"^[\s]*([●•⬤◉◆✓✔☑☒■▪▸►○◯◇□☐]|[Yy]es|[Nn]o|[Tt]rue|[Ff]alse|[Xx])[\s]*$",
    re.UNICODE,
)


def _normalize_markers(df: pd.DataFrame) -> pd.DataFrame:
    def _convert_cell(val):
        if not isinstance(val, str):
            return val
        stripped = val.strip().lower()
        if not stripped or not _MARKER_RE.match(val):
            return val
        if stripped in _YES_MARKERS:
            return "Yes"
        if stripped in _NO_MARKERS:
            return "No"
        return val

    return df.map(_convert_cell)


# ═══════════════════════════════════════════════════════════════════════════
#  3. Column normalization — alias table (Pass 1) + LLM fuzzy match (Pass 2)
# ═══════════════════════════════════════════════════════════════════════════

_ALIAS_MAP: dict[str, str] = {
    # control_id
    "control id": "control_id", "ctrl id": "control_id", "control #": "control_id",
    "control no": "control_id", "control no.": "control_id", "control number": "control_id",
    "control ref": "control_id",
    # control_description
    "control description": "control_description", "control activity": "control_description",
    "control narrative": "control_description", "control detail": "control_description",
    # risk_description
    "risk description": "risk_description", "risk desc": "risk_description",
    "risk narrative": "risk_description", "risk detail": "risk_description",
    "risk title": "risk_description", "risk name": "risk_description", "risk summary": "risk_description",
    # risk_level
    "risk level": "risk_level", "risk rating": "risk_level", "inherent risk": "risk_level",
    "risk severity": "risk_level", "risk category": "risk_level", "significant risk": "risk_level",
    # control_type (preventive/detective)
    "control type": "control_type", "preventive/detective": "control_type", "p/d": "control_type",
    "nature of control": "control_type",
    # control_nature (manual/automated)
    "control nature": "control_nature", "manual/automated": "control_nature",
    "manual / automated": "control_nature", "automation": "control_nature",
    "manual/automated/itdm": "control_nature",
    # control_frequency
    "control frequency": "control_frequency", "frequency": "control_frequency",
    "frequency of control": "control_frequency", "periodicity": "control_frequency",
    # control_owner
    "control owner": "control_owner", "owner": "control_owner", "performed by": "control_owner",
    "responsible": "control_owner",
    # process
    "process": "process", "sub process": "process", "subprocess": "process",
    "sub-process": "process", "mega process": "process", "business process": "process",
    "cycle": "process", "process area": "process", "activity": "process",
}

_LLM_SYSTEM_PROMPT = (
    "You are an expert data-mapping assistant for control-assessment RCM (Risk Control Matrix) "
    "spreadsheets, used across any domain (SOX, ITGC, vendor risk, ISO 27001, operational risk).\n"
    "Given INPUT column names from a user's spreadsheet and REQUIRED canonical field names, map "
    "each input column to the best-matching required field.\n\n"
    "RULES:\n"
    "1. Only map when confident the columns represent the same concept.\n"
    "2. If an input column does not match any required field, set its value to null — it is kept "
    "as a passthrough column, not forced into a generic bucket.\n"
    "3. Each required field can be used AT MOST once.\n"
    "4. Columns ending in 'No.'/'#'/'Number' are usually numeric IDs, not descriptive text — do not "
    "map them to description fields.\n"
    "5. Domain-specific columns (e.g. 'COSO Objective', 'IFC Component', 'Vendor Tier', 'Data "
    "Classification') that don't correspond to a required field must be left as passthrough (null).\n"
    "6. Consider typos and synonyms; match on meaning.\n\n"
    "Return ONLY JSON: {\"mappings\": {\"<input_col>\": \"<required_field_or_null>\", ...}}"
)


def _get_llm_client():
    if not get_settings().azure_openai_api_key:
        logger.warning("No Azure OpenAI API key configured — skipping LLM column match")
    return get_llm_client()


def _llm_match(remaining_input: list[str], unmatched_targets: list[str], df: pd.DataFrame) -> dict[str, str]:
    if not remaining_input or not unmatched_targets:
        return {}

    client, model = _get_llm_client()
    if client is None:
        return {}

    sample_hint = ""
    try:
        sample_rows = df[remaining_input].head(2).to_dict(orient="records")
        sample_hint = (
            f"\n\nSAMPLE DATA (first rows for the input columns above):\n"
            f"{json.dumps(sample_rows, default=str, ensure_ascii=False)}"
        )
    except Exception:
        pass

    user_prompt = (
        f"INPUT columns:\n{json.dumps(remaining_input)}\n\n"
        f"REQUIRED fields:\n{json.dumps(unmatched_targets)}\n\n"
        f"Map each input column to the best matching required field, or null if no match.{sample_hint}"
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            # Reasoning-model budget — see llm_utils.parse_json_response's
            # docstring for why this needs real headroom, not just enough
            # for the visible JSON output.
            max_completion_tokens=2500,
            response_format={"type": "json_object"},
        )
        raw_mappings = parse_json_response(resp, caller="rcm_normalizer._llm_match").get("mappings", {})

        valid_targets = set(unmatched_targets)
        used: set[str] = set()
        llm_mapped: dict[str, str] = {}
        for inp, target in raw_mappings.items():
            if target and target in valid_targets and target not in used:
                llm_mapped[inp] = target
                used.add(target)
        logger.info("LLM column match resolved %d columns", len(llm_mapped))
        return llm_mapped
    except Exception as e:
        logger.warning("LLM column mapping failed: %s — continuing with alias-match only", e)
        return {}


def _try_alias_match(input_columns: list[str]) -> tuple[dict[str, str], list[str]]:
    mapped: dict[str, str] = {}
    remaining: list[str] = []
    used_canonical: set[str] = set()

    for col in input_columns:
        lookup = col.strip().lower()
        canonical = _ALIAS_MAP.get(lookup)
        if canonical and canonical not in used_canonical:
            mapped[col] = canonical
            used_canonical.add(canonical)
        else:
            remaining.append(col)

    return mapped, remaining


def _normalize_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], list[str], list[str]]:
    """Returns (df, column_map, passthrough, still_missing)."""
    input_columns = [str(c).strip() for c in df.columns]

    exact_mapped, remaining = _try_alias_match(input_columns)
    resolved = set(exact_mapped.values())
    unmatched_targets = [c for c in ALL_CANONICAL if c not in resolved]

    llm_mapped: dict[str, str] = {}
    if remaining and unmatched_targets:
        llm_mapped = _llm_match(remaining, unmatched_targets, df)

    full_map = {**exact_mapped, **llm_mapped}
    passthrough = [c for c in input_columns if c not in full_map]
    all_resolved = set(full_map.values())
    still_missing = [c for c in REQUIRED_CANONICAL if c not in all_resolved] + [
        c for c in RECOMMENDED_FIELDS if c not in all_resolved
    ]

    if full_map:
        df = df.rename(columns=full_map)

    return df, full_map, passthrough, still_missing


# ═══════════════════════════════════════════════════════════════════════════
#  4. Forward-fill (cardinality-gated, generalized — no fixed column whitelist)
# ═══════════════════════════════════════════════════════════════════════════

_GROUPING_FIELD_NAMES = {"process", "risk_level", "control_type", "control_nature", "control_frequency"}


def _forward_fill_grouping_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill columns that behave like merged-cell groupings: non-null
    values repeat in blocks and cardinality is low relative to row count.
    Never forward-fills per-row-unique columns (IDs, descriptions)."""
    n_rows = len(df)
    if n_rows == 0:
        return df

    for col in df.columns:
        if not df[col].isna().any():
            continue
        col_lower = str(col).strip().lower()
        if col_lower in ("control_id", "control_description", "risk_description"):
            continue

        non_null = df[col].dropna()
        if non_null.empty:
            continue
        cardinality_ratio = non_null.nunique() / max(len(non_null), 1)
        is_grouping_name = col_lower in _GROUPING_FIELD_NAMES
        is_low_cardinality = cardinality_ratio < 0.5 and non_null.nunique() < max(n_rows * 0.3, 3)

        if is_grouping_name or is_low_cardinality:
            df[col] = df[col].ffill()

    return df


# ═══════════════════════════════════════════════════════════════════════════
#  5. Public entry point
# ═══════════════════════════════════════════════════════════════════════════


def normalize_rcm_file(file_path: Path) -> dict[str, Any]:
    """Full pipeline: header detection -> forward-fill -> marker normalization
    -> column mapping. Returns {df, column_map, passthrough, still_missing,
    header_row_index}."""
    suffix = file_path.suffix.lower()

    if suffix == ".csv":
        df = pd.read_csv(file_path, dtype=str)
        header_row_index = 1
    else:
        probe = pd.read_excel(file_path, sheet_name=0, header=None, dtype=str, nrows=15)
        best_idx, best_score = 0, -1
        for idx in range(len(probe)):
            score = _score_header_row(probe.iloc[idx].tolist())
            if score > best_score:
                best_idx, best_score = idx, score

        df = pd.read_excel(file_path, sheet_name=0, header=best_idx, dtype=str)
        df = df.dropna(axis=0, how="all")
        unnamed = [c for c in df.columns if str(c).strip().lower().startswith("unnamed")]
        if unnamed:
            df = df.drop(columns=unnamed, errors="ignore")
        df.columns = [str(c).strip() for c in df.columns]
        header_row_index = best_idx + 1

    df = _forward_fill_grouping_columns(df)
    df = _normalize_markers(df)
    df, column_map, passthrough, still_missing = _normalize_columns(df)

    # Drop rows with no control_id and no control_description (trailing/empty rows).
    key_cols = [c for c in ("control_id", "control_description") if c in df.columns]
    if key_cols:
        empty_mask = df[key_cols].apply(
            lambda col: col.isna() | (col.astype(str).str.strip().isin(["", "nan", "none", "null"]))
        ).all(axis=1)
        if empty_mask.any():
            df = df[~empty_mask].reset_index(drop=True)

    return {
        "df": df,
        "column_map": column_map,
        "passthrough": passthrough,
        "still_missing": still_missing,
        "header_row_index": header_row_index,
    }
