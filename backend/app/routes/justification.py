"""
Step 2 — justification emails sent to a control owner about a reconciliation
mismatch (RCM vs SOP/workpaper contradiction), and the response the LLM then
judges against that specific mismatch. The email embeds a link to a public,
token-secured response page (no login) the control owner can submit
directly from; an auditor can also upload a response manually on their
behalf via the authenticated endpoint below.
"""

import html
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from psycopg.rows import dict_row

from app.config import get_settings
from app.database import get_conn
from app.engines.sop_adequacy_engine import analyze_justification_response
from app.engines.text_extraction import extract_text
from app.models.schemas import (
    JustificationEmailItemResponse,
    JustificationEmailResponse,
    JustificationResponseTokenInfo,
    SendJustificationEmailRequest,
)
from app.security import require_auth
from app.services.email_service import EmailNotConfigured, EmailSendError, send_email
from app.storage.files import save_justification_response_file

router = APIRouter(prefix="/api/projects", tags=["justification"])
public_router = APIRouter(prefix="/api/justification-response", tags=["justification-public"])

_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def _response_url(token: str) -> str:
    base = get_settings().frontend_base_url
    return f"{base}/respond/{token}"


def _build_html_body(plain_body: str, item_rows: list[dict]) -> str:
    """Renders the same content as the plain-text body, plus a real
    button-styled link per mismatch — the response page (a single combined
    form) accepts a justification and/or an evidence attachment together, so
    'Attach Evidence' and 'Provide Justification' both point to the same
    token URL rather than two separate forms."""
    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in plain_body.split("\n") if line.strip())

    def _item_block(r: dict) -> str:
        label = f"{r['control_id']} ({r['field']})" if r["field"] else r["control_id"]
        url = _response_url(r["token"])
        return f"""
        <div style="margin:0 0 20px;padding:14px 16px;border:1px solid #e2e6ed;border-left:3px solid #dc2626;border-radius:8px;background:#fef2f2;">
          <div style="font-weight:700;font-size:13px;color:#0f172a;margin-bottom:4px;">{html.escape(label)}</div>
          <div style="font-size:13px;color:#334155;margin-bottom:12px;">{html.escape(r["mismatch_description"])}</div>
          <a href="{url}" style="display:inline-block;margin:0 8px 8px 0;padding:9px 16px;background:#0a2472;color:#ffffff;text-decoration:none;border-radius:6px;font-size:13px;font-weight:600;">Provide Justification</a>
          <a href="{url}" style="display:inline-block;margin:0 8px 8px 0;padding:9px 16px;background:#ffffff;color:#0a2472;text-decoration:none;border-radius:6px;font-size:13px;font-weight:600;border:1px solid #0a2472;">Attach Evidence</a>
        </div>"""

    items_html = "".join(_item_block(r) for r in item_rows)
    return f"""\
<html><body style="margin:0;padding:24px;background:#f0f2f5;font-family:Segoe UI,Inter,Arial,sans-serif;color:#0f172a;">
  <div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:12px;padding:28px;border:1px solid #e2e6ed;">
    <div style="font-size:12px;font-weight:700;letter-spacing:0.04em;color:#0a2472;margin-bottom:16px;">CONTROL ASSESSMENT</div>
    {paragraphs}
    <div style="margin-top:20px;">{items_html}</div>
    <p style="font-size:11.5px;color:#64748b;margin-top:8px;">
      Each button opens a secure page for that item only — no login required. You can type your justification
      and/or attach supporting evidence there in one step.
    </p>
  </div>
</body></html>"""


def _require_project(project_id: str, user_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s AND created_by = %s", (project_id, user_id))
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


def _item_to_response(row: dict) -> JustificationEmailItemResponse:
    return JustificationEmailItemResponse(
        id=row["id"],
        control_id=row["control_id"],
        field=row["field"],
        mismatch_description=row["mismatch_description"],
        response_text=row["response_text"],
        response_attachment_name=row["response_attachment_name"],
        response_uploaded_at=row["response_uploaded_at"],
        analysis_verdict=row["analysis_verdict"],
        analysis_reasoning=row["analysis_reasoning"],
        analyzed_at=row["analyzed_at"],
        response_url=_response_url(row["response_token"]) if row.get("response_token") else None,
    )


@router.post("/{project_id}/justification-emails", response_model=JustificationEmailResponse)
def send_justification_email(
    project_id: str, body: SendJustificationEmailRequest, auth: dict = Depends(require_auth)
):
    """Sends one email covering 1..N mismatches (single-control send has one
    item; a batch/collective send has several — same endpoint either way).
    Each mismatch gets its own random response token before the email is
    composed, so the body can link straight to that item's public response
    page — the owner can act on any single mismatch independently even in a
    batch email."""
    _require_project(project_id, auth["user_id"])

    email_id = str(uuid.uuid4())
    item_rows = [
        {
            "item_id": str(uuid.uuid4()),
            "token": secrets.token_urlsafe(32),
            "control_id": item.control_id,
            "field": item.field,
            "mismatch_description": item.mismatch_description,
        }
        for item in body.items
    ]

    def _link_line(r: dict) -> str:
        label = f"{r['control_id']} ({r['field']})" if r["field"] else r["control_id"]
        return f"- {label}: {_response_url(r['token'])}"

    links = "\n".join(_link_line(r) for r in item_rows)
    full_body = f"{body.body}\n\nRespond to each item directly here:\n{links}\n"
    html_body = _build_html_body(body.body, item_rows)

    send_status = "sent"
    error_message = None
    try:
        send_email(body.recipient_email, body.subject, full_body, html_body=html_body)
    except EmailNotConfigured as e:
        raise HTTPException(status_code=422, detail=str(e))
    except EmailSendError as e:
        send_status = "failed"
        error_message = str(e)

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO justification_emails
                    (id, project_id, recipient_email, subject, body, sent_by, send_status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, recipient_email, subject, sent_at, send_status, error_message
                """,
                (email_id, project_id, body.recipient_email, body.subject, full_body,
                 auth["user_id"], send_status, error_message),
            )
            email_row = cur.fetchone()

            items = []
            for r in item_rows:
                cur.execute(
                    """
                    INSERT INTO justification_email_items
                        (id, justification_email_id, project_id, control_id, field, mismatch_description, response_token)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, control_id, field, mismatch_description, response_text,
                              response_attachment_name, response_uploaded_at,
                              analysis_verdict, analysis_reasoning, analyzed_at, response_token
                    """,
                    (r["item_id"], email_id, project_id, r["control_id"], r["field"],
                     r["mismatch_description"], r["token"]),
                )
                items.append(cur.fetchone())
        conn.commit()

    return JustificationEmailResponse(
        id=email_row["id"],
        recipient_email=email_row["recipient_email"],
        subject=email_row["subject"],
        sent_at=email_row["sent_at"],
        send_status=email_row["send_status"],
        error_message=email_row["error_message"],
        items=[_item_to_response(r) for r in items],
    )


@router.get("/{project_id}/justification-emails", response_model=list[JustificationEmailResponse])
def list_justification_emails(project_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, recipient_email, subject, sent_at, send_status, error_message "
                "FROM justification_emails WHERE project_id = %s ORDER BY sent_at DESC",
                (project_id,),
            )
            emails = cur.fetchall()
            cur.execute(
                "SELECT id, justification_email_id, control_id, field, mismatch_description, response_text, "
                "response_attachment_name, response_uploaded_at, analysis_verdict, analysis_reasoning, analyzed_at, "
                "response_token "
                "FROM justification_email_items WHERE project_id = %s ORDER BY created_at",
                (project_id,),
            )
            items_by_email: dict[str, list[dict]] = {}
            for row in cur.fetchall():
                items_by_email.setdefault(row["justification_email_id"], []).append(row)

    return [
        JustificationEmailResponse(
            id=e["id"],
            recipient_email=e["recipient_email"],
            subject=e["subject"],
            sent_at=e["sent_at"],
            send_status=e["send_status"],
            error_message=e["error_message"],
            items=[_item_to_response(r) for r in items_by_email.get(e["id"], [])],
        )
        for e in emails
    ]


@router.get("/{project_id}/justification-emails/{item_id}", response_model=JustificationEmailItemResponse)
def get_justification_item(project_id: str, item_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, control_id, field, mismatch_description, response_text, response_attachment_name, "
                "response_uploaded_at, analysis_verdict, analysis_reasoning, analyzed_at, response_token "
                "FROM justification_email_items WHERE id = %s AND project_id = %s",
                (item_id, project_id),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Justification item not found")
    return _item_to_response(row)


@router.post(
    "/{project_id}/justification-emails/{item_id}/response",
    response_model=JustificationEmailItemResponse,
)
async def upload_justification_response(
    project_id: str,
    item_id: str,
    response_text: str | None = Form(None),
    file: UploadFile | None = None,
    auth: dict = Depends(require_auth),
):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id FROM justification_email_items WHERE id = %s AND project_id = %s",
                (item_id, project_id),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Justification item not found")

    attachment_path: str | None = None
    attachment_name: str | None = None
    attachment_text = ""
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Attachment exceeds the 25MB upload limit.")
        dest = save_justification_response_file(project_id, item_id, file.filename, content)
        attachment_path = str(dest)
        attachment_name = file.filename
        try:
            attachment_text = extract_text(dest)
        except Exception:
            attachment_text = ""

    combined_text = "\n\n".join(t for t in (response_text or "", attachment_text) if t.strip())
    if not combined_text.strip():
        raise HTTPException(status_code=422, detail="Provide response text and/or an attachment with readable text.")

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE justification_email_items
                SET response_text = %s, response_attachment_path = %s, response_attachment_name = %s,
                    response_uploaded_at = %s, response_uploaded_by = %s,
                    analysis_verdict = NULL, analysis_reasoning = NULL, analyzed_at = NULL
                WHERE id = %s AND project_id = %s
                RETURNING id, control_id, field, mismatch_description, response_text, response_attachment_name,
                          response_uploaded_at, analysis_verdict, analysis_reasoning, analyzed_at, response_token
                """,
                (combined_text, attachment_path, attachment_name, datetime.now(timezone.utc),
                 auth["user_id"], item_id, project_id),
            )
            row = cur.fetchone()
        conn.commit()
    return _item_to_response(row)


@router.post(
    "/{project_id}/justification-emails/{item_id}/analyze",
    response_model=JustificationEmailItemResponse,
)
def analyze_justification_item(project_id: str, item_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT jei.*, c.control_description, c.control_owner, c.control_frequency, c.control_type, "
                "       c.control_nature, c.risk_description, c.process "
                "FROM justification_email_items jei "
                "LEFT JOIN controls c ON c.project_id = jei.project_id AND c.control_id = jei.control_id "
                "WHERE jei.id = %s AND jei.project_id = %s",
                (item_id, project_id),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Justification item not found")
    if not (row["response_text"] or "").strip():
        raise HTTPException(status_code=422, detail="No response has been uploaded for this item yet.")

    rcm_value = row.get(row["field"]) if row["field"] else ""
    result = analyze_justification_response(
        control_id=row["control_id"],
        field=row["field"],
        mismatch_description=row["mismatch_description"],
        rcm_value=rcm_value or "",
        doc_value="",
        response_text=row["response_text"],
    )

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE justification_email_items
                SET analysis_verdict = %s, analysis_reasoning = %s, analyzed_at = %s
                WHERE id = %s AND project_id = %s
                RETURNING id, control_id, field, mismatch_description, response_text, response_attachment_name,
                          response_uploaded_at, analysis_verdict, analysis_reasoning, analyzed_at, response_token
                """,
                (result["verdict"], result["reasoning"], datetime.now(timezone.utc), item_id, project_id),
            )
            updated = cur.fetchone()
        conn.commit()
    return _item_to_response(updated)


# ═══════════════════════════════════════════════════════════════════════════
#  Public, unauthenticated endpoints — reached via the token link embedded in
#  the justification email itself. Deliberately expose ONLY the one
#  mismatch's own fields, never project/control data beyond it, and never
#  list or enumerate other items.
# ═══════════════════════════════════════════════════════════════════════════


def _fetch_by_token(cur, token: str) -> dict:
    cur.execute(
        "SELECT id, project_id, control_id, field, mismatch_description, response_text, "
        "response_attachment_name, response_uploaded_at, analysis_verdict, analysis_reasoning "
        "FROM justification_email_items WHERE response_token = %s",
        (token,),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="This link is invalid or has expired.")
    return row


@public_router.get("/{token}", response_model=JustificationResponseTokenInfo)
def get_justification_item_by_token(token: str):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _fetch_by_token(cur, token)
    return JustificationResponseTokenInfo(
        control_id=row["control_id"],
        field=row["field"],
        mismatch_description=row["mismatch_description"],
        already_responded=row["response_uploaded_at"] is not None,
        response_text=row["response_text"],
        response_attachment_name=row["response_attachment_name"],
    )


@public_router.post("/{token}", response_model=JustificationResponseTokenInfo)
async def submit_justification_response_by_token(
    token: str,
    response_text: str | None = Form(None),
    file: UploadFile | None = None,
):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            row = _fetch_by_token(cur, token)

    attachment_path: str | None = None
    attachment_name: str | None = None
    attachment_text = ""
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Attachment exceeds the 25MB upload limit.")
        dest = save_justification_response_file(row["project_id"], row["id"], file.filename, content)
        attachment_path = str(dest)
        attachment_name = file.filename
        try:
            attachment_text = extract_text(dest)
        except Exception:
            attachment_text = ""

    combined_text = "\n\n".join(t for t in (response_text or "", attachment_text) if t.strip())
    if not combined_text.strip():
        raise HTTPException(status_code=422, detail="Provide a justification and/or attach a file with readable text.")

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                UPDATE justification_email_items
                SET response_text = %s, response_attachment_path = %s, response_attachment_name = %s,
                    response_uploaded_at = %s, response_uploaded_by = NULL,
                    analysis_verdict = NULL, analysis_reasoning = NULL, analyzed_at = NULL
                WHERE response_token = %s
                RETURNING control_id, field, mismatch_description, response_text, response_attachment_name
                """,
                (combined_text, attachment_path, attachment_name, datetime.now(timezone.utc), token),
            )
            updated = cur.fetchone()
        conn.commit()

    return JustificationResponseTokenInfo(
        control_id=updated["control_id"],
        field=updated["field"],
        mismatch_description=updated["mismatch_description"],
        already_responded=True,
        response_text=updated["response_text"],
        response_attachment_name=updated["response_attachment_name"],
    )
