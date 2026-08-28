"""
Risk-level inference via weighted Probability x Impact scoring.

Replicates ControlIris's `infer_risk_level.py` model, with the weights and
band thresholds exposed as a user choice (default or custom) rather than
hardcoded:

    Score = P_weight x I_weight,  then mapped through band thresholds.

    Defaults: Low=1, Medium=3, High=6
              Score <=5 -> Low, <=17 -> Medium, <=35 -> High, else Critical

The 3x3 risk matrix is NOT a separate hardcoded artefact — it is derived
from the weights and bands every time, so changing either automatically
changes the matrix. "Critical" is a system-computed escalation (only
High x High under the defaults), never a user-selectable input.

Inference cascade per control:
  1. Compute   — both Probability and Impact present -> pure arithmetic.
  2. Infer P/I — one or both missing -> LLM infers them, then compute.
  3. Direct    — no usable signal -> LLM infers the level directly.
  4. Default   — LLM unavailable/failed -> Medium, flagged low-confidence.

Every inferred value carries {value, source, confidence, reasoning} so an
auditor can tell a computed rating from an inferred one.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.engines.llm_utils import get_llm_client, parse_json_response

logger = logging.getLogger("engines.risk_inference")

# ── Default weighted score values ─────────────────────────────────────────
DEFAULT_SCORE_MAP: dict[str, int] = {"low": 1, "medium": 3, "high": 6}

# (upper_bound_inclusive, label); anything above the last band is Critical.
DEFAULT_BANDS: list[tuple[int, str]] = [(5, "Low"), (17, "Medium"), (35, "High")]

VALID_INPUTS = ("Low", "Medium", "High")
VALID_OUTPUTS = ("Low", "Medium", "High", "Critical")

_INPUT_ALIASES = {
    "low": "low", "l": "low", "minor": "low", "1": "low",
    "medium": "medium", "med": "medium", "m": "medium", "moderate": "medium", "2": "medium",
    "high": "high", "h": "high", "major": "high", "significant": "high", "3": "high",
    "critical": "high", "very high": "high", "4": "high",
}


def normalize_pi_input(raw: Any) -> str:
    """Normalizes a raw probability/impact cell to low|medium|high, or ""."""
    if raw is None:
        return ""
    return _INPUT_ALIASES.get(str(raw).strip().lower(), "")


def score_to_level(score: int, bands: list[tuple[int, str]] | None = None) -> str:
    for threshold, label in (bands or DEFAULT_BANDS):
        if score <= threshold:
            return label
    return "Critical"


def build_risk_matrix(
    score_map: dict[str, int] | None = None,
    bands: list[tuple[int, str]] | None = None,
) -> dict[str, str]:
    """The full 3x3 matrix, derived from weights+bands rather than hardcoded.
    Keys are "probability|impact" so the result is JSON-serializable."""
    sm = score_map or DEFAULT_SCORE_MAP
    matrix: dict[str, str] = {}
    for p in ("low", "medium", "high"):
        for i in ("low", "medium", "high"):
            matrix[f"{p}|{i}"] = score_to_level(sm[p] * sm[i], bands)
    return matrix


def compute_risk_score(
    probability: str,
    impact: str,
    score_map: dict[str, int] | None = None,
    bands: list[tuple[int, str]] | None = None,
) -> tuple[int, str]:
    """Returns (score, level); (0, "") if either input is unusable."""
    sm = score_map or DEFAULT_SCORE_MAP
    p, i = normalize_pi_input(probability), normalize_pi_input(impact)
    p_score, i_score = sm.get(p, 0), sm.get(i, 0)
    if not p_score or not i_score:
        return 0, ""
    score = p_score * i_score
    return score, score_to_level(score, bands)


def validate_weighting(score_map: dict[str, Any], bands: list[Any]) -> tuple[dict[str, int], list[tuple[int, str]]]:
    """Validates a user-supplied weighting, raising ValueError with a
    human-readable message. Enforces the orderings that make the model
    meaningful: Low < Medium < High weights, and strictly ascending band
    thresholds — otherwise the derived matrix would be nonsense (e.g. a
    'High/High' control scoring Low)."""
    cleaned: dict[str, int] = {}
    for key in ("low", "medium", "high"):
        if key not in score_map:
            raise ValueError(f"Weighting is missing the '{key}' weight.")
        try:
            value = int(score_map[key])
        except (TypeError, ValueError):
            raise ValueError(f"Weight for '{key}' must be a whole number.")
        if value < 1:
            raise ValueError(f"Weight for '{key}' must be at least 1.")
        cleaned[key] = value

    if not (cleaned["low"] < cleaned["medium"] < cleaned["high"]):
        raise ValueError(
            f"Weights must increase Low < Medium < High (got Low={cleaned['low']}, "
            f"Medium={cleaned['medium']}, High={cleaned['high']})."
        )

    cleaned_bands: list[tuple[int, str]] = []
    for entry in bands:
        if isinstance(entry, dict):
            threshold, label = entry.get("threshold"), entry.get("label")
        else:
            threshold, label = entry[0], entry[1]
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            raise ValueError(f"Band threshold '{threshold}' must be a whole number.")
        if not label:
            raise ValueError("Every band needs a label.")
        cleaned_bands.append((threshold, str(label)))

    if not cleaned_bands:
        raise ValueError("At least one band threshold is required.")
    if any(a[0] >= b[0] for a, b in zip(cleaned_bands, cleaned_bands[1:])):
        raise ValueError("Band thresholds must increase from lowest to highest.")

    max_score = cleaned["high"] * cleaned["high"]
    if cleaned_bands[-1][0] >= max_score:
        raise ValueError(
            f"The top band threshold ({cleaned_bands[-1][0]}) must be below the maximum possible score "
            f"({max_score} = High x High), otherwise no control can ever reach Critical."
        )
    return cleaned, cleaned_bands


# ═══════════════════════════════════════════════════════════════════════════
#  LLM inference of missing Probability / Impact / Risk Level
# ═══════════════════════════════════════════════════════════════════════════


def _get_llm_client():
    return get_llm_client()


def _llm_infer_pi(control: dict[str, Any]) -> dict[str, Any]:
    """Asks the LLM for Probability and Impact separately (not the level),
    so the user's own weighting — not the model's opinion — decides the
    final rating."""
    client, model = _get_llm_client()
    if client is None:
        return {}

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an audit risk-assessment assistant. Given a control and its risk, rate the "
                        "inherent RISK PROBABILITY (how likely the risk is to occur without the control) and "
                        "RISK IMPACT (how severe the consequence would be) as exactly Low, Medium, or High. "
                        "Rate the two independently — a rare but catastrophic risk is Low probability / High "
                        "impact. Do NOT return an overall risk level; only probability and impact. "
                        'Return ONLY JSON: {"probability": "Low|Medium|High", "impact": "Low|Medium|High", '
                        '"reasoning": "one sentence"}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Control ID: {control.get('control_id')}\n"
                        f"Control Description: {control.get('control_description') or 'n/a'}\n"
                        f"Risk Description: {control.get('risk_description') or 'n/a'}\n"
                        f"Process: {control.get('process') or 'n/a'}"
                    ),
                },
            ],
            max_completion_tokens=1500,
            response_format={"type": "json_object"},
        )
        parsed = parse_json_response(resp, caller="risk_inference._llm_infer_pi")
        probability = normalize_pi_input(parsed.get("probability"))
        impact = normalize_pi_input(parsed.get("impact"))
        if not probability or not impact:
            return {}
        return {"probability": probability, "impact": impact, "reasoning": parsed.get("reasoning", "")}
    except Exception as e:
        logger.warning("P/I inference failed for %s: %s", control.get("control_id"), e)
        return {}


def infer_one(
    control: dict[str, Any],
    score_map: dict[str, int],
    bands: list[tuple[int, str]],
) -> dict[str, Any]:
    """Runs the cascade for a single control and returns a full audit trail
    of how the rating was reached."""
    control_id = control["control_id"]
    raw = control.get("raw_row") or {}
    existing_p = normalize_pi_input(raw.get("risk_probability") or control.get("risk_probability"))
    existing_i = normalize_pi_input(raw.get("risk_impact") or control.get("risk_impact"))

    # 1. Both present -> pure computation, no LLM.
    if existing_p and existing_i:
        score, level = compute_risk_score(existing_p, existing_i, score_map, bands)
        return {
            "control_id": control_id, "value": level, "probability": existing_p.title(),
            "impact": existing_i.title(), "score": score, "source": "Computed",
            "confidence": "High",
            "reasoning": f"{existing_p.title()} probability x {existing_i.title()} impact = score {score}.",
        }

    # 2. One or both missing -> infer P/I, then apply the user's weighting.
    inferred = _llm_infer_pi(control)
    if inferred:
        probability = existing_p or inferred["probability"]
        impact = existing_i or inferred["impact"]
        score, level = compute_risk_score(probability, impact, score_map, bands)
        which = "probability and impact" if not existing_p and not existing_i else (
            "probability" if not existing_p else "impact"
        )
        return {
            "control_id": control_id, "value": level, "probability": probability.title(),
            "impact": impact.title(), "score": score, "source": "Inferred P/I + Computed",
            "confidence": "Medium",
            "reasoning": (
                f"Inferred {which} from the control/risk description "
                f"({inferred.get('reasoning', '').strip()}); "
                f"{probability.title()} x {impact.title()} = score {score}."
            ).strip(),
        }

    # 3. LLM unavailable or failed -> conservative default, clearly flagged.
    return {
        "control_id": control_id, "value": "Medium", "probability": "", "impact": "", "score": 0,
        "source": "Default (inference unavailable)", "confidence": "Low",
        "reasoning": "Could not infer probability/impact; defaulted to Medium pending your review.",
    }


def infer_risk_levels(
    controls: list[dict[str, Any]],
    score_map: dict[str, int] | None = None,
    bands: list[tuple[int, str]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Infers a risk level for every control that lacks one. Parallelized with
    per-control failure isolation, so one bad control can't sink the batch."""
    sm = score_map or DEFAULT_SCORE_MAP
    b = bands or DEFAULT_BANDS

    needs_inference = [c for c in controls if not normalize_pi_input(c.get("risk_level"))
                       and not str(c.get("risk_level") or "").strip()]
    results: dict[str, dict[str, Any]] = {}
    if not needs_inference:
        return results

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(infer_one, c, sm, b): c["control_id"] for c in needs_inference}
        for future in as_completed(futures):
            control_id = futures[future]
            try:
                results[control_id] = future.result()
            except Exception as e:
                logger.warning("Risk inference raised for %s: %s", control_id, e)
                results[control_id] = {
                    "control_id": control_id, "value": "Medium", "probability": "", "impact": "",
                    "score": 0, "source": "Default (inference unavailable)", "confidence": "Low",
                    "reasoning": f"Inference raised an error: {e}",
                }
    return results
