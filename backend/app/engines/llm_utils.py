"""
Shared helper for parsing Azure OpenAI chat-completion JSON responses.
Reasoning models (e.g. gpt-5.x) can spend the entire max_completion_tokens
budget on hidden reasoning tokens before producing any visible output,
leaving message.content empty even on a normal "stop" finish_reason. Every
LLM call site in this codebase parses content with `json.loads(content or
"{}")`, which silently treats an empty/truncated response the same as "the
model legitimately returned nothing" — so a too-small token budget looks
identical to the LLM correctly saying "no data" and never gets noticed.
This helper logs that distinction instead of hiding it.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.config import get_settings

logger = logging.getLogger("engines.llm_utils")


def parse_json_response(resp: Any, *, caller: str) -> dict:
    """Extracts and JSON-parses the first choice's message content, logging
    a warning (not raising) if the content is empty despite a normal
    finish_reason — the signature of a token-budget-truncated reasoning
    response rather than a deliberate empty answer."""
    choice = resp.choices[0]
    content = choice.message.content or ""
    if not content.strip():
        logger.warning(
            "%s: LLM returned empty content (finish_reason=%s) — likely max_completion_tokens "
            "too low for a reasoning model to leave room for visible output after its hidden "
            "reasoning tokens. Falling back to default handling for this call.",
            caller, choice.finish_reason,
        )
        return {}
    return json.loads(content)


# ── Request bounds ──────────────────────────────────────────────────────
# Every LLM call in this codebase is made inside a blocking HTTP request
# handler, so an unbounded call doesn't just stall one engine — it holds the
# whole request open. Left untimed, the attribute-preview POST hung
# indefinitely with its progress stuck at 0/N, which is indistinguishable to
# the user from a dead server.
#
# These bounds turn a stall into an ordinary failure that each engine's
# existing retry/fallback path already handles.
LLM_TIMEOUT_SECONDS = 120.0

# Deliberately 1, not the SDK default of 2.
#
# These are reasoning-model calls that legitimately take 40-60s. The SDK
# retries on timeout WITHOUT surfacing anything, so a generous max_retries
# silently multiplies the worst case: attribute generation, which already
# retries 3 times over a 3-stage pipeline, went from ~45s per call to a run
# that had not finished after 15 minutes and logged nothing to explain it.
#
# One retry still absorbs a transient network blip. Engines that do their own
# retrying (attribute_engine) should pass max_retries=0 and rely on that,
# so every attempt is logged and counted in one place.
LLM_MAX_RETRIES = 1


# Guards the cold-start build. Bare lru_cache is thread-SAFE but not
# thread-ATOMIC: N threads arriving on an empty cache all miss and all build
# a client, and the losers' connection pools are simply discarded. Every
# engine here fans out into a ThreadPoolExecutor immediately, so that race is
# the normal case, not a corner case. Double-checked under the lock.
_client_lock = threading.Lock()
_clients: dict[tuple, Any] = {}


def _build_client(api_key: str, endpoint: str, api_version: str, max_retries: int):
    from openai import AzureOpenAI

    return AzureOpenAI(
        api_key=api_key,
        azure_endpoint=endpoint,
        api_version=api_version,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=max_retries,
    )


def _cached_client(api_key: str, endpoint: str, api_version: str, max_retries: int):
    """One AzureOpenAI instance per (credential, retry policy) combination.

    Constructing a client builds a fresh httpx connection pool, so a client
    built per control — which is what every engine used to do — throws away
    the keep-alive connection and pays a new TLS handshake on every single
    call. Measured at ~1.3s of pure overhead per call; across a 12-control
    RCM with a multi-stage attribute pipeline that is minutes of dead time.

    Keyed on the credential so a settings change still yields a new client,
    and on max_retries because attribute_engine deliberately runs with 0
    (it does its own logged retrying) while everything else uses the shared
    default. The AzureOpenAI client is thread-safe, which is what makes
    sharing one across a thread pool sound in the first place.
    """
    key = (api_key, endpoint, api_version, max_retries)
    # Fast path: no lock once built, which is every call after the first.
    client = _clients.get(key)
    if client is not None:
        return client
    with _client_lock:
        # Re-check: another thread may have built it while we waited.
        client = _clients.get(key)
        if client is None:
            client = _build_client(*key)
            _clients[key] = client
        return client


def get_llm_client(max_retries: int = LLM_MAX_RETRIES):
    """Shared, connection-pooled client. Returns (client, deployment), with
    client None when no API key is configured — every engine already treats
    that as "fall back to deterministic behaviour"."""
    settings = get_settings()
    if not settings.azure_openai_api_key:
        return None, settings.azure_openai_deployment
    client = _cached_client(
        settings.azure_openai_api_key,
        settings.azure_openai_endpoint,
        settings.azure_openai_api_version,
        max_retries,
    )
    return client, settings.azure_openai_deployment
