"""
The agent loop. Each turn: rebuild the system prompt from live project state,
send the full tool schemas, execute any tool calls, and loop until the model
stops calling tools — no hardcoded phase state machine.

Progress is streamed as SSE events on the same contract the frontend already
implements (token / tool_start / tool_end / results_ready / done / error).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Generator

from app.agent.core.types import AgentContext
from app.agent.prompts.system import (
    _blocking_action_hint,
    _next_action_hint,
    _runnable_next_step,
    build_system_prompt,
)
from app.agent.tools.phase_tools import ALL_TOOLS, TOOLS_BY_NAME, execute_tool
from app.engines.llm_utils import get_llm_client

logger = logging.getLogger("agent.loop")

MAX_ROUNDS = 8


def _get_llm_client():
    # Shared, connection-pooled client. The agent loop makes up to MAX_ROUNDS
    # calls per turn, so reusing the connection matters here too.
    return get_llm_client()


def _ensure_next_line(text: str, status: dict[str, Any]) -> str:
    """Reconciles the reply's closing guidance with live project state, so the
    user always knows what to do next.

      - blocked on the user (a file / the evidence list): a "**Next:**" line.
        Keep the model's if it wrote one, else append the deterministic one.
      - not blocked but a step is runnable: strip any stale "**Next:**" the
        model added, then make sure the reply ends by naming that step and
        inviting a go-ahead. Append a one-liner if the model didn't.
      - nothing left to do: strip a stray "**Next:**" and leave it.
    """
    if not text:
        return text

    lines = text.splitlines()
    has_next_line = any(line.strip().startswith("**Next:**") for line in lines)
    blocking = _blocking_action_hint(status)

    if blocking:
        if has_next_line:
            return text
        return f"{text}\n\n**Next:** {blocking}"

    # Not blocked — a "**Next:**" line here is wrong (it reads as a demand).
    # Drop it and any trailing blank lines the model left behind.
    if has_next_line:
        kept = [line for line in lines if not line.strip().startswith("**Next:**")]
        while kept and not kept[-1].strip():
            kept.pop()
        text = "\n".join(kept)

    runnable = _runnable_next_step(status)
    if runnable:
        low = text.lower()
        # Only append if the model didn't already point at the next move.
        if "proceed" not in low and "next step" not in low and runnable["verb"] not in low:
            text = f"{text}\n\n{runnable['sentence']}"
    return text


def run_agent_turn(
    project_id: str,
    auth: dict[str, Any],
    user_message: str,
    history: list[dict[str, Any]],
    emit: Callable[[str, dict], None],
    save_assistant: Callable[[str], None],
) -> Generator[None, None, None]:
    """Runs one user turn to completion, emitting SSE events as it goes.

    `history` is prior chat turns (role/content dicts) so the agent has
    conversational context; project state comes from the system prompt
    instead, which is rebuilt each round so it can't go stale mid-turn.
    """
    client, model = _get_llm_client()
    if client is None:
        emit("token", {"text": "The assessment agent isn't available — no LLM credentials are configured."})
        return

    ctx = AgentContext(project_id=project_id, auth=auth, emit=emit)
    status_tool = TOOLS_BY_NAME["get_project_status"]
    status = status_tool.execute(ctx).data

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(status)},
        *history,
        {"role": "user", "content": user_message},
    ]
    tools = [t.to_openai_schema() for t in ALL_TOOLS]
    final_text = ""

    for round_no in range(MAX_ROUNDS):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_completion_tokens=4000,
            )
        except Exception:
            logger.exception("agent LLM call failed for project %s", project_id)
            # Don't leave the user with a bare "something went wrong" — still
            # tell them what the next step is from the deterministic hint.
            hint = _blocking_action_hint(status) or _next_action_hint(status)
            fallback = (
                "I hit a problem reaching the assessment model, so I can't run this turn. "
                "You can still drive the workflow from the buttons on the right."
            )
            if hint:
                fallback += f"\n\n**Next:** {hint}"
            emit("token", {"text": fallback})
            save_assistant(fallback)
            yield
            return
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = msg.tool_calls or []

        if not tool_calls:
            final_text = _ensure_next_line((msg.content or "").strip(), status)
            if final_text:
                emit("token", {"text": final_text})
            break

        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}

            emit("tool_start", {"tool_name": name, "args": arguments})
            result = execute_tool(name, ctx, arguments)
            emit(
                "tool_end",
                {"tool_name": name, "result": {"success": result.success, "message": result.message}},
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(
                    {"success": result.success, "message": result.message, "data": result.data},
                    default=str,
                )[:6000],
            })

        # State may have changed — refresh the system prompt so the next
        # round reasons about what is true NOW, not what was true at the
        # start of the turn.
        status = status_tool.execute(ctx).data
        messages[0] = {"role": "system", "content": build_system_prompt(status)}
    else:
        final_text = _ensure_next_line(
            "I've completed several steps but stopped here to avoid looping.", status
        )
        emit("token", {"text": final_text})

    if final_text:
        save_assistant(final_text)
    yield
