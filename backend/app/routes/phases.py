import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from pathlib import Path

from app.database import get_conn
from app.engines import progress
from app.engines.evidence_gap_engine import assess_evidence_gaps, generate_required_documents
from app.engines.gap_assessment_engine import build_gap_assessment
from app.engines.rcm_overlay import load_effective_controls
from app.engines.risk_scorer import score_controls
from app.engines.sop_adequacy_engine import run_sop_adequacy_assessment
from app.models.schemas import PhaseResultResponse, RunAllResponse
from app.security import require_auth

logger = logging.getLogger("routes.phases")

router = APIRouter(prefix="/api/projects", tags=["phases"])


def _require_project(project_id: str, user_id: str) -> dict:
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM projects WHERE id = %s AND created_by = %s", (project_id, user_id))
            project = cur.fetchone()
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
            return project


def _claim_phase(project_id: str, user_id: str, phase: int, check) -> dict:
    """Atomically verifies a phase's preconditions and claims it as running.

    Phase runs are read-then-write ("is phase N-1 done?" ... minutes of LLM
    work ... "mark phase N done"), which made concurrent runs a TOCTOU race.
    We take the row lock only long enough to check preconditions and flip
    phase_status to 'running'; a second caller then blocks on the lock, wakes
    to find 'running', and is rejected — while the slow work happens with no
    lock held.
    """
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM projects WHERE id = %s AND created_by = %s FOR UPDATE",
                (project_id, user_id),
            )
            project = cur.fetchone()
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

            if (project["phase_status"] or {}).get(str(phase)) == "running":
                raise HTTPException(
                    status_code=409,
                    detail=f"Step {phase} is already running for this project. Wait for it to finish.",
                )
            check(project)

            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, %s, '\"running\"'), updated_at = NOW() "
                "WHERE id = %s",
                ([str(phase)], project_id),
            )
        conn.commit()
    return project


def _release_phase_claim(project_id: str, phase: int, new_status: str = "pending") -> None:
    """Clears a 'running' claim when the phase fails, so the user can retry."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE projects SET phase_status = jsonb_set(phase_status, %s, %s::jsonb), updated_at = NOW() "
                    "WHERE id = %s AND phase_status->>%s = 'running'",
                    ([str(phase)], json.dumps(new_status), project_id, str(phase)),
                )
            conn.commit()
    except Exception:
        logger.exception("Could not release the 'running' claim on step %s of project %s", phase, project_id)


def _fetch_phase_result(conn, project_id: str, phase: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM phase_results WHERE project_id = %s AND phase = %s", (project_id, phase))
        return cur.fetchone()


def _load_done_result(conn, project_id: str, phase: int) -> dict:
    row = _fetch_phase_result(conn, project_id, phase)
    if row is None or row["status"] != "done" or not (row["result"] or {}):
        return {}
    return row["result"]


def _write_phase(conn, project_id: str, phase: int, payload: dict, user_id: str, advance_current: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO phase_results (id, project_id, phase, status, result, approved_by, approved_at)
            VALUES (gen_random_uuid()::text, %s, %s, 'done', %s, %s, NOW())
            ON CONFLICT (project_id, phase) DO UPDATE
                SET status = 'done', result = EXCLUDED.result, approved_by = EXCLUDED.approved_by,
                    approved_at = NOW(), updated_at = NOW()
            """,
            (project_id, phase, json.dumps(payload), user_id),
        )
        if advance_current:
            cur.execute(
                "UPDATE projects SET current_phase = %s, "
                "phase_status = jsonb_set(phase_status, %s, '\"done\"'), updated_at = NOW() WHERE id = %s",
                (phase, [str(phase)], project_id),
            )
        else:
            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, %s, '\"done\"'), updated_at = NOW() "
                "WHERE id = %s",
                ([str(phase)], project_id),
            )
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════
#  Step 1 — RCM intake
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{project_id}/phases/1/run", response_model=PhaseResultResponse)
def run_rcm_intake(project_id: str, auth: dict = Depends(require_auth)):
    """Recomputes the step-1 completeness view. The RCM upload already writes
    this and marks step 1 done, so this is only needed after an override."""
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project. Upload an RCM first.")
        payload = score_controls(controls)
        _write_phase(conn, project_id, 1, payload, auth["user_id"], advance_current=True)
        saved = _fetch_phase_result(conn, project_id, 1)
    return PhaseResultResponse(
        phase=1, status="done", result=saved["result"],
        approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Step 2 — Adequacy assessment (SOPs + monthly workpapers)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{project_id}/phases/2/run", response_model=PhaseResultResponse)
def run_adequacy_assessment(project_id: str, auth: dict = Depends(require_auth)):
    """Preconditions: step 1 done AND at least one adequacy document uploaded."""

    def _check(project: dict) -> None:
        if (project["phase_status"] or {}).get("1") != "done":
            raise HTTPException(status_code=400, detail="Step 1 (RCM intake) must be completed first.")
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1 FROM adequacy_documents WHERE project_id = %s LIMIT 1", (project_id,))
                if cur.fetchone() is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "No SOPs or workpapers uploaded. Upload a folder (one subfolder per Control ID) "
                            "or individual SOP/workpaper files before running the adequacy assessment."
                        ),
                    )

    _claim_phase(project_id, auth["user_id"], 2, _check)
    try:
        return _run_phase2_body(project_id, auth)
    except Exception:
        _release_phase_claim(project_id, 2)
        raise


def _run_phase2_body(project_id: str, auth: dict) -> PhaseResultResponse:
    project = _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, doc_kind, period_month, extracted_text FROM adequacy_documents WHERE project_id = %s",
                (project_id,),
            )
            doc_rows = cur.fetchall()

        project_sop_parts: list[str] = []
        docs_text_by_control: dict[str, list[str]] = {}
        workpaper_months_by_control: dict[str, list[str]] = {}
        for row in doc_rows:
            text = row["extracted_text"] or ""
            if row["control_id"]:
                docs_text_by_control.setdefault(row["control_id"], []).append(text)
                if row["doc_kind"] == "workpaper" and row["period_month"]:
                    workpaper_months_by_control.setdefault(row["control_id"], []).append(
                        row["period_month"].strftime("%Y-%m")
                    )
            else:
                project_sop_parts.append(text)

        docs_text_joined = {cid: "\n\n".join(parts) for cid, parts in docs_text_by_control.items()}
        project_sop_text = "\n\n".join(project_sop_parts)

        progress.set_progress(project_id, progress.ADEQUACY, 0, len(controls) * 2, activity="Starting reconciliation")
        try:
            result_payload = run_sop_adequacy_assessment(
                controls,
                project_sop_text,
                docs_text_joined,
                workpaper_months_by_control,
                project["audit_period_start"],
                project["audit_period_end"],
                on_progress=lambda cid, done, total, activity: progress.set_progress(
                    project_id, progress.ADEQUACY, done, total, cid, activity
                ),
            )
        finally:
            progress.clear_progress(project_id, progress.ADEQUACY)

        result_payload["stats"] = {**result_payload["counts"]}
        _write_phase(conn, project_id, 2, result_payload, auth["user_id"], advance_current=True)
        saved = _fetch_phase_result(conn, project_id, 2)

    return PhaseResultResponse(
        phase=2, status="done", result=saved["result"],
        approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Step 3 — Evidence requirements & intake
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{project_id}/phases/3/run", response_model=PhaseResultResponse)
def run_evidence_assessment(project_id: str, auth: dict = Depends(require_auth)):
    """Precondition: step 2 (adequacy) done. Evidence upload and the declared
    evidence list are both optional inputs — the run still reports the gap."""

    def _check(project: dict) -> None:
        if (project["phase_status"] or {}).get("2") != "done":
            raise HTTPException(status_code=400, detail="Step 2 (adequacy assessment) must be completed first.")

    _claim_phase(project_id, auth["user_id"], 3, _check)
    try:
        return _run_phase3_body(project_id, auth)
    except Exception:
        _release_phase_claim(project_id, 3)
        raise


def _run_phase3_body(project_id: str, auth: dict) -> PhaseResultResponse:
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, original_name, detected_mode FROM evidence_files WHERE project_id = %s",
                (project_id,),
            )
            evidence_rows = cur.fetchall()
            cur.execute("SELECT control_id, items FROM declared_evidence WHERE project_id = %s", (project_id,))
            declared_rows = cur.fetchall()

        filenames_by_control: dict[str, list[str]] = {}
        mode_by_control: dict[str, str] = {}
        for row in evidence_rows:
            filenames_by_control.setdefault(row["control_id"], []).append(row["original_name"])
            mode_by_control[row["control_id"]] = row["detected_mode"]
        for c in controls:
            mode_by_control.setdefault(c["control_id"], "no_evidence")

        declared_by_control: dict[str, list[str]] = {}
        for row in declared_rows:
            items = row["items"] or []
            declared_by_control[row["control_id"]] = [
                (i.get("name") if isinstance(i, dict) else str(i)) for i in items if i
            ]

        # Reuse step 2's reconciliation text as extra context for the checklist.
        step2 = _load_done_result(conn, project_id, 2)
        recon_text = {
            r["control_id"]: "; ".join(
                f"{f}: {v.get('doc_value', '')}"
                for f, v in (r.get("fields") or {}).items()
                if v.get("doc_value")
            )
            for r in (step2.get("reconciliation") or [])
        }

        progress.set_progress(project_id, progress.EVIDENCE, 0, len(controls), activity="Starting checklist generation")
        try:
            required_documents = generate_required_documents(
                controls,
                recon_text,
                on_progress=lambda cid, done, total, activity: progress.set_progress(
                    project_id, progress.EVIDENCE, done, total, cid, activity
                ),
            )
        finally:
            progress.clear_progress(project_id, progress.EVIDENCE)

        result_payload = assess_evidence_gaps(
            controls, required_documents, filenames_by_control, declared_by_control, mode_by_control
        )

        _write_phase(conn, project_id, 3, result_payload, auth["user_id"], advance_current=True)
        saved = _fetch_phase_result(conn, project_id, 3)

    return PhaseResultResponse(
        phase=3, status="done", result=saved["result"],
        approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Step 4 — Gap assessment
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/{project_id}/phases/4/run", response_model=PhaseResultResponse)
def run_gap_assessment(project_id: str, auth: dict = Depends(require_auth)):
    """Precondition: step 3 done. Aggregates steps 1-3 into the gap picture
    that the Excel summary is built from."""

    def _check(project: dict) -> None:
        if (project["phase_status"] or {}).get("3") != "done":
            raise HTTPException(status_code=400, detail="Step 3 (evidence assessment) must be completed first.")

    _claim_phase(project_id, auth["user_id"], 4, _check)
    try:
        return _run_phase4_body(project_id, auth)
    except Exception:
        _release_phase_claim(project_id, 4)
        raise


def _run_phase4_body(project_id: str, auth: dict) -> PhaseResultResponse:
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        step1 = _load_done_result(conn, project_id, 1)
        step2 = _load_done_result(conn, project_id, 2)
        step3 = _load_done_result(conn, project_id, 3)

        result_payload = build_gap_assessment(controls, step1, step2, step3)
        _write_phase(conn, project_id, 4, result_payload, auth["user_id"], advance_current=True)
        saved = _fetch_phase_result(conn, project_id, 4)

    return PhaseResultResponse(
        phase=4, status="done", result=saved["result"],
        approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


# ═══════════════════════════════════════════════════════════════════════════
#  Progress + run-all + fetch
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/{project_id}/phase-progress")
def phase_progress(project_id: str, auth: dict = Depends(require_auth)):
    """Progress of any long-running step for this project.

    Returns {stage: {done, total, label}} for whatever is in flight. An absent
    stage means "no information", NOT "finished" — see engines/progress.py.
    """
    _require_project(project_id, auth["user_id"])
    return {"stages": progress.get_progress(project_id)}


@router.post("/{project_id}/phases-run-all", response_model=RunAllResponse)
def run_all_remaining_phases(project_id: str, auth: dict = Depends(require_auth)):
    """Runs every not-yet-done step in order, stopping at the first one whose
    preconditions aren't met and reporting exactly what's blocking."""
    project = _require_project(project_id, auth["user_id"])
    status_map = project["phase_status"] or {}

    runners = {
        1: run_rcm_intake,
        2: run_adequacy_assessment,
        3: run_evidence_assessment,
        4: run_gap_assessment,
    }

    completed: list[int] = []
    for phase in (1, 2, 3, 4):
        if status_map.get(str(phase)) == "done":
            continue
        try:
            runners[phase](project_id, auth)
        except HTTPException as e:
            return RunAllResponse(
                completed_phases=completed,
                stopped_at_phase=phase,
                blocked_reason=str(e.detail),
                message=(
                    f"Ran {len(completed)} step(s), then stopped at Step {phase}: {e.detail}"
                    if completed
                    else f"Could not start at Step {phase}: {e.detail}"
                ),
            )
        completed.append(phase)

    if not completed:
        return RunAllResponse(completed_phases=[], message="All steps were already complete — nothing to run.")
    return RunAllResponse(
        completed_phases=completed,
        message=f"Completed step(s) {', '.join(str(p) for p in completed)}.",
    )


@router.get("/{project_id}/phases/{phase}", response_model=PhaseResultResponse)
def get_phase_result(project_id: str, phase: int, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM phase_results WHERE project_id = %s AND phase = %s", (project_id, phase))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Step not started")
    return PhaseResultResponse(
        phase=row["phase"], status=row["status"], result=row["result"],
        approved_at=row["approved_at"], updated_at=row["updated_at"],
    )
