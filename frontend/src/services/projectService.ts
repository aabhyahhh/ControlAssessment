import { apiFetch } from "./api";
import type { Framework, Project } from "../types";

export function listProjects() {
  return apiFetch<Project[]>("/projects");
}

export function createProject(input: {
  name: string;
  framework: Framework;
  audit_period_start: string;
  audit_period_end: string;
}) {
  return apiFetch<Project>("/projects", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function getProject(projectId: string) {
  return apiFetch<Project>(`/projects/${projectId}`);
}

/** Permanently deletes a project with all of its data and uploaded files.
 *  Irreversible — callers must confirm with the user first. */
export function deleteProject(projectId: string) {
  return apiFetch<void>(`/projects/${projectId}`, { method: "DELETE" });
}
