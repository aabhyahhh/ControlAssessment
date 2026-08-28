"""
Agent tool contract. Ported in design (not by import) from ControlIris's
`agent/tools/base.py`: each tool declares its own OpenAI function schema and
its own preconditions, so hard rules live in code rather than only in the
system prompt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    # Human-readable line the agent can relay verbatim; keeps the LLM from
    # having to re-summarize a structured result it might get wrong.
    message: str = ""


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = False
    enum: list[str] | None = None


class Tool(ABC):
    """One agent-callable action.

    `preconditions` returns None when the tool may run, or a plain-English
    reason why it can't. The reason is handed back to the LLM so it can tell
    the user exactly what's blocking and how to unblock it, rather than
    silently failing or looping.
    """

    name: str = ""
    description: str = ""
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: "AgentContext") -> str | None:  # noqa: F821
        return None

    @abstractmethod
    def execute(self, ctx: "AgentContext", **kwargs) -> ToolResult:  # noqa: F821
        ...

    def to_openai_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            spec: dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum:
                spec["enum"] = p.enum
            properties[p.name] = spec
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }


@dataclass
class AgentContext:
    """Everything a tool needs to act, plus a channel for streaming progress.

    Carries the caller's identity so tools reuse the exact same
    ownership-checked route functions the UI calls — the agent gets no
    privileged path of its own.
    """

    project_id: str
    auth: dict[str, Any]
    emit: Callable[[str, dict[str, Any]], None]

    def project(self) -> dict[str, Any]:
        from app.database import get_conn
        from psycopg.rows import dict_row

        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM projects WHERE id = %s", (self.project_id,))
                return cur.fetchone() or {}

    def phase_status(self) -> dict[str, str]:
        return (self.project().get("phase_status") or {})
