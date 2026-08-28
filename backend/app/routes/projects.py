import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from app.database import get_conn
from app.models.schemas import ProjectCreateRequest, ProjectResponse
from app.security import require_auth
from app.storage.files import delete_project_files

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectResponse])
def list_projects(auth: dict = Depends(require_auth)):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM projects WHERE created_by = %s ORDER BY created_at DESC",
                (auth["user_id"],),
            )
            rows = cur.fetchall()
    return [ProjectResponse(**row) for row in rows]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreateRequest, auth: dict = Depends(require_auth)):
    if body.audit_period_end < body.audit_period_start:
        raise HTTPException(status_code=422, detail="audit_period_end must be on or after audit_period_start")
    project_id = str(uuid.uuid4())
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO projects (id, created_by, name, framework, audit_period_start, audit_period_end)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (project_id, auth["user_id"], body.name, body.framework, body.audit_period_start, body.audit_period_end),
            )
            row = cur.fetchone()
        conn.commit()
    return ProjectResponse(**row)


# Every table that references projects(id). None of these foreign keys is
# declared ON DELETE CASCADE, so the parent row cannot be removed until each
# child is cleared explicitly — a bare DELETE FROM projects fails on a
# foreign-key violation. Order matters only in that projects goes last.
_PROJECT_CHILD_TABLES = (
    "chat_messages",
    "artifacts",
    "control_test_results",
    "control_attributes",
    "phase_results",
    "evidence_files",
    "sop_uploads",
    "control_overlays",
    "controls",
    "rcm_uploads",
)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, auth: dict = Depends(require_auth)):
    """Permanently deletes a project with all of its data and files.

    The ownership check and the deletes share one transaction, so a project
    belonging to another user is never touched and a partial delete can't be
    left behind — either every child row goes or none does.

    Returns 404 rather than 403 for a project the caller doesn't own: whether
    some other user's project exists isn't information this endpoint should
    leak.
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # FOR UPDATE holds the row for the duration, so a phase run that
            # starts mid-delete blocks rather than writing children back
            # behind us.
            cur.execute(
                "SELECT id FROM projects WHERE id = %s AND created_by = %s FOR UPDATE",
                (project_id, auth["user_id"]),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

            for table in _PROJECT_CHILD_TABLES:
                # Table names come from the module-level tuple above, never
                # from the request, so this interpolation is not injectable.
                cur.execute(f"DELETE FROM {table} WHERE project_id = %s", (project_id,))
            cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
        conn.commit()

    # Only after the rows are durably gone. Best-effort by design — see
    # delete_project_files for why a filesystem error must not fail the
    # request at this point.
    delete_project_files(project_id)
    return None


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, auth: dict = Depends(require_auth)):
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM projects WHERE id = %s AND created_by = %s",
                (project_id, auth["user_id"]),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectResponse(**row)
