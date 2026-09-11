import { apiFetch } from "./api";
import type { AdequacyUploadResult, Control, EvidenceUploadResult, RcmUploadResult } from "../types";

export function uploadRcm(projectId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<RcmUploadResult>(`/projects/${projectId}/upload`, {
    method: "POST",
    body: formData,
  });
}

export function listControls(projectId: string) {
  return apiFetch<Control[]>(`/projects/${projectId}/controls`);
}

/**
 * fileList must carry webkitRelativePath (i.e. selected via a
 * webkitdirectory input) so each file's folder position can be recovered
 * server-side for control-ID / sample-ID matching.
 */
export function uploadEvidenceFolder(projectId: string, fileList: FileList | File[]) {
  const files = Array.from(fileList);
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
    const relPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    formData.append("relative_paths", relPath);
  }
  return apiFetch<EvidenceUploadResult>(`/projects/${projectId}/upload-folder`, {
    method: "POST",
    body: formData,
  });
}

/** One folder, one subfolder per Control ID, SOPs + monthly workpapers
 *  inside. A file directly under the root is a whole-process SOP. */
export function uploadAdequacyFolder(projectId: string, fileList: FileList | File[]) {
  const files = Array.from(fileList);
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
    const relPath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
    formData.append("relative_paths", relPath);
  }
  return apiFetch<AdequacyUploadResult>(`/projects/${projectId}/upload-adequacy-folder`, {
    method: "POST",
    body: formData,
  });
}

/** A single SOP or workpaper. Omit controlId for a whole-process SOP. */
export function uploadAdequacyFile(
  projectId: string,
  file: File,
  opts?: { controlId?: string; docKind?: "sop" | "workpaper" },
) {
  const formData = new FormData();
  formData.append("file", file);
  if (opts?.controlId) formData.append("control_id", opts.controlId);
  if (opts?.docKind) formData.append("doc_kind", opts.docKind);
  return apiFetch<AdequacyUploadResult>(`/projects/${projectId}/upload-adequacy-file`, {
    method: "POST",
    body: formData,
  });
}
