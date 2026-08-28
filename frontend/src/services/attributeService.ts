import { apiFetch } from "./api";
import type { ControlAttributes } from "../types";

// NOTE: the preview/approve endpoints use /attributes-preview and
// /attributes-approve (hyphen, not slash) so they can't be shadowed by the
// /attributes/{control_id} routes on the backend.
export function previewAttributes(projectId: string) {
  return apiFetch<ControlAttributes[]>(`/projects/${projectId}/attributes-preview`, { method: "POST" });
}

export function approveAttributes(projectId: string) {
  return apiFetch<ControlAttributes[]>(`/projects/${projectId}/attributes-approve`, { method: "POST" });
}

export function listAttributes(projectId: string) {
  return apiFetch<ControlAttributes[]>(`/projects/${projectId}/attributes`);
}

export interface StageProgress {
  done: number;
  total: number;
  label: string | null;
}

/** Progress of any long-running phase. A stage that is absent means "no
 *  information available" — never "finished" (see engines/progress.py). */
export function getPhaseProgress(projectId: string) {
  return apiFetch<{ stages: Record<string, StageProgress> }>(
    `/projects/${projectId}/phase-progress`,
  );
}

export function modifyAttribute(
  projectId: string,
  controlId: string,
  attributeNo: number,
  body: { name?: string; description?: string },
) {
  return apiFetch<ControlAttributes>(
    `/projects/${projectId}/attributes/${encodeURIComponent(controlId)}/${attributeNo}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export function addAttribute(
  projectId: string,
  controlId: string,
  body: { name: string; description: string; position?: number },
) {
  return apiFetch<ControlAttributes>(`/projects/${projectId}/attributes/${encodeURIComponent(controlId)}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function removeAttribute(projectId: string, controlId: string, attributeNo: number) {
  return apiFetch<ControlAttributes>(
    `/projects/${projectId}/attributes/${encodeURIComponent(controlId)}/${attributeNo}`,
    { method: "DELETE" },
  );
}
