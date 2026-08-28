"""
Evidence-folder classification shared by Phase 2 (gap analysis) and Phase 4
(effectiveness testing). Deliberately multi-sample-only per the build's
explicit deviation from the generalized spec: there is no single_sample
fallback. A control folder is either organized into samples, or it is
flagged invalid_format and excluded from testing until reorganized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

JUNK_BASENAMES = {".ds_store", "thumbs.db", "desktop.ini", ".localized"}

SAMPLE_FILENAME_RE = re.compile(r"^sample[_-]?(\d+)\b", re.IGNORECASE)
SAMPLE_DIRNAME_RE = re.compile(r"^sample[_-]?(\d+)$", re.IGNORECASE)


def is_junk_path(parts: list[str]) -> bool:
    for p in parts:
        lp = p.lower()
        if lp in JUNK_BASENAMES or p == "__MACOSX" or p.startswith("._") or p.startswith("~$"):
            return True
    return False


@dataclass
class ControlEvidenceClassification:
    control_id: str
    detected_mode: str  # 'multi_sample' | 'invalid_format' | 'no_evidence'
    sample_ids: list[str] = field(default_factory=list)
    file_count: int = 0


def detect_control_test_mode(control_folder: Path) -> ControlEvidenceClassification:
    """Classifies a single control's evidence folder. multi_sample requires
    either sample subfolders (sample1/, sample_2/...) or sample-named files
    (sample_1.pdf, sample-2.docx...) directly inside the control folder.
    Flat files with no sample structure -> invalid_format (never treated as
    one implicit sample). Empty/missing folder -> no_evidence."""
    control_id = control_folder.name

    if not control_folder.exists() or not control_folder.is_dir():
        return ControlEvidenceClassification(control_id=control_id, detected_mode="no_evidence")

    entries = [e for e in control_folder.iterdir() if not is_junk_path([e.name])]
    if not entries:
        return ControlEvidenceClassification(control_id=control_id, detected_mode="no_evidence")

    sample_dirs = sorted(
        (e for e in entries if e.is_dir() and SAMPLE_DIRNAME_RE.match(e.name)),
        key=lambda e: e.name.lower(),
    )
    if sample_dirs:
        sample_ids = [d.name for d in sample_dirs]
        file_count = sum(1 for d in sample_dirs for f in d.iterdir() if f.is_file() and not is_junk_path([f.name]))
        return ControlEvidenceClassification(
            control_id=control_id, detected_mode="multi_sample", sample_ids=sample_ids, file_count=file_count,
        )

    files = [e for e in entries if e.is_file()]
    sample_files = sorted((f for f in files if SAMPLE_FILENAME_RE.match(f.name)), key=lambda f: f.name.lower())
    if sample_files:
        sample_ids = [f.stem for f in sample_files]
        return ControlEvidenceClassification(
            control_id=control_id, detected_mode="multi_sample", sample_ids=sample_ids, file_count=len(sample_files),
        )

    non_junk_files = [e for e in entries if e.is_file()]
    if non_junk_files:
        return ControlEvidenceClassification(
            control_id=control_id, detected_mode="invalid_format", file_count=len(non_junk_files),
        )

    # Only non-sample subdirectories present — still no usable structure.
    return ControlEvidenceClassification(control_id=control_id, detected_mode="invalid_format")


def classify_evidence_root(evidence_root: Path, control_ids: list[str]) -> dict[str, ControlEvidenceClassification]:
    """Classifies every control's evidence folder under evidence_root. A
    control_id with no matching subfolder at all is no_evidence."""
    results: dict[str, ControlEvidenceClassification] = {}
    for control_id in control_ids:
        folder = evidence_root / control_id
        results[control_id] = detect_control_test_mode(folder)
    return results
