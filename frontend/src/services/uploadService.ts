import { apiFetch } from "./api";
import type { Control, EvidenceUploadResult, RcmUploadResult, SopUploadResult } from "../types";

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

export function uploadSop(projectId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<SopUploadResult>(`/projects/${projectId}/upload-sop`, {
    method: "POST",
    body: formData,
  });
}
