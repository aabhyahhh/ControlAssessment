"""
Per-project progress for long-running phases.

The adequacy document upload (SOP/workpaper text extraction + SOP-step
parsing), the adequacy assessment (step 2), and the evidence checklist
generation (step 3) can each run for minutes — text extraction plus, where
an LLM is configured, one or more model calls per document/control,
parallelized. Rather than convert them to SSE (which would change the
contract the agent tools also call), each records its progress here and the
UI polls one endpoint.

The gap assessment (step 4) is deliberately NOT instrumented: it does no LLM
work at all, only aggregates the already-computed results of steps 1-3, and
returns in milliseconds for any realistic control count. There is nothing
for a progress bar to show there.

Deliberately in-process and non-durable. This is a progress *hint*: the POST
response remains the source of truth, and losing the hint on restart costs
nothing. With multiple workers a poll may reach a worker that never saw the
POST, so a missing entry means "no information available" — never "finished".
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
# {project_id: {stage: {"done": int, "total": int, "label": str | None, "activity": str | None}}}
_state: dict[str, dict[str, dict]] = {}

# Stage keys. Kept as constants so the route, the engines and the frontend
# poll agree on spelling.
UPLOAD = "upload"
ADEQUACY = "adequacy"
EVIDENCE = "evidence"


def set_progress(
    project_id: str,
    stage: str,
    done: int,
    total: int,
    label: str | None = None,
    activity: str | None = None,
) -> None:
    """Record progress for one stage.

    `label` is the item just finished (a control ID or filename, usually),
    shown beside the bar. `activity` is what's actually happening to it right
    now — "Extracting text", "Reconciling against SOP", "Waiting for model
    response" — so the bar reads as a real account of backend work rather
    than a bare N-of-M count. Both are optional and independent: a caller
    that only knows the count can omit either.
    """
    with _lock:
        _state.setdefault(project_id, {})[stage] = {
            "done": done,
            "total": total,
            "label": label,
            "activity": activity,
        }


def clear_progress(project_id: str, stage: str) -> None:
    with _lock:
        stages = _state.get(project_id)
        if not stages:
            return
        stages.pop(stage, None)
        if not stages:
            _state.pop(project_id, None)


def get_progress(project_id: str) -> dict[str, dict]:
    """All in-flight stages for a project. Returns a copy — callers must not
    be able to mutate the shared state through the returned dict."""
    with _lock:
        return {stage: dict(entry) for stage, entry in _state.get(project_id, {}).items()}
