import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg.rows import dict_row

from pathlib import Path

from app.database import get_conn
from app.engines import progress
from app.engines.remediation_engine import build_remediation_plan
from app.engines.evidence_gap_engine import assess_evidence_gaps, generate_required_documents
from app.engines.rcm_overlay import load_effective_controls
from app.engines.risk_inference import (
    DEFAULT_BANDS,
    DEFAULT_SCORE_MAP,
    build_risk_matrix,
    infer_risk_levels,
    validate_weighting,
)
from app.engines.risk_scorer import score_controls
from app.engines.sop_adequacy_engine import run_sop_adequacy_assessment
from app.engines.testing_engine import run_batch_testing
from app.engines.timeline_sufficiency import run_timeline_sufficiency_check
from app.models.schemas import PhaseResultResponse, RiskWeightingRequest, RunAllResponse
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
    work ... "mark phase N done"), which made concurrent runs a TOCTOU race:
    both saw the gate open, both ran the full pipeline, and the second
    silently clobbered the first's results.

    Holding a row lock across the LLM work would block for minutes, so
    instead we take the lock only long enough to check preconditions and
    flip phase_status to 'running'. A second caller then blocks on the lock,
    wakes to find 'running', and is rejected — while the slow work happens
    with no lock held.

    `check(project)` receives the locked project row and should raise an
    HTTPException if its preconditions aren't met.
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
                    detail=f"Phase {phase} is already running for this project. Wait for it to finish.",
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
    """Clears a 'running' claim when the phase fails, so the user can retry
    instead of being locked out by a stale claim."""
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
        logger.exception("Could not release the 'running' claim on phase %s of project %s", phase, project_id)


def _fetch_phase_result(conn, project_id: str, phase: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM phase_results WHERE project_id = %s AND phase = %s", (project_id, phase))
        return cur.fetchone()


@router.post("/{project_id}/phases/1/run", response_model=PhaseResultResponse)
def run_risk_prioritization(project_id: str, auth: dict = Depends(require_auth)):
    def _check(project: dict) -> None:
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1 FROM controls WHERE project_id = %s LIMIT 1", (project_id,))
                if cur.fetchone() is None:
                    raise HTTPException(
                        status_code=400, detail="No RCM loaded for this project. Upload an RCM first."
                    )

    _claim_phase(project_id, auth["user_id"], 1, _check)
    try:
        return _run_phase1_body(project_id, auth)
    except Exception:
        _release_phase_claim(project_id, 1)
        raise


def _controls_missing_risk_level(controls: list[dict]) -> list[dict]:
    return [c for c in controls if not str(c.get("risk_level") or "").strip()]


def _write_phase1_gate(conn, project_id: str, payload: dict, phase_status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO phase_results (id, project_id, phase, status, result)
            VALUES (gen_random_uuid()::text, %s, 1, %s, %s)
            ON CONFLICT (project_id, phase) DO UPDATE
                SET status = EXCLUDED.status, result = EXCLUDED.result, updated_at = NOW()
            """,
            (project_id, phase_status, json.dumps(payload)),
        )
        cur.execute(
            "UPDATE projects SET phase_status = jsonb_set(phase_status, '{1}', %s::jsonb), updated_at = NOW() "
            "WHERE id = %s",
            (json.dumps(phase_status), project_id),
        )
    conn.commit()


def _run_phase1_body(project_id: str, auth: dict, weighting: dict | None = None) -> PhaseResultResponse:
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project. Upload an RCM first.")

        missing = _controls_missing_risk_level(controls)

        # Gate 1 — the RCM has controls with no Risk Level, and the user
        # hasn't yet told us how to weight Probability x Impact. Ask before
        # inferring: the weighting materially changes every rating, so
        # picking one silently would bury a real audit judgement.
        if missing and weighting is None:
            result_payload = {
                "awaiting_weighting": True,
                "controls_missing_risk_level": [c["control_id"] for c in missing],
                "default_weighting": {
                    "score_map": DEFAULT_SCORE_MAP,
                    "bands": [{"threshold": t, "label": l} for t, l in DEFAULT_BANDS],
                },
                "default_matrix": build_risk_matrix(),
            }
            _write_phase1_gate(conn, project_id, result_payload, "awaiting_approval")
            saved = _fetch_phase_result(conn, project_id, 1)
            return PhaseResultResponse(
                phase=1, status="awaiting_approval", result=saved["result"],
                approved_at=saved["approved_at"], updated_at=saved["updated_at"],
            )

        score_map, bands = DEFAULT_SCORE_MAP, DEFAULT_BANDS
        if weighting is not None:
            score_map, bands = weighting["score_map"], weighting["bands"]

        pending_inferences = infer_risk_levels(controls, score_map, bands)

        if pending_inferences:
            # Gate 2 — inferred risk levels are staged, not committed, until
            # the user approves them via /phases/1/approve.
            result_payload = {
                "pending_risk_inferences": pending_inferences,
                "controls_pending_inference": len(pending_inferences),
                "weighting_used": {
                    "score_map": score_map,
                    "bands": [{"threshold": t, "label": l} for t, l in bands],
                    "is_default": weighting is None or weighting.get("is_default", False),
                },
                "risk_matrix": build_risk_matrix(score_map, bands),
            }
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phase_results (id, project_id, phase, status, result)
                    VALUES (gen_random_uuid()::text, %s, 1, 'awaiting_approval', %s)
                    ON CONFLICT (project_id, phase) DO UPDATE
                        SET status = 'awaiting_approval', result = %s, updated_at = NOW()
                    """,
                    (project_id, json.dumps(result_payload), json.dumps(result_payload)),
                )
                cur.execute(
                    "UPDATE projects SET phase_status = jsonb_set(phase_status, '{1}', '\"awaiting_approval\"'), "
                    "updated_at = NOW() WHERE id = %s",
                    (project_id,),
                )
            conn.commit()
            saved = _fetch_phase_result(conn, project_id, 1)
            return PhaseResultResponse(
                phase=1, status="awaiting_approval", result=saved["result"],
                approved_at=saved["approved_at"], updated_at=saved["updated_at"],
            )

        result_payload = score_controls(controls)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result, approved_by, approved_at)
                VALUES (gen_random_uuid()::text, %s, 1, 'done', %s, %s, NOW())
                ON CONFLICT (project_id, phase) DO UPDATE
                    SET status = 'done', result = %s, approved_by = %s, approved_at = NOW(), updated_at = NOW()
                """,
                (project_id, json.dumps(result_payload), auth["user_id"], json.dumps(result_payload), auth["user_id"]),
            )
            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, '{1}', '\"done\"'), "
                "updated_at = NOW() WHERE id = %s",
                (project_id,),
            )
        conn.commit()
        saved = _fetch_phase_result(conn, project_id, 1)

    return PhaseResultResponse(
        phase=1, status="done", result=saved["result"], approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


@router.post("/{project_id}/phases/1/weighting", response_model=PhaseResultResponse)
def set_risk_weighting(project_id: str, body: RiskWeightingRequest, auth: dict = Depends(require_auth)):
    """Accepts the user's Probability x Impact weighting choice and runs the
    risk-level inference with it.

    `use_default=true` uses the standard model (Low=1, Medium=3, High=6;
    <=5 Low, <=17 Medium, <=35 High, else Critical). Otherwise score_map and
    bands are required and are validated — a weighting whose ordering is
    inverted, or whose top band is unreachable, would silently produce
    meaningless ratings, so it's rejected with an explanation rather than
    quietly accepted.
    """
    _require_project(project_id, auth["user_id"])

    if body.use_default:
        weighting = {"score_map": DEFAULT_SCORE_MAP, "bands": DEFAULT_BANDS, "is_default": True}
    else:
        if not body.score_map or not body.bands:
            raise HTTPException(
                status_code=422,
                detail="A custom weighting needs both score_map (low/medium/high) and bands.",
            )
        try:
            score_map, bands = validate_weighting(
                body.score_map, [{"threshold": b.threshold, "label": b.label} for b in body.bands]
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        weighting = {"score_map": score_map, "bands": bands, "is_default": False}

    return _run_phase1_body(project_id, auth, weighting)


@router.post("/{project_id}/phases/1/approve", response_model=PhaseResultResponse)
def approve_risk_inferences(project_id: str, auth: dict = Depends(require_auth)):
    """Commits the staged risk-level inferences from run_risk_prioritization
    into the control_overlays table (non-destructive — original upload is
    untouched), then re-runs scoring now that risk_level is fully resolved.

    Everything here is ONE transaction. Committing the overlays separately
    (as this used to) meant a failure in the scoring step left the overlays
    durably applied while phase_results still advertised the same
    inferences as 'pending' — the staged set the user was looking at no
    longer matched what had actually been written.
    """
    _require_project(project_id, auth["user_id"])

    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Lock the project so a concurrent approve (or a phase-1 re-run)
            # can't interleave with this one.
            cur.execute(
                "SELECT id FROM projects WHERE id = %s AND created_by = %s FOR UPDATE",
                (project_id, auth["user_id"]),
            )
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

            cur.execute("SELECT result FROM phase_results WHERE project_id = %s AND phase = 1", (project_id,))
            row = cur.fetchone()
        if row is None or "pending_risk_inferences" not in (row["result"] or {}):
            raise HTTPException(status_code=400, detail="No pending risk-level inferences to approve.")

        pending = row["result"]["pending_risk_inferences"]
        with conn.cursor() as cur:
            for control_id, inference in pending.items():
                cur.execute(
                    """
                    INSERT INTO control_overlays (id, project_id, control_id, field, new_value, source)
                    VALUES (gen_random_uuid()::text, %s, %s, 'risk_level', %s, 'llm_inference')
                    ON CONFLICT (project_id, control_id, field) DO UPDATE
                        SET new_value = %s, source = 'llm_inference', updated_at = NOW()
                    """,
                    (project_id, control_id, inference["value"], inference["value"]),
                )

        # Reads the overlays written above through the same uncommitted
        # transaction, so scoring sees exactly what will be persisted.
        controls = load_effective_controls(conn, project_id)
        result_payload = score_controls(controls)
        result_payload["applied_risk_inferences"] = pending

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE phase_results SET status = 'done', result = %s, approved_by = %s, approved_at = NOW(), updated_at = NOW()
                WHERE project_id = %s AND phase = 1
                """,
                (json.dumps(result_payload), auth["user_id"], project_id),
            )
            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, '{1}', '\"done\"'), "
                "updated_at = NOW() WHERE id = %s",
                (project_id,),
            )
        conn.commit()
        saved = _fetch_phase_result(conn, project_id, 1)

    return PhaseResultResponse(
        phase=1, status="done", result=saved["result"], approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


@router.post("/{project_id}/phases/2/run", response_model=PhaseResultResponse)
def run_evidence_gap_analysis(project_id: str, auth: dict = Depends(require_auth)):
    """Precondition: Phase 1 must be approved (done) before evidence gap
    analysis can run — enforced here, not just implied by the UI."""

    def _check(project: dict) -> None:
        if (project["phase_status"] or {}).get("1") != "done":
            raise HTTPException(
                status_code=400, detail="Phase 1 (RACM validation) must be completed and approved first."
            )

    _claim_phase(project_id, auth["user_id"], 2, _check)
    try:
        return _run_phase2_body(project_id, auth)
    except Exception:
        _release_phase_claim(project_id, 2)
        raise


def _run_phase2_body(project_id: str, auth: dict) -> PhaseResultResponse:
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, sample_id, original_name, detected_mode FROM evidence_files WHERE project_id = %s",
                (project_id,),
            )
            evidence_rows = cur.fetchall()

        filenames_by_control: dict[str, list[str]] = {}
        mode_by_control: dict[str, str] = {}
        for row in evidence_rows:
            filenames_by_control.setdefault(row["control_id"], []).append(row["original_name"])
            mode_by_control[row["control_id"]] = row["detected_mode"]

        for c in controls:
            mode_by_control.setdefault(c["control_id"], "no_evidence")

        required_documents = generate_required_documents(controls)
        result_payload = assess_evidence_gaps(controls, required_documents, filenames_by_control, mode_by_control)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result, approved_by, approved_at)
                VALUES (gen_random_uuid()::text, %s, 2, 'done', %s, %s, NOW())
                ON CONFLICT (project_id, phase) DO UPDATE
                    SET status = 'done', result = %s, approved_by = %s, approved_at = NOW(), updated_at = NOW()
                """,
                (project_id, json.dumps(result_payload), auth["user_id"], json.dumps(result_payload), auth["user_id"]),
            )
            cur.execute(
                "UPDATE projects SET current_phase = 2, phase_status = jsonb_set(phase_status, '{2}', '\"done\"'), "
                "updated_at = NOW() WHERE id = %s",
                (project_id,),
            )
        conn.commit()
        saved = _fetch_phase_result(conn, project_id, 2)

    return PhaseResultResponse(
        phase=2, status="done", result=saved["result"], approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


@router.post("/{project_id}/phases/3/run", response_model=PhaseResultResponse)
def run_adequacy_assessment(project_id: str, auth: dict = Depends(require_auth)):
    """Preconditions: Phase 2 must be approved (done) AND a SOP must be
    uploaded before adequacy assessment can run — both enforced here, not
    just implied by the UI. The timeline-sufficiency check runs as its own
    step inside this same phase (needs evidence + audit period, not the
    SOP), matching the plan's design of one phase_results row for both."""

    def _check(project: dict) -> None:
        if (project["phase_status"] or {}).get("2") != "done":
            raise HTTPException(status_code=400, detail="Phase 2 (evidence review) must be completed first.")
        # Checked as part of the claim so the SOP can't be deleted between
        # the gate and the run.
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute("SELECT 1 FROM sop_uploads WHERE project_id = %s LIMIT 1", (project_id,))
                if cur.fetchone() is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "No SOP has been uploaded for this project. Upload an SOP document before running "
                            "the adequacy assessment."
                        ),
                    )

    _claim_phase(project_id, auth["user_id"], 3, _check)
    try:
        return _run_phase3_body(project_id, auth)
    except Exception:
        _release_phase_claim(project_id, 3)
        raise


def _run_phase3_body(project_id: str, auth: dict) -> PhaseResultResponse:
    project = _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, original_name, parsed_steps FROM sop_uploads WHERE project_id = %s "
                "ORDER BY uploaded_at DESC LIMIT 1",
                (project_id,),
            )
            sop_row = cur.fetchone()
        if sop_row is None:
            raise HTTPException(
                status_code=400,
                detail="No SOP has been uploaded for this project. Upload an SOP document before running the adequacy assessment.",
            )

        controls = load_effective_controls(conn, project_id)
        if not controls:
            raise HTTPException(status_code=400, detail="No RCM loaded for this project.")

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, original_name FROM evidence_files WHERE project_id = %s",
                (project_id,),
            )
            evidence_rows = cur.fetchall()

        filenames_by_control: dict[str, list[str]] = {}
        for row in evidence_rows:
            filenames_by_control.setdefault(row["control_id"], []).append(row["original_name"])

        sop_steps = sop_row["parsed_steps"] or []
        # Publish per-control progress so the UI can show a percentage for
        # what is otherwise a multi-minute opaque wait.
        progress.set_progress(project_id, progress.ADEQUACY, 0, len(controls))
        try:
            adequacy = run_sop_adequacy_assessment(
                controls,
                sop_steps,
                on_progress=lambda cid, done, total: progress.set_progress(
                    project_id, progress.ADEQUACY, done, total, cid
                ),
            )
        finally:
            progress.clear_progress(project_id, progress.ADEQUACY)
        timeline_sufficiency = run_timeline_sufficiency_check(
            controls, filenames_by_control, project["audit_period_start"], project["audit_period_end"],
        )
        timeline_issues_count = sum(1 for t in timeline_sufficiency if t["status"] != "sufficient")

        result_payload = {
            "stats": {
                **adequacy["counts"],
                "timeline_issues_count": timeline_issues_count,
            },
            "sop_upload": {"filename": sop_row["original_name"], "parsed_step_count": len(sop_steps)},
            "control_alignment": adequacy["control_alignment"],
            "coverage_gaps": adequacy["coverage_gaps"],
            "control_type_mix": adequacy["control_type_mix"],
            "deficiencies": adequacy["deficiencies"],
            "timeline_sufficiency": timeline_sufficiency,
        }

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result, approved_by, approved_at)
                VALUES (gen_random_uuid()::text, %s, 3, 'done', %s, %s, NOW())
                ON CONFLICT (project_id, phase) DO UPDATE
                    SET status = 'done', result = %s, approved_by = %s, approved_at = NOW(), updated_at = NOW()
                """,
                (project_id, json.dumps(result_payload), auth["user_id"], json.dumps(result_payload), auth["user_id"]),
            )
            cur.execute(
                "UPDATE projects SET current_phase = 3, phase_status = jsonb_set(phase_status, '{3}', '\"done\"'), "
                "updated_at = NOW() WHERE id = %s",
                (project_id,),
            )
        conn.commit()
        saved = _fetch_phase_result(conn, project_id, 3)

    return PhaseResultResponse(
        phase=3, status="done", result=saved["result"], approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


def _risk_weight(risk_level: str | None) -> float:
    return {"high": 3.0, "medium": 2.0, "low": 1.0}.get((risk_level or "medium").strip().lower(), 2.0)


def _short_control_titles(controls: list[dict]) -> dict[str, str]:
    """Card-sized labels for a set of controls.

    RCMs carry a full control_description and no short name. Generated RCMs
    in particular template every row the same way -- "Management performs the
    X control and retains sample-level evidence" -- so taking the opening
    words yields the same boilerplate for every control and the distinguishing
    part is exactly what gets cut. The title is therefore found by stripping
    the word-prefix and word-suffix COMMON TO THE WHOLE SET, which is what
    isolates X. With a single control, or descriptions that share nothing,
    this reduces to the opening clause."""
    def clause(text: str) -> str:
        text = (text or "").strip()
        for sep in (" - ", " \u2014 ", ";", ":", ". "):
            if sep in text:
                text = text.split(sep)[0]
                break
        return text.rstrip(".").strip()

    clauses = {c["control_id"]: clause(c.get("control_description") or "") for c in controls}
    word_lists = {cid: t.split() for cid, t in clauses.items() if t}
    if not word_lists:
        return {cid: "" for cid in clauses}

    lists = list(word_lists.values())
    shortest = min(len(w) for w in lists)

    def common_run(index_of):
        """Words shared by every description at the given positional mapping.
        Capped below `shortest` so a title can never be emptied entirely."""
        run = 0
        while run < shortest - 1:
            probe = lists[0][index_of(run)].lower()
            if any(w[index_of(run)].lower() != probe for w in lists):
                break
            run += 1
        return run

    # Only worth stripping when there are several descriptions to compare.
    if len(lists) > 1:
        prefix = common_run(lambda i: i)
        suffix = common_run(lambda i: -1 - i)
    else:
        prefix = suffix = 0

    titles = {}
    for cid, words in word_lists.items():
        core = words[prefix : len(words) - suffix] or words
        # Drop a trailing bare "control" ("the tariff & fee assurance control")
        # -- it is a category word, not part of the name.
        if len(core) > 1 and core[-1].lower() in {"control", "process"}:
            core = core[:-1]
        title = " ".join(core[:6]).strip(" ,.")
        titles[cid] = title[:1].upper() + title[1:] if title else ""
    for cid in clauses:
        titles.setdefault(cid, "")
    return titles


def _build_phase4_payload(
    controls: list[dict],
    control_results: list[dict],
    format_issues: list[dict],
    phase3_result: dict | None = None,
) -> dict:
    controls_by_id = {c["control_id"]: c for c in controls}

    # The testing pane presents controls as cards, which need a title and the
    # inherent risk alongside the verdict. Both live on the RCM row, not on
    # the test result, so they are attached here rather than re-fetched in
    # the frontend.
    titles = _short_control_titles(controls)
    for r in control_results:
        control = controls_by_id.get(r["control_id"], {})
        r["control_title"] = titles.get(r["control_id"], "")
        r["risk_level"] = (control.get("risk_level") or "").strip() or None

    effective = sum(1 for r in control_results if r["effectiveness_status"] == "Effective")
    partially_effective = sum(1 for r in control_results if r["effectiveness_status"] == "Effective with Exceptions")
    ineffective = sum(1 for r in control_results if r["effectiveness_status"] == "Not Effective")
    unclosed_exceptions = sum(r["failed_samples"] for r in control_results)

    # Risk-weighted % effective, computed over controls that actually got a
    # verdict — format-issue controls and "Not Tested" ones are excluded from
    # the denominator rather than silently counted as failures.
    scored = [r for r in control_results if r["effectiveness_status"] != "Not Tested"]
    total_weight = sum(_risk_weight(controls_by_id.get(r["control_id"], {}).get("risk_level")) for r in scored)
    effective_weight = sum(
        _risk_weight(controls_by_id.get(r["control_id"], {}).get("risk_level"))
        * (1.0 if r["effectiveness_status"] == "Effective" else 0.5 if r["effectiveness_status"] == "Effective with Exceptions" else 0.0)
        for r in scored
    )
    overall_health_pct = round(effective_weight / total_weight, 4) if total_weight else 0.0

    material_weakness_indicators = [
        {
            "control_id": r["control_id"],
            "reason": f"Deviation rate {r['deviation_rate']:.0%} across {r['total_samples']} sample(s) — {r['deficiency_type']}.",
        }
        for r in control_results
        if r["deficiency_type"] == "Material Weakness"
    ]

    sampling_results = [
        {
            "control_id": r["control_id"],
            "frequency": controls_by_id.get(r["control_id"], {}).get("control_frequency") or "Not specified",
            "sample_size": r["total_samples"],
            "fails": r["failed_samples"],
            "verdict": r["effectiveness_status"],
            "deficiency_type": r["deficiency_type"],
            "deviation_rate": r["deviation_rate"],
        }
        for r in control_results
    ]

    # Per-sample remediation ranking, weighted by the control's Phase 1 risk
    # level and its Phase 3 SOP alignment. See engines/remediation_engine.py
    # for why those two determinants and not the verdict alone.
    p3 = phase3_result or {}
    alignment_by_control = {
        a["control_id"]: a.get("alignment", "")
        for a in (p3.get("control_alignment") or [])
    }
    # A control appears in control_alignment only when the SOP had something
    # to say about it, so that keyset IS the SOP-covered set.
    sop_covered = set(alignment_by_control)
    remediation_priorities = build_remediation_plan(
        control_results, controls_by_id, alignment_by_control, sop_covered
    )

    return {
        "stats": {
            "effective": effective,
            "partially_effective": partially_effective,
            "ineffective": ineffective,
            "unclosed_exceptions": unclosed_exceptions,
            "format_issue_count": len(format_issues),
        },
        "overall_health_pct": overall_health_pct,
        "tested_control_count": len(scored),
        "material_weakness_indicators": material_weakness_indicators,
        "format_issues": format_issues,
        "sampling_results": sampling_results,
        "control_results": control_results,
        "remediation_priorities": remediation_priorities,
    }


@router.post("/{project_id}/phases/4/run", response_model=PhaseResultResponse)
def run_control_testing(project_id: str, auth: dict = Depends(require_auth)):
    """Preconditions: Phase 3 done, and at least one approved attribute
    schema. Multi-sample only — controls without sample-organized evidence
    are reported in format_issues rather than tested."""

    def _check(project: dict) -> None:
        if (project["phase_status"] or {}).get("3") != "done":
            raise HTTPException(status_code=400, detail="Phase 3 (adequacy assessment) must be completed first.")
        with get_conn() as c:
            with c.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM control_attributes WHERE project_id = %s AND status = 'approved' LIMIT 1",
                    (project_id,),
                )
                if cur.fetchone() is None:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "No approved testing attributes. Generate the attribute preview and approve it "
                            "before testing."
                        ),
                    )

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

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, worksteps, attributes, sample_columns FROM control_attributes "
                "WHERE project_id = %s AND status = 'approved'",
                (project_id,),
            )
            approved_rows = cur.fetchall()
        if not approved_rows:
            raise HTTPException(
                status_code=400,
                detail="No approved testing attributes. Generate the attribute preview and approve it before testing.",
            )
        schemas_by_control = {
            r["control_id"]: {
                "worksteps": r["worksteps"] or [],
                "attributes": r["attributes"] or [],
                "sample_columns": r["sample_columns"] or [],
            }
            for r in approved_rows
        }

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT control_id, sample_id, file_path, original_name, detected_mode "
                "FROM evidence_files WHERE project_id = %s",
                (project_id,),
            )
            evidence_rows = cur.fetchall()

        modes_by_control: dict[str, str] = {}
        samples_by_control: dict[str, dict[str, list[Path]]] = {}
        for row in evidence_rows:
            control_id = row["control_id"]
            modes_by_control[control_id] = row["detected_mode"]
            # A sample-named file sitting directly under the control folder
            # has no sample_id column value; its filename stem is the sample.
            sample_id = row["sample_id"] or Path(row["original_name"] or "sample").stem
            samples_by_control.setdefault(control_id, {}).setdefault(sample_id, []).append(Path(row["file_path"]))

        for c in controls:
            modes_by_control.setdefault(c["control_id"], "no_evidence")

        progress.set_progress(project_id, progress.TESTING, 0, len(schemas_by_control))
        try:
            control_results, format_issues = run_batch_testing(
                controls, schemas_by_control, samples_by_control, modes_by_control,
                progress_callback=lambda cid, done, total: progress.set_progress(
                    project_id, progress.TESTING, done, total, cid
                ),
            )
        finally:
            progress.clear_progress(project_id, progress.TESTING)
        # Phase 3's alignment data feeds the remediation ranking. Absent (or
        # a failed read) simply drops the SOP determinant rather than
        # blocking the run — risk level and verdict still rank the work.
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT result FROM phase_results WHERE project_id = %s AND phase = 3 AND status = 'done'",
                (project_id,),
            )
            row3 = cur.fetchone()
        result_payload = _build_phase4_payload(
            controls, control_results, format_issues, (row3 or {}).get("result") or {}
        )

        with conn.cursor() as cur:
            for r in control_results:
                cur.execute(
                    """
                    INSERT INTO control_test_results
                        (id, project_id, control_id, test_mode, total_samples, passed_samples, failed_samples,
                         deviation_rate, effectiveness_status, deficiency_type, overall_remarks, sample_results)
                    VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, control_id) DO UPDATE
                        SET test_mode = EXCLUDED.test_mode, total_samples = EXCLUDED.total_samples,
                            passed_samples = EXCLUDED.passed_samples, failed_samples = EXCLUDED.failed_samples,
                            deviation_rate = EXCLUDED.deviation_rate,
                            effectiveness_status = EXCLUDED.effectiveness_status,
                            deficiency_type = EXCLUDED.deficiency_type,
                            overall_remarks = EXCLUDED.overall_remarks, sample_results = EXCLUDED.sample_results
                    """,
                    (
                        project_id, r["control_id"], r["test_mode"], r["total_samples"], r["passed_samples"],
                        r["failed_samples"], r["deviation_rate"], r["effectiveness_status"],
                        r["deficiency_type"], r["overall_remarks"], json.dumps(r["sample_results"]),
                    ),
                )
            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result, approved_by, approved_at)
                VALUES (gen_random_uuid()::text, %s, 4, 'done', %s, %s, NOW())
                ON CONFLICT (project_id, phase) DO UPDATE
                    SET status = 'done', result = %s, approved_by = %s, approved_at = NOW(), updated_at = NOW()
                """,
                (project_id, json.dumps(result_payload), auth["user_id"], json.dumps(result_payload), auth["user_id"]),
            )
            cur.execute(
                "UPDATE projects SET current_phase = 4, phase_status = jsonb_set(phase_status, '{4}', '\"done\"'), "
                "updated_at = NOW() WHERE id = %s",
                (project_id,),
            )
        conn.commit()
        saved = _fetch_phase_result(conn, project_id, 4)

    return PhaseResultResponse(
        phase=4, status="done", result=saved["result"], approved_at=saved["approved_at"], updated_at=saved["updated_at"],
    )


@router.post("/{project_id}/phases-run-all", response_model=RunAllResponse)
def run_all_remaining_phases(project_id: str, auth: dict = Depends(require_auth)):
    """Runs every not-yet-done phase in order, stopping at the first one whose
    preconditions aren't met (e.g. no SOP uploaded for Phase 3, or attributes
    not yet approved for Phase 4) and reporting exactly what's blocking —
    never silently skipping a phase."""
    project = _require_project(project_id, auth["user_id"])
    status_map = project["phase_status"] or {}

    runners = {
        1: run_risk_prioritization,
        2: run_evidence_gap_analysis,
        3: run_adequacy_assessment,
        4: run_control_testing,
    }

    completed: list[int] = []
    for phase in (1, 2, 3, 4):
        if status_map.get(str(phase)) == "done":
            continue
        try:
            result = runners[phase](project_id, auth)
        except HTTPException as e:
            return RunAllResponse(
                completed_phases=completed,
                stopped_at_phase=phase,
                blocked_reason=str(e.detail),
                message=(
                    f"Ran {len(completed)} phase(s), then stopped at Phase {phase}: {e.detail}"
                    if completed
                    else f"Could not start at Phase {phase}: {e.detail}"
                ),
            )
        completed.append(phase)
        # Phase 1 has two deliberate human gates — choosing the risk
        # weighting, then approving the inferred levels. Neither is a
        # failure, so stop and say exactly which one is waiting.
        if result.status == "awaiting_approval":
            if (result.result or {}).get("awaiting_weighting"):
                n = len((result.result or {}).get("controls_missing_risk_level") or [])
                return RunAllResponse(
                    completed_phases=completed,
                    stopped_at_phase=phase,
                    blocked_reason="Awaiting your choice of risk weighting.",
                    message=(
                        f"Paused at Phase {phase}: {n} control(s) have no Risk Level. Choose the "
                        "Probability x Impact weighting (default or custom) so I can infer them."
                    ),
                )
            return RunAllResponse(
                completed_phases=completed,
                stopped_at_phase=phase,
                blocked_reason="Awaiting your approval of the inferred risk levels.",
                message=(
                    f"Ran Phase {phase} and paused: some controls were missing a Risk Level, so the inferred "
                    "values need your approval before the remaining phases can run."
                ),
            )

    if not completed:
        return RunAllResponse(completed_phases=[], message="All phases were already complete — nothing to run.")
    return RunAllResponse(
        completed_phases=completed,
        message=f"Completed phase(s) {', '.join(str(p) for p in completed)}.",
    )


@router.get("/{project_id}/phases/{phase}", response_model=PhaseResultResponse)
def get_phase_result(project_id: str, phase: int, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM phase_results WHERE project_id = %s AND phase = %s", (project_id, phase))
            row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Phase not started")
    return PhaseResultResponse(
        phase=row["phase"], status=row["status"], result=row["result"],
        approved_at=row["approved_at"], updated_at=row["updated_at"],
    )
