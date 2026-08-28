import { apiFetch, getToken } from "./api";
import type { Artifact } from "../types";

export function listArtifacts(projectId: string) {
  return apiFetch<Artifact[]>(`/projects/${projectId}/artifacts`);
}

export function exportAttributes(projectId: string) {
  return apiFetch<Artifact>(`/projects/${projectId}/export-attributes`, { method: "POST" });
}

export function exportFinalReport(projectId: string) {
  return apiFetch<Artifact>(`/projects/${projectId}/export-final-report`, { method: "POST" });
}

export function exportPhase(projectId: string, phase: number) {
  return apiFetch<Artifact>(`/projects/${projectId}/export-phase/${phase}`, { method: "POST" });
}

export function exportRcm(projectId: string) {
  return apiFetch<Artifact>(`/projects/${projectId}/export-rcm`, { method: "POST" });
}

export interface OverrideResult {
  controls_updated: number;
  fields_updated: number;
  unknown_control_ids: string[];
  message: string;
}

export function overrideRcm(projectId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<OverrideResult>(`/projects/${projectId}/override-rcm`, { method: "POST", body: formData });
}

export function overrideAttributes(projectId: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<OverrideResult>(`/projects/${projectId}/override-attributes`, { method: "POST", body: formData });
}

/**
 * Downloads an artifact. Goes through fetch rather than a plain link because
 * the endpoint needs the bearer token; the blob is handed to a temporary
 * object URL so the browser saves it with the server-provided filename.
 */
export async function downloadArtifact(projectId: string, artifactId: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`/api/projects/${projectId}/artifacts/${artifactId}/download`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new Error(`Download failed (${res.status})`);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
