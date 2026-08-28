import json
import math
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status

from app.database import get_conn
from app.engines.evidence_router import SAMPLE_FILENAME_RE, detect_control_test_mode, is_junk_path
from app.engines.rcm_normalizer import normalize_rcm_file
from app.engines.rcm_overlay import load_effective_controls
from app.engines.sop_adequacy_engine import parse_sop_steps
from app.engines.text_extraction import extract_text
from app.models.schemas import (
    ControlResponse,
    EvidenceFolderControlSummary,
    EvidenceUploadResponse,
    RcmUploadResponse,
    SopUploadResponse,
)
from app.security import require_auth
from app.storage.files import clear_evidence_root, evidence_dir, save_evidence_file, save_rcm_upload, save_sop_upload

router = APIRouter(prefix="/api/projects", tags=["upload"])

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_ALLOWED_SUFFIXES = (".xlsx", ".xls", ".csv")
_ALLOWED_SOP_SUFFIXES = (".docx", ".pdf", ".txt")


def _require_project(project_id: str, user_id: str) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM projects WHERE id = %s AND created_by = %s", (project_id, user_id))
            if cur.fetchone() is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


def _clean_value(value):
    """psycopg/JSON can't serialize pandas NaN/NaT — normalize to None."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value).strip() if str(value).strip().lower() not in ("nan", "none", "null") else None


@router.post("/{project_id}/upload", response_model=RcmUploadResponse)
async def upload_rcm(project_id: str, file: UploadFile, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])

    original_name = file.filename or "rcm_upload"
    suffix = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix}'. Use .xlsx, .xls, or .csv.")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 100MB upload limit.")

    dest_path = save_rcm_upload(project_id, original_name, content)

    try:
        normalized = normalize_rcm_file(dest_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not parse RCM file: {e}")

    df = normalized["df"]
    if "control_id" not in df.columns or df.empty:
        raise HTTPException(
            status_code=422,
            detail="Could not find a Control ID column, or the file has no data rows. "
            "Check that the file has a header row with a Control ID / Control Description column.",
        )

    rcm_upload_id = str(uuid.uuid4())
    row_count = len(df)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rcm_uploads (id, project_id, file_path, original_name, column_map, passthrough, row_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    rcm_upload_id, project_id, str(dest_path), original_name,
                    json.dumps(normalized["column_map"]), json.dumps(normalized["passthrough"]), row_count,
                ),
            )

            # Replace any prior control set for this project (latest upload wins;
            # original file itself is preserved untouched on disk as the audit trail).
            cur.execute("DELETE FROM control_overlays WHERE project_id = %s", (project_id,))
            cur.execute("DELETE FROM controls WHERE project_id = %s", (project_id,))

            passthrough_cols = normalized["passthrough"]
            seen_control_ids: set[str] = set()
            for _, row in df.iterrows():
                control_id = _clean_value(row.get("control_id"))
                if not control_id or control_id in seen_control_ids:
                    continue
                seen_control_ids.add(control_id)

                raw_row = {col: _clean_value(row.get(col)) for col in df.columns if col in passthrough_cols}
                for extra in ("risk_probability", "risk_impact"):
                    if extra in df.columns:
                        raw_row[extra] = _clean_value(row.get(extra))

                cur.execute(
                    """
                    INSERT INTO controls (
                        id, project_id, rcm_upload_id, control_id, control_description, risk_description,
                        risk_level, control_type, control_nature, control_frequency, control_owner, process, raw_row
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(uuid.uuid4()), project_id, rcm_upload_id, control_id,
                        _clean_value(row.get("control_description")),
                        _clean_value(row.get("risk_description")),
                        _clean_value(row.get("risk_level")),
                        _clean_value(row.get("control_type")),
                        _clean_value(row.get("control_nature")),
                        _clean_value(row.get("control_frequency")),
                        _clean_value(row.get("control_owner")),
                        _clean_value(row.get("process")),
                        json.dumps(raw_row),
                    ),
                )

            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result)
                VALUES (%s, %s, 1, 'pending', %s)
                ON CONFLICT (project_id, phase) DO UPDATE SET status = 'pending', result = %s, updated_at = NOW()
                """,
                (str(uuid.uuid4()), project_id, json.dumps({}), json.dumps({})),
            )
            cur.execute(
                "UPDATE projects SET current_phase = 1, "
                "phase_status = jsonb_set(phase_status, '{1}', '\"pending\"'), updated_at = NOW() "
                "WHERE id = %s",
                (project_id,),
            )
        conn.commit()

    return RcmUploadResponse(
        rcm_upload_id=rcm_upload_id,
        row_count=len(seen_control_ids),
        column_map=normalized["column_map"],
        passthrough=[c for c in normalized["passthrough"] if c not in ("risk_probability", "risk_impact")],
        still_missing=normalized["still_missing"],
        header_row_index=normalized["header_row_index"],
    )


@router.get("/{project_id}/controls", response_model=list[ControlResponse])
def list_controls(project_id: str, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])
    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
    return [ControlResponse(**c) for c in controls]


@router.post("/{project_id}/upload-folder", response_model=EvidenceUploadResponse)
async def upload_evidence_folder(
    project_id: str,
    files: list[UploadFile],
    relative_paths: list[str] = Form(...),
    auth: dict = Depends(require_auth),
):
    """Accepts an evidence folder upload. Each file's client-side relative
    path (webkitRelativePath, e.g. "evidence/CTRL-001/sample_1/invoice.pdf")
    is sent alongside it in relative_paths (same order/index). The first
    path segment is the enforced single root folder and is stripped; the
    second segment must match a known Control ID (exact, after Unicode
    dash/whitespace normalization)."""
    _require_project(project_id, auth["user_id"])

    if len(files) != len(relative_paths):
        raise HTTPException(status_code=422, detail="files and relative_paths must be the same length.")

    with get_conn() as conn:
        controls = load_effective_controls(conn, project_id)
    if not controls:
        raise HTTPException(status_code=400, detail="No RCM loaded for this project. Upload an RCM first.")

    control_id_lookup = {_normalize_path_segment(c["control_id"]).lower(): c["control_id"] for c in controls}

    # Pass 1 — string-only validation of the single-root-folder constraint,
    # before any file bytes are read. Rejects a multi-root upload cheaply
    # instead of buffering every file's content first.
    roots_seen: set[str] = set()
    parsed_paths: list[list[str]] = []
    for rel_path in relative_paths:
        parts = [p for p in rel_path.replace("\\", "/").split("/") if p]
        parsed_paths.append(parts)
        if parts and not is_junk_path(parts):
            roots_seen.add(parts[0])

    if len(roots_seen) > 1:
        raise HTTPException(
            status_code=422,
            detail=f"Evidence upload must be a single root folder; found {len(roots_seen)}: {sorted(roots_seen)}.",
        )

    # Pass 2 — read and bucket file contents now that the root check passed.
    per_control_files: dict[str, list[tuple[str | None, str, bytes]]] = {}
    unmatched: set[str] = set()
    control_segment_variants: dict[str, set[str]] = {}
    total_saved = 0

    for upload_file, rel_path, parts in zip(files, relative_paths, parsed_paths):
        if not parts or is_junk_path(parts):
            continue

        remainder = parts[1:]
        if not remainder:
            continue

        control_segment = remainder[0]
        normalized_control = _normalize_path_segment(control_segment).lower()
        matched_control_id = control_id_lookup.get(normalized_control)
        if matched_control_id is None:
            unmatched.add(control_segment)
            continue

        # Two differently-spelled/cased folder names (e.g. "CTRL-001" and
        # "ctrl-001") both matching the same control would otherwise merge
        # silently — reject instead, since that's more likely two separate
        # upload attempts than one intentional folder.
        variants = control_segment_variants.setdefault(matched_control_id, set())
        variants.add(control_segment)
        if len(variants) > 1:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Found multiple differently-named folders that all match Control ID "
                    f"'{matched_control_id}': {sorted(variants)}. Use exactly one folder name per control."
                ),
            )

        inner = remainder[1:]
        content = await upload_file.read()
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"File '{rel_path}' exceeds the 100MB upload limit.")

        # inner = ["sample_1", "file.pdf"] -> file inside a sample subfolder
        # inner = ["sample_1.pdf"]         -> a sample-named file directly under
        #                                     the control folder; its stem IS the
        #                                     sample, so route it into a sample_1/
        #                                     subdirectory. (Storing it flat would
        #                                     break classification: save_evidence_file
        #                                     prefixes a uuid, and SAMPLE_FILENAME_RE
        #                                     is anchored, so "<uuid>_sample_1.pdf"
        #                                     never matches and the whole control
        #                                     would be misread as invalid_format.)
        # inner = [] or a non-sample name   -> flat file, no sample.
        filename = inner[-1] if inner else control_segment
        if len(inner) >= 2:
            sample_id = inner[0]
        elif len(inner) == 1 and SAMPLE_FILENAME_RE.match(inner[0]):
            sample_id = Path(inner[0]).stem
        else:
            sample_id = None

        per_control_files.setdefault(matched_control_id, []).append((sample_id, filename, content))

    # Refuse an upload that matched nothing rather than wiping existing
    # evidence for it — otherwise a mistyped folder name silently destroys a
    # project's whole evidence set.
    if not per_control_files:
        raise HTTPException(
            status_code=422,
            detail=(
                "No uploaded folder matched a Control ID in this project"
                + (f" (unmatched folder names: {sorted(unmatched)})" if unmatched else "")
                + ". Existing evidence was left unchanged. Expected one subfolder per Control ID."
            ),
        )

    summaries: list[EvidenceFolderControlSummary] = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM evidence_files WHERE project_id = %s", (project_id,))
            # Destroy the old files only once the DB delete has succeeded and
            # we're committed to writing the replacement set. Doing this before
            # opening the transaction risked deleting evidence while the rows
            # survived — Phase 4 would then read missing files, score every
            # attribute "No", and report Material Weakness on evidence that was
            # merely deleted.
            clear_evidence_root(project_id)
            for control_id, entries in per_control_files.items():
                saved_paths: list[tuple[str | None, str, bytes, Path]] = []
                for sample_id, filename, content in entries:
                    dest = save_evidence_file(project_id, control_id, sample_id, filename, content)
                    saved_paths.append((sample_id, filename, content, dest))
                    total_saved += 1

                classification = detect_control_test_mode(_control_evidence_root(project_id, control_id))
                for sample_id, filename, content, dest in saved_paths:
                    cur.execute(
                        """
                        INSERT INTO evidence_files (id, project_id, control_id, sample_id, file_path, original_name, file_type, file_size, detected_mode)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            str(uuid.uuid4()), project_id, control_id, sample_id, str(dest),
                            filename, Path(filename).suffix.lstrip("."), len(content),
                            classification.detected_mode,
                        ),
                    )
                summaries.append(
                    EvidenceFolderControlSummary(
                        control_id=control_id,
                        detected_mode=classification.detected_mode,
                        sample_count=len(classification.sample_ids),
                        file_count=classification.file_count,
                    ),
                )

            # Controls with no uploaded evidence at all are still reported as no_evidence.
            uploaded_ids = set(per_control_files.keys())
            for c in controls:
                if c["control_id"] not in uploaded_ids:
                    summaries.append(
                        EvidenceFolderControlSummary(
                            control_id=c["control_id"], detected_mode="no_evidence", sample_count=0, file_count=0,
                        ),
                    )

            # Mark Phase 2 stale, but KEEP the previous result. Wiping it to
            # '{}' opened a window — from this commit until the re-run wrote
            # new results — where the row existed but held nothing, and an
            # export taken in that window silently produced an empty
            # workbook. Consumers gate on status='done', so stale-but-real
            # data is strictly better here than no data.
            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result)
                VALUES (%s, %s, 2, 'pending', '{}'::jsonb)
                ON CONFLICT (project_id, phase) DO UPDATE SET status = 'pending', updated_at = NOW()
                """,
                (str(uuid.uuid4()), project_id),
            )
            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, '{2}', '\"pending\"'), updated_at = NOW() "
                "WHERE id = %s",
                (project_id,),
            )
        conn.commit()

    return EvidenceUploadResponse(
        controls=summaries, total_files_saved=total_saved, unmatched_control_ids=sorted(unmatched),
    )


def _normalize_path_segment(s: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKC", s or "")
    normalized = "".join("-" if unicodedata.category(ch) == "Pd" else ch for ch in normalized)
    return normalized.strip()


def _control_evidence_root(project_id: str, control_id: str) -> Path:
    return evidence_dir(project_id, control_id)


@router.post("/{project_id}/upload-sop", response_model=SopUploadResponse)
async def upload_sop(project_id: str, file: UploadFile, auth: dict = Depends(require_auth)):
    _require_project(project_id, auth["user_id"])

    original_name = file.filename or "sop_upload"
    suffix = "." + original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if suffix not in _ALLOWED_SOP_SUFFIXES:
        raise HTTPException(status_code=422, detail=f"Unsupported file type '{suffix}'. Use .docx, .pdf, or .txt.")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 100MB upload limit.")

    dest_path = save_sop_upload(project_id, original_name, content)

    try:
        extracted_text = extract_text(dest_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not extract text from SOP file: {e}")

    if not extracted_text.strip():
        raise HTTPException(status_code=422, detail="No extractable text found in the uploaded SOP file.")

    parsed_steps = parse_sop_steps(extracted_text)
    sop_upload_id = str(uuid.uuid4())

    with get_conn() as conn:
        with conn.cursor() as cur:
            # Only one active SOP per project for v1 — replace any prior upload.
            cur.execute("DELETE FROM sop_uploads WHERE project_id = %s", (project_id,))
            cur.execute(
                """
                INSERT INTO sop_uploads (id, project_id, file_path, original_name, extracted_text, parsed_steps)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (sop_upload_id, project_id, str(dest_path), original_name, extracted_text, json.dumps(parsed_steps)),
            )
            cur.execute(
                """
                INSERT INTO phase_results (id, project_id, phase, status, result)
                VALUES (%s, %s, 3, 'pending', '{}'::jsonb)
                ON CONFLICT (project_id, phase) DO UPDATE SET status = 'pending', result = '{}'::jsonb, updated_at = NOW()
                """,
                (str(uuid.uuid4()), project_id),
            )
            cur.execute(
                "UPDATE projects SET phase_status = jsonb_set(phase_status, '{3}', '\"pending\"'), updated_at = NOW() "
                "WHERE id = %s",
                (project_id,),
            )
        conn.commit()

    return SopUploadResponse(sop_upload_id=sop_upload_id, filename=original_name, parsed_step_count=len(parsed_steps))
