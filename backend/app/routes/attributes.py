"""
Phase 4 attribute preview / edit / approve endpoints.

Two rules from ATTRIBUTE_GENERATION_ENGINE_SPEC.md are enforced here rather
than left to the prompt:
 - Defect #1 fix: the deterministic quality gate re-runs after EVERY
   mutation (not just generation), and its findings are persisted and
   returned so a schema with unresolved issues is visibly flagged.
 - Freeze rule (spec Section 1): once a schema is approved it cannot be
   mutated — the evaluation LLM's attribute_results keys are the frozen
   positional ids, so resequencing after approval would silently
   desynchronize pass/fail results.
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from app.database import get_conn
from app.engines.attribute_engine import generate_attributes, resequence_attribute_ids
from app.engines import progress
from app.engines.attribute_quality_gate import check_schema_quality
from app.engines.rcm_overlay import load_effective_controls
from app.models.schemas import AddAttributeRequest, ControlAttributesResponse, ModifyAttributeRequest
from app.security import require_auth

router = APIRouter(prefix="/api/projects", tags=["attributes"])

# Progress for the long-running phases now lives in engines/progress.py so
# adequacy, attribute generation and testing all report through one channel.


def _set_progress(project_id: str, done: int, total: int, control_id: str | None = None) -> None:
    progress.set_progress(project_id, progress.ATTRIBUTES, done, total, control_id)


def _clear_progress(project_id: str) -> None:
    progress.clear_progress(project_id, progress.ATTRIBUTES)


def _require_project(project_id: str, user_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM projects WHERE id = %s AND created_by = %s", (project_id, user_id))
            project = cur.fetchone()
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
            return project


def _fetch_row(conn, project_id: str, control_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM control_attributes WHERE project_id = %s AND control_id = %s",
            (project_id, control_id),
        )
        return cur.fetchone()


def _require_mutable_row(conn, project_id: str, control_id: str) -> dict:
    """A schema is immutable once test results exist for that control — the
    results are keyed to its positional attribute IDs, so editing would
    desynchronize them. Merely being 'approved' is not enough to lock it:
    if testing never ran, the user must still be able to fix the attributes.
    """
    row = _fetch_row(conn, project_id, control_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No attributes generated yet for {control_id}.")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM control_test_results WHERE project_id = %s AND control_id = %s",
            (project_id, control_id),
        )
        has_results = cur.fetchone() is not None

    if has_results:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{control_id} has already been tested — its results are keyed to these attribute IDs, so they "
                "can't be edited. Regenerate the attributes to re-test this control from scratch."
            ),
        )
    return row


def _control_text(conn, project_id: str, control_id: str) -> str:
    controls = load_effective_controls(conn, project_id)
    for c in controls:
        if c["control_id"] == control_id:
            return " ".join(str(c.get(f) or "") for f in ("control_description", "risk_description"))
    return ""


def _persist(conn, project_id: str, control_id: str, schema: dict, issues: list[str]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE control_attributes
               SET worksteps = %s, attributes = %s, sample_columns = %s,
                   quality_issues = %s, updated_at = NOW()
             WHERE project_id = %s AND control_id = %s
            """,
            (
                json.dumps(schema["worksteps"]), json.dumps(schema["attributes"]),
                json.dumps(schema["sample_columns"]), json.dumps(issues),
                project_id, control_id,
            ),
        )
    conn.commit()


def _regate_and_persist(conn, project_id: str, control_id: str, row: dict, attributes: list[dict]) -> dict:
    """Shared tail for every mutation path: resequence ids, re-run the
    quality gate, persist, and return the refreshed row."""
    schema = {
        "worksteps": row["worksteps"],
        "attributes": resequence_attribute_ids(attributes),
        "sample_columns": row["sample_columns"],
    }
    issues = check_schema_quality(schema, _control_text(conn, project_id, control_id))
    _persist(conn, project_id, control_id, schema, issues)
    return _fetch_row(conn, project_id, control_id)


def _to_response(row: dict) -> ControlAttributesResponse:
    return ControlAttributesResponse(
        control_id=row["control_id"],
        worksteps=row["worksteps"] or [],
        attributes=row["attributes"] or [],
        sample_columns=row["sample_columns"] or [],
        quality_issues=row["quality_issues"] or [],
        status=row["status"],
        updated_at=row["updated_at"],
    )


# Literal-segment paths use the /attributes-<verb> form rather than
# /attributes/<verb>, so they can never be shadowed by the
# /attributes/{control_id} routes below regardless of declaration order.
@router.get("/{project_id}/phase-progress")
def phase_progress(project_id: str, auth: dict = Depends(require_auth)):
    """Progress of any long-running phase for this project.

    Returns {stage: {done, total, label}} for whatever is in flight. An
    absent stage means "no information", NOT "finished" — see
    engines/progress.py for why.
    """
    _require_project(project_id, auth["user_id"])
    return {"stages": progress.get_progress(project_id)}


@router.post("/{project_id}/attributes-preview", response_model=list[ControlAttributesResponse])
def preview_attributes(project_id: str, auth: dict = Depends(require_auth)):
    """Generates attribute schemas for every control that doesn't already
    have an approved one. Precondition: Phase 3 must be complete."""
    project = _require_project(project_id, auth["user_id"])
    if (project["phase_status"] or {}).get("3") != "done":
        raise HTTPException(status_code=400, detail="Phase 3 (adequacy assessment) must be completed first.")

    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id FROM control_test_results WHERE project_id = %s",
                (project_id,),
            )
            already_tested = {r["control_id"] for r in cur.fetchall()}

        # The freeze exists so that test results stay keyed to the attribute
        # IDs they were produced against — so it only has to bind once a
        # control HAS results. A control that is merely approved but never
        # tested can still be regenerated, which is the escape hatch when
        # testing fails after approval.
        to_generate = [c for c in controls if c["control_id"] not in already_tested]
        if to_generate:
            # Publish 0/N before the first control lands, so the bar appears
            # immediately rather than after the first (slow) completion.
            _set_progress(project_id, 0, len(to_generate))
            try:
                generated = generate_attributes(
                    to_generate,
                    on_progress=lambda cid, done, total: _set_progress(project_id, done, total, cid),
                )
            finally:
                _clear_progress(project_id)
        else:
            generated = {}

        with conn.cursor() as cur:
            for control_id, schema in generated.items():
                cur.execute(
                    """
                    INSERT INTO control_attributes
                        (id, project_id, control_id, worksteps, attributes, sample_columns, quality_issues, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                    ON CONFLICT (project_id, control_id) DO UPDATE
                        SET worksteps = EXCLUDED.worksteps, attributes = EXCLUDED.attributes,
                            sample_columns = EXCLUDED.sample_columns, quality_issues = EXCLUDED.quality_issues,
                            status = 'pending', updated_at = NOW()
                    """,
                    (
                        str(uuid.uuid4()), project_id, control_id,
                        json.dumps(schema["worksteps"]), json.dumps(schema["attributes"]),
                        json.dumps(schema["sample_columns"]), json.dumps(schema["quality_issues"]),
                    ),
                )
        conn.commit()

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM control_attributes WHERE project_id = %s ORDER BY control_id",
                (project_id,),
            )
            rows = cur.fetchall()

    return [_to_response(r) for r in rows]


@router.get("/{project_id}/attributes", response_model=list[ControlAttributesResponse])
def list_attributes(project_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM control_attributes WHERE project_id = %s ORDER BY control_id",
                (project_id,),
            )
            rows = cur.fetchall()
    return [_to_response(r) for r in rows]


@router.patch("/{project_id}/attributes/{control_id}/{attribute_no}", response_model=ControlAttributesResponse)
def modify_attribute(
    project_id: str, control_id: str, attribute_no: int,
    body: ModifyAttributeRequest, auth: dict = Depends(require_auth),
):
    """attribute_no is 1-based, per spec Section 5.1."""
    _require_project(project_id, auth["user_id"])
    if body.name is None and body.description is None:
        raise HTTPException(status_code=422, detail="Provide at least one of name or description.")

    with get_conn() as conn:
        row = _require_mutable_row(conn, project_id, control_id)
        attributes = list(row["attributes"] or [])
        if not (1 <= attribute_no <= len(attributes)):
            raise HTTPException(
                status_code=422,
                detail=f"Attribute {attribute_no} is out of range — {control_id} has {len(attributes)} attribute(s).",
            )

        target = dict(attributes[attribute_no - 1])
        if body.name is not None:
            target["name"] = body.name.strip()
        if body.description is not None:
            target["description"] = body.description.strip()
        attributes[attribute_no - 1] = target

        return _to_response(_regate_and_persist(conn, project_id, control_id, row, attributes))


@router.post("/{project_id}/attributes/{control_id}", response_model=ControlAttributesResponse)
def add_attribute(project_id: str, control_id: str, body: AddAttributeRequest, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        row = _require_mutable_row(conn, project_id, control_id)
        attributes = list(row["attributes"] or [])

        new_attr = {"id": "0", "name": body.name.strip(), "description": body.description.strip()}
        # position is 1-based; clamp into range, default = append.
        index = len(attributes) if body.position is None else max(0, min(body.position - 1, len(attributes)))
        attributes.insert(index, new_attr)

        return _to_response(_regate_and_persist(conn, project_id, control_id, row, attributes))


@router.delete("/{project_id}/attributes/{control_id}/{attribute_no}", response_model=ControlAttributesResponse)
def remove_attribute(project_id: str, control_id: str, attribute_no: int, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        row = _require_mutable_row(conn, project_id, control_id)
        attributes = list(row["attributes"] or [])
        if not (1 <= attribute_no <= len(attributes)):
            raise HTTPException(
                status_code=422,
                detail=f"Attribute {attribute_no} is out of range — {control_id} has {len(attributes)} attribute(s).",
            )
        # Defect #9 fix: a control with zero attributes has no testable
        # condition at all, so refuse rather than allow it.
        if len(attributes) == 1:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot remove the last attribute of {control_id} — a control needs at least one testable condition.",
            )

        attributes.pop(attribute_no - 1)
        return _to_response(_regate_and_persist(conn, project_id, control_id, row, attributes))


# NOTE: path is /attributes-approve, not /attributes/approve — the latter
# would be shadowed by POST /attributes/{control_id} (add_attribute), which
# would silently reject approval as a malformed add-attribute request.
@router.post("/{project_id}/attributes-approve", response_model=list[ControlAttributesResponse])
def approve_attributes(project_id: str, auth: dict = Depends(require_auth)):
    """Freezes every pending schema that has at least one attribute. Schemas
    with unresolved quality issues can still be approved — that's a
    legitimate human call — but the issues stay recorded and visible."""
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, attributes FROM control_attributes WHERE project_id = %s AND status = 'pending'",
                (project_id,),
            )
            pending = cur.fetchall()

        approvable = [r["control_id"] for r in pending if (r["attributes"] or [])]
        if not approvable:
            raise HTTPException(status_code=400, detail="No pending attribute schemas with attributes to approve.")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE control_attributes SET status = 'approved', approved_at = NOW(), updated_at = NOW() "
                "WHERE project_id = %s AND control_id = ANY(%s)",
                (project_id, approvable),
            )
        conn.commit()

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM control_attributes WHERE project_id = %s ORDER BY control_id",
                (project_id,),
            )
            rows = cur.fetchall()

    return [_to_response(r) for r in rows]
