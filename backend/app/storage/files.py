import re
import shutil
import unicodedata
import uuid
from pathlib import Path

from app.config import get_settings

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(original_name: str) -> str:
    name = unicodedata.normalize("NFKC", original_name).strip()
    name = _UNSAFE_CHARS.sub("_", name)
    return name or "file"


def rcm_upload_dir(project_id: str) -> Path:
    path = get_settings().storage_path / "uploads" / project_id / "rcm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_rcm_upload(project_id: str, original_name: str, content: bytes) -> Path:
    directory = rcm_upload_dir(project_id)
    dest = directory / f"{uuid.uuid4().hex}_{_safe_filename(original_name)}"
    dest.write_bytes(content)
    return dest


def evidence_root_dir(project_id: str) -> Path:
    path = get_settings().storage_path / "uploads" / project_id / "evidence"
    path.mkdir(parents=True, exist_ok=True)
    return path


def evidence_dir(project_id: str, control_id: str) -> Path:
    path = evidence_root_dir(project_id) / _safe_filename(control_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_evidence_root(project_id: str) -> None:
    """Removes all previously-uploaded evidence files for a project before a
    fresh folder upload is written, so a re-upload can't leave stale files
    on disk with no corresponding evidence_files DB row (those stale files
    would otherwise still be picked up by detect_control_test_mode())."""
    root = evidence_root_dir(project_id)
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def save_evidence_file(project_id: str, control_id: str, sample_id: str | None, original_name: str, content: bytes) -> Path:
    directory = evidence_dir(project_id, control_id)
    if sample_id:
        directory = directory / _safe_filename(sample_id)
        directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{uuid.uuid4().hex}_{_safe_filename(original_name)}"
    dest.write_bytes(content)
    return dest


def artifacts_dir(project_id: str) -> Path:
    path = get_settings().storage_path / "artifacts" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def adequacy_root_dir(project_id: str) -> Path:
    path = get_settings().storage_path / "uploads" / project_id / "adequacy"
    path.mkdir(parents=True, exist_ok=True)
    return path


def adequacy_dir(project_id: str, control_id: str | None) -> Path:
    """Per-control subfolder for SOPs/workpapers; a project-wide SOP
    (control_id None) goes in a _process folder."""
    root = adequacy_root_dir(project_id)
    path = root / (_safe_filename(control_id) if control_id else "_process")
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_adequacy_file(project_id: str, control_id: str | None, original_name: str, content: bytes) -> Path:
    directory = adequacy_dir(project_id, control_id)
    dest = directory / f"{uuid.uuid4().hex}_{_safe_filename(original_name)}"
    dest.write_bytes(content)
    return dest


def clear_adequacy_root(project_id: str) -> None:
    """Removes all previously-uploaded SOP/workpaper files before a fresh
    folder upload, so a re-upload can't leave stale files with no DB row."""
    root = adequacy_root_dir(project_id)
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def delete_project_files(project_id: str) -> None:
    """Removes every file a project owns: its uploads (RCM, evidence, SOP)
    and its generated artifacts.

    Deliberately best-effort — it runs AFTER the database rows are committed,
    so a filesystem error can't roll back a delete the user was told
    succeeded. The worst case is orphaned bytes on disk with nothing
    referencing them, which is recoverable; the reverse (rows gone, request
    failed) is not.

    project_id is a UUID from the database, never raw user input, so it
    cannot traverse out of the storage root.
    """
    root = get_settings().storage_path
    for path in (root / "uploads" / project_id, root / "artifacts" / project_id):
        shutil.rmtree(path, ignore_errors=True)
