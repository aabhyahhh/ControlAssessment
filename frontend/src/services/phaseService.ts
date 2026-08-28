import { apiFetch } from "./api";
import type { Phase1Result, Phase2Result, Phase3Result, Phase4Result, PhaseResult, RunAllResult } from "../types";

export function runRiskPrioritization(projectId: string) {
  return apiFetch<PhaseResult<Phase1Result>>(`/projects/${projectId}/phases/1/run`, { method: "POST" });
}

export function setRiskWeighting(
  projectId: string,
  body: { use_default: boolean; score_map?: Record<string, number>; bands?: { threshold: number; label: string }[] },
) {
  return apiFetch<PhaseResult<Phase1Result>>(`/projects/${projectId}/phases/1/weighting`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function approveRiskInferences(projectId: string) {
  return apiFetch<PhaseResult<Phase1Result>>(`/projects/${projectId}/phases/1/approve`, { method: "POST" });
}

export function runEvidenceGapAnalysis(projectId: string) {
  return apiFetch<PhaseResult<Phase2Result>>(`/projects/${projectId}/phases/2/run`, { method: "POST" });
}

export function runAdequacyAssessment(projectId: string) {
  return apiFetch<PhaseResult<Phase3Result>>(`/projects/${projectId}/phases/3/run`, { method: "POST" });
}

export function runControlTesting(projectId: string) {
  return apiFetch<PhaseResult<Phase4Result>>(`/projects/${projectId}/phases/4/run`, { method: "POST" });
}

export function runAllRemainingPhases(projectId: string) {
  return apiFetch<RunAllResult>(`/projects/${projectId}/phases-run-all`, { method: "POST" });
}

export function getPhaseResult<T = Record<string, unknown>>(projectId: string, phase: number) {
  return apiFetch<PhaseResult<T>>(`/projects/${projectId}/phases/${phase}`);
}
