"""
Step 3 — the evidence the user declares they hold, entered per control through
a structured UI. Stored in declared_evidence and reconciled against the
engine-generated required-documents list when step 3 runs.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from app.database import get_conn
from app.engines.rcm_overlay import load_effective_controls
from app.models.schemas import DeclaredEvidenceRequest, DeclaredEvidenceResponse
from app.security import require_auth

router = APIRouter(prefix="/api/projects", tags=["evidence"])


def _require_project(project_id: str, user_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s AND created_by = %s", (project_id, user_id))
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/{project_id}/evidence-list", response_model=list[DeclaredEvidenceResponse])
def list_declared_evidence(project_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, items, updated_at FROM declared_evidence WHERE project_id = %s ORDER BY control_id",
                (project_id,),
            )
            rows = cur.fetchall()
    return [
        DeclaredEvidenceResponse(control_id=r["control_id"], items=r["items"] or [], updated_at=r["updated_at"])
        for r in rows
    ]


@router.put("/{project_id}/evidence-list", response_model=DeclaredEvidenceResponse)
def upsert_declared_evidence(
    project_id: str, body: DeclaredEvidenceRequest, auth: dict = Depends(require_auth)
):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if body.control_id not in {c["control_id"] for c in controls}:
            raise HTTPException(status_code=422, detail=f"Control ID '{body.control_id}' is not in this project.")

        items = [i.model_dump() for i in body.items]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO declared_evidence (id, project_id, control_id, items)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (project_id, control_id) DO UPDATE
                    SET items = EXCLUDED.items, updated_at = NOW()
                RETURNING control_id, items, updated_at
                """,
                (str(uuid.uuid4()), project_id, body.control_id, json.dumps(items)),
            )
            row = cur.fetchone()
        # A change to the declared list makes a completed step 3 stale.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, '{3}', '\"pending\"'), updated_at = NOW() "
                "WHERE id = %s AND phase_status->>'3' = 'done'",
                (project_id,),
            )
        conn.commit()
    return DeclaredEvidenceResponse(
        control_id=row["control_id"], items=row["items"] or [], updated_at=row["updated_at"]
    )
