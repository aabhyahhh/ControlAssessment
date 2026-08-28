import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from psycopg.rows import dict_row
from pydantic import BaseModel

from app.database import get_conn
from app.models.schemas import ChatMessageResponse
from app.security import require_auth

logger = logging.getLogger("routes.chat")

router = APIRouter(prefix="/api/projects", tags=["chat"])


class ChatMessageRequest(BaseModel):
    message: str


def _sse(event: str, data: dict | None = None) -> str:
    # default=str is not optional here. Event payloads carry Pydantic
    # model_dump() output, which keeps datetime/Decimal/UUID as live objects —
    # `attributes_ready` raised "Object of type datetime is not JSON
    # serializable" mid-stream, which surfaced to the user as the attribute
    # generator being broken. Any event may carry such a value, so the
    # tolerance belongs in the encoder rather than at each call site.
    payload = json.dumps(data if data is not None else {}, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _require_project(project_id: str, user_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM projects WHERE id = %s AND created_by = %s",
                (project_id, user_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


def _save_message(project_id: str, role: str, content: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages (id, project_id, role, content) VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), project_id, role, content),
            )
        conn.commit()


@router.get("/{project_id}/chat", tags=["chat"], response_model=list[ChatMessageResponse])
def list_messages(project_id: str, auth: dict = Depends(require_auth)):
    """Full chat transcript for the project, oldest first. The frontend loads
    this on mount so a conversation survives navigating away and back."""
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, role, content, created_at FROM chat_messages WHERE project_id = %s "
                "AND content IS NOT NULL AND content <> '' ORDER BY created_at ASC",
                (project_id,),
            )
            rows = cur.fetchall()
    return [
        ChatMessageResponse(
            id=r["id"], role=r["role"], content=r["content"] or "", createdAt=r["created_at"]
        )
        for r in rows
    ]


class AppendMessageRequest(BaseModel):
    role: str
    content: str


@router.post("/{project_id}/chat/messages", response_model=ChatMessageResponse, tags=["chat"])
def append_message(project_id: str, body: AppendMessageRequest, auth: dict = Depends(require_auth)):
    """Persists a message the UI produced locally (upload confirmations, phase
    summaries). Without this those lines live only in React state and vanish
    the moment the user navigates away."""
    if body.role not in ("user", "assistant"):
        raise HTTPException(status_code=422, detail="role must be 'user' or 'assistant'.")
    _require_project(project_id, auth["user_id"])

    message_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "INSERT INTO chat_messages (id, project_id, role, content) VALUES (%s, %s, %s, %s) "
                "RETURNING id, role, content, created_at",
                (message_id, project_id, body.role, body.content),
            )
            row = cur.fetchone()
        conn.commit()
    return ChatMessageResponse(
        id=row["id"], role=row["role"], content=row["content"] or "", createdAt=row["created_at"]
    )


def _recent_history(project_id: str, limit: int = 12) -> list[dict]:
    """Prior turns for conversational context. Only plain user/assistant text
    is replayed — tool calls are not, because the system prompt carries live
    project state and stale tool results would just mislead the model."""
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT role, content FROM chat_messages WHERE project_id = %s AND role IN ('user','assistant') "
                "AND content IS NOT NULL AND content <> '' ORDER BY created_at DESC LIMIT %s",
                (project_id, limit),
            )
            rows = cur.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


@router.post("/{project_id}/chat")
def post_chat_message(project_id: str, body: ChatMessageRequest, auth: dict = Depends(require_auth)):
    """Accepts a user message and streams the agent's response back as SSE.

    The agent decides which tool to call each turn; the tools wrap the same
    route functions the UI buttons call, so preconditions and ownership
    checks apply identically either way.
    """
    _require_project(project_id, auth["user_id"])
    _save_message(project_id, "user", body.message)
    history = _recent_history(project_id)

    def event_stream():
        import queue
        import threading

        from app.agent.core.loop import run_agent_turn

        # The agent runs on a worker thread and pushes SSE frames onto this
        # queue; the response generator drains it as they arrive. Buffering
        # the whole turn instead would leave the user staring at nothing for
        # minutes while phases run.
        frames: queue.Queue = queue.Queue()
        _DONE = object()

        def emit(name: str, data: dict | None = None) -> None:
            frames.put(_sse(name, data))

        def worker() -> None:
            try:
                for _ in run_agent_turn(
                    project_id=project_id,
                    auth=auth,
                    user_message=body.message,
                    history=history,
                    emit=emit,
                    save_assistant=lambda text: _save_message(project_id, "assistant", text),
                ):
                    pass
            except Exception:
                correlation_id = str(uuid.uuid4())
                logger.exception(
                    "chat stream failed for project %s (correlation_id=%s)", project_id, correlation_id
                )
                frames.put(
                    _sse(
                        "error",
                        {
                            "message": "Something went wrong processing your message.",
                            "correlation_id": correlation_id,
                        },
                    )
                )
            finally:
                frames.put(_DONE)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            try:
                frame = frames.get(timeout=15)
            except queue.Empty:
                # Keep-alive comment so proxies don't drop a long phase run.
                yield ": keep-alive\n\n"
                continue
            if frame is _DONE:
                break
            yield frame
        yield _sse("done")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
