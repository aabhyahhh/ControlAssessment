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
from app.agent.prompts.system import _blocking_action_hint, build_system_prompt
from app.agent.tools.phase_tools import ALL_TOOLS, TOOLS_BY_NAME, execute_tool
from app.engines.llm_utils import get_llm_client

logger = logging.getLogger("agent.loop")

MAX_ROUNDS = 8


def _get_llm_client():
    # Shared, connection-pooled client. The agent loop makes up to MAX_ROUNDS
    # calls per turn, so reusing the connection matters here too.
    return get_llm_client()


def _ensure_next_line(text: str, status: dict[str, Any]) -> str:
    """Reconciles the reply's closing "**Next:**" line with live project state.

    The line is only appropriate when the workflow is genuinely blocked on the
    user — a file to attach, or an approval that is theirs to give. So:

      - blocked and the model wrote no line  -> append the deterministic one
      - blocked and the model wrote its own  -> keep the model's wording
      - not blocked                          -> strip any line the model added

    That last case is the important one. The model tends to close every reply
    with an instruction, which on a progress update means repeating a stale
    demand ("attach your RCM") long after it was satisfied.
    """
    if not text:
        return text

    lines = text.splitlines()
    has_line = any(line.strip().startswith("**Next:**") for line in lines)
    blocking = _blocking_action_hint(status)

    if blocking and not has_line:
        return f"{text}\n\n**Next:** {blocking}"
    if blocking or not has_line:
        return text

    # Not blocked: drop the model's line and any blank lines it left behind.
    kept = [line for line in lines if not line.strip().startswith("**Next:**")]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


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
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            max_completion_tokens=4000,
        )
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
