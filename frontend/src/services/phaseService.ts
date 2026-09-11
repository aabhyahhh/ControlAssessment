import { apiFetch } from "./api";
import type { Phase1Result, Phase2Result, Phase3Result, Phase4Result, PhaseResult, RunAllResult } from "../types";

export function runRcmIntake(projectId: string) {
  return apiFetch<PhaseResult<Phase1Result>>(`/projects/${projectId}/phases/1/run`, { method: "POST" });
}

export function runAdequacyAssessment(projectId: string) {
  return apiFetch<PhaseResult<Phase2Result>>(`/projects/${projectId}/phases/2/run`, { method: "POST" });
}

export function runEvidenceAssessment(projectId: string) {
  return apiFetch<PhaseResult<Phase3Result>>(`/projects/${projectId}/phases/3/run`, { method: "POST" });
}

export function runGapAssessment(projectId: string) {
  return apiFetch<PhaseResult<Phase4Result>>(`/projects/${projectId}/phases/4/run`, { method: "POST" });
}

export function runAllRemainingPhases(projectId: string) {
  return apiFetch<RunAllResult>(`/projects/${projectId}/phases-run-all`, { method: "POST" });
}

export function getPhaseResult<T = Record<string, unknown>>(projectId: string, phase: number) {
  return apiFetch<PhaseResult<T>>(`/projects/${projectId}/phases/${phase}`);
}

export interface StageProgress {
  done: number;
  total: number;
  label: string | null;
}

/** Progress of any long-running step. A stage that is absent means "no
 *  information available" — never "finished" (see engines/progress.py). */
export function getPhaseProgress(projectId: string) {
  return apiFetch<{ stages: Record<string, StageProgress> }>(`/projects/${projectId}/phase-progress`);
}
