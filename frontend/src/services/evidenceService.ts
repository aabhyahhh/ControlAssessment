import { apiFetch } from "./api";
import type { DeclaredEvidence, DeclaredEvidenceItem } from "../types";

export function listDeclaredEvidence(projectId: string) {
  return apiFetch<DeclaredEvidence[]>(`/projects/${projectId}/evidence-list`);
}

export function upsertDeclaredEvidence(projectId: string, controlId: string, items: DeclaredEvidenceItem[]) {
  return apiFetch<DeclaredEvidence>(`/projects/${projectId}/evidence-list`, {
    method: "PUT",
    body: JSON.stringify({ control_id: controlId, items }),
  });
}
