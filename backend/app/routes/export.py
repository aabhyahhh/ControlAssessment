"""
Artifact generation and download. Every generated file is recorded in the
`artifacts` table so the UI's repository panel can list and re-download
past exports rather than only offering the most recent one.
"""

import json
from typing import Any
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from psycopg.rows import dict_row

from app.database import get_conn
from app.engines.attribute_quality_gate import check_schema_quality
from app.engines.export_engine import (
    build_attributes_workbook,
    build_final_report,
    build_phase_workbook,
    build_rcm_workbook,
)
from app.engines.override_engine import (
    OVERRIDABLE_FIELDS,
    parse_attribute_overrides,
    parse_rcm_overrides,
)
from app.engines.rcm_overlay import load_effective_controls
from app.models.schemas import ArtifactResponse, OverrideResultResponse
from app.security import require_auth
from app.storage.files import artifacts_dir

router = APIRouter(prefix="/api/projects", tags=["export"])


def _require_project(project_id: str, user_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM projects WHERE id = %s AND created_by = %s", (project_id, user_id))
            project = cur.fetchone()
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
            return project


def _record_artifact(conn, project_id: str, path: Path, phase: int | None, artifact_type: str) -> dict:
    artifact_id = str(uuid.uuid4())
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO artifacts (id, project_id, phase, filename, file_path, artifact_type)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (artifact_id, project_id, phase, path.name, str(path), artifact_type),
        )
        row = cur.fetchone()
    conn.commit()
    return row


@router.get("/{project_id}/artifacts", response_model=list[ArtifactResponse])
def list_artifacts(project_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM artifacts WHERE project_id = %s ORDER BY created_at DESC",
                (project_id,),
            )
            rows = cur.fetchall()
    return [ArtifactResponse(**r) for r in rows]


@router.post("/{project_id}/export-attributes", response_model=ArtifactResponse)
def export_attributes(project_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, attributes FROM control_attributes WHERE project_id = %s ORDER BY control_id",
                (project_id,),
            )
            schemas = cur.fetchall()
        if not schemas:
            raise HTTPException(status_code=400, detail="No attribute schemas to export — generate them first.")

        path = build_attributes_workbook(
            [{"control_id": s["control_id"], "attributes": s["attributes"] or []} for s in schemas],
            artifacts_dir(project_id),
        )
        row = _record_artifact(conn, project_id, path, phase=4, artifact_type="attributes")
    return ArtifactResponse(**row)


@router.post("/{project_id}/export-final-report", response_model=ArtifactResponse)
def export_final_report(project_id: str, auth: dict = Depends(require_auth)):
    """Universe-preserving: every control appears exactly once on the summary
    sheet, with untested controls carrying an explicit reason rather than
    being omitted."""
    project = _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT phase, status, result FROM phase_results WHERE project_id = %s", (project_id,))
            # Only completed phases contribute. A phase mid-re-run holds an
            # empty result, and including it would silently blank that
            # section of the report rather than marking it as not yet run.
            phase_results = {
                r["phase"]: r["result"]
                for r in cur.fetchall()
                if r["status"] == "done" and (r["result"] or {})
            }
            cur.execute(
                "SELECT control_id, attributes FROM control_attributes WHERE project_id = %s ORDER BY control_id",
                (project_id,),
            )
            schemas = [{"control_id": r["control_id"], "attributes": r["attributes"] or []} for r in cur.fetchall()]

        path = build_final_report(dict(project), controls, phase_results, schemas, artifacts_dir(project_id))
        row = _record_artifact(conn, project_id, path, phase=None, artifact_type="final_report")
    return ArtifactResponse(**row)


@router.post("/{project_id}/export-phase/{phase}", response_model=ArtifactResponse)
def export_phase(project_id: str, phase: int, auth: dict = Depends(require_auth)):
    """Downloadable workbook for one phase's results, in the same shape the
    user can edit and re-upload as an override."""
    if phase not in (1, 2, 3, 4):
        raise HTTPException(status_code=422, detail="Phase must be 1, 2, 3 or 4.")
    _require_project(project_id, auth["user_id"])

    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT status, result FROM phase_results WHERE project_id = %s AND phase = %s",
                (project_id, phase),
            )
            row = cur.fetchone()
        # Check the STATUS, not just the row's existence. A re-run resets the
        # row to status='pending' before the new payload lands, so a row can
        # exist while holding nothing — exporting then produced a header-only
        # workbook, recorded as a perfectly legitimate artifact. status flips
        # to 'done' in the same transaction that writes the real result.
        if row is None or row["status"] != "done" or not (row["result"] or {}):
            raise HTTPException(
                status_code=409,
                detail=f"Phase {phase} has no completed results to export yet — "
                "wait for the run to finish, then try again.",
            )

        path = build_phase_workbook(phase, controls, row["result"], artifacts_dir(project_id))
        artifact = _record_artifact(conn, project_id, path, phase=phase, artifact_type=f"phase{phase}")
    return ArtifactResponse(**artifact)


@router.post("/{project_id}/export-rcm", response_model=ArtifactResponse)
def export_rcm(project_id: str, auth: dict = Depends(require_auth)):
    """The working RCM (normalized + any overrides applied), editable and
    re-uploadable via /override-rcm."""
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")
        path = build_rcm_workbook(controls, artifacts_dir(project_id))
        artifact = _record_artifact(conn, project_id, path, phase=1, artifact_type="rcm")
    return ArtifactResponse(**artifact)


@router.post("/{project_id}/override-rcm", response_model=OverrideResultResponse)
async def override_rcm(project_id: str, file: UploadFile, auth: dict = Depends(require_auth)):
    """Applies edits from a re-uploaded RCM workbook as non-destructive
    overlays. Controls absent from the sheet are left alone; a blank cell
    means 'no change'; a single '-' clears the field."""
    _require_project(project_id, auth["user_id"])
    dest = _save_override_upload(project_id, file, await file.read())

    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        known = {c["control_id"] for c in controls}
        try:
            parsed = parse_rcm_overrides(dest, known)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read the override sheet: {e}")

        # Only persist genuine differences. The export writes every field as
        # a value, so a straight re-upload would otherwise stamp an overlay
        # on all of them — making it look to an auditor like 20+ fields were
        # hand-edited when the user changed two.
        current = {c["control_id"]: c for c in controls}
        overrides: dict[str, dict[str, Any]] = {}
        for control_id, values in parsed["overrides"].items():
            existing = current.get(control_id, {})
            changed = {
                field: value
                for field, value in values.items()
                if field in OVERRIDABLE_FIELDS
                and (value if value is not None else "") != (existing.get(field) or "")
            }
            if changed:
                overrides[control_id] = changed

        applied = 0
        with conn.cursor() as cur:
            for control_id, values in overrides.items():
                for field, value in values.items():
                    if value is None:
                        cur.execute(
                            "DELETE FROM control_overlays WHERE project_id = %s AND control_id = %s AND field = %s",
                            (project_id, control_id, field),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO control_overlays (id, project_id, control_id, field, new_value, source)
                            VALUES (gen_random_uuid()::text, %s, %s, %s, %s, 'excel_reupload')
                            ON CONFLICT (project_id, control_id, field) DO UPDATE
                                SET new_value = EXCLUDED.new_value, source = 'excel_reupload', updated_at = NOW()
                            """,
                            (project_id, control_id, field, value),
                        )
                    applied += 1
        conn.commit()

    return OverrideResultResponse(
        controls_updated=len(overrides),
        fields_updated=applied,
        unknown_control_ids=parsed["unknown_control_ids"],
        message=(
            f"Applied {applied} field edit(s) across {len(overrides)} control(s)."
            + (
                f" Ignored {len(parsed['unknown_control_ids'])} row(s) whose Control ID isn't in this project: "
                f"{', '.join(parsed['unknown_control_ids'][:5])}."
                if parsed["unknown_control_ids"]
                else ""
            )
            + " Re-run Phase 1 to rescore with these values."
        ),
    )


@router.post("/{project_id}/override-attributes", response_model=OverrideResultResponse)
async def override_attributes(project_id: str, file: UploadFile, auth: dict = Depends(require_auth)):
    """Applies edits from a re-uploaded attribute workbook. Row order within
    a control is authoritative for attribute order/IDs. Controls that have
    already been tested are refused — their results are keyed to the frozen
    attribute IDs."""
    _require_project(project_id, auth["user_id"])
    dest = _save_override_upload(project_id, file, await file.read())

    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        known = {c["control_id"] for c in controls}
        control_text = {
            c["control_id"]: " ".join(str(c.get(f) or "") for f in ("control_description", "risk_description"))
            for c in controls
        }
        try:
            parsed = parse_attribute_overrides(dest, known)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not read the override sheet: {e}")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT control_id FROM control_test_results WHERE project_id = %s", (project_id,))
            tested = {r["control_id"] for r in cur.fetchall()}

        updated, refused = 0, []
        with conn.cursor() as cur:
            for control_id, attributes in parsed["attributes"].items():
                if control_id in tested:
                    refused.append(control_id)
                    continue
                schema = {"worksteps": [], "attributes": attributes, "sample_columns": []}
                cur.execute(
                    "SELECT worksteps, sample_columns FROM control_attributes "
                    "WHERE project_id = %s AND control_id = %s",
                    (project_id, control_id),
                )
                existing = cur.fetchone()
                if existing:
                    schema["worksteps"], schema["sample_columns"] = existing[0] or [], existing[1] or []

                issues = check_schema_quality(schema, control_text.get(control_id, ""))
                cur.execute(
                    """
                    INSERT INTO control_attributes
                        (id, project_id, control_id, worksteps, attributes, sample_columns, quality_issues, status)
                    VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, %s, 'pending')
                    ON CONFLICT (project_id, control_id) DO UPDATE
                        SET attributes = EXCLUDED.attributes, quality_issues = EXCLUDED.quality_issues,
                            status = 'pending', updated_at = NOW()
                    """,
                    (
                        project_id, control_id, json.dumps(schema["worksteps"]), json.dumps(attributes),
                        json.dumps(schema["sample_columns"]), json.dumps(issues),
                    ),
                )
                updated += 1
        conn.commit()

    return OverrideResultResponse(
        controls_updated=updated,
        fields_updated=sum(len(a) for a in parsed["attributes"].values()),
        unknown_control_ids=parsed["unknown_control_ids"],
        message=(
            f"Updated attributes for {updated} control(s); each was re-checked against the quality gate."
            + (
                f" Refused {len(refused)} already-tested control(s) ({', '.join(refused[:5])}) — their results are "
                "keyed to the frozen attribute IDs."
                if refused
                else ""
            )
        ),
    )


def _save_override_upload(project_id: str, file: UploadFile, content: bytes) -> Path:
    original_name = file.filename or "override.xlsx"
    suffix = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if suffix not in (".xlsx", ".xls", ".csv"):
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix}'. Use .xlsx, .xls or .csv.")
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds the 100MB upload limit.")
    dest = artifacts_dir(project_id) / f"override_{uuid.uuid4().hex}{suffix}"
    dest.write_bytes(content)
    return dest


@router.get("/{project_id}/artifacts/{artifact_id}/download")
def download_artifact(project_id: str, artifact_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM artifacts WHERE id = %s AND project_id = %s",
                (artifact_id, project_id),
            )
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")

    path = Path(row["file_path"])
    # Containment check: file_path is written by this service, but a stored
    # path must still resolve inside the project's own artifacts directory
    # before it's served.
    root = artifacts_dir(project_id).resolve()
    if not path.resolve().is_relative_to(root) or not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact file is no longer available")

    return FileResponse(
        path,
        filename=row["filename"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
