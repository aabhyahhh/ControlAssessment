import { apiFetch } from "./api";
import type { JustificationEmail, JustificationEmailItem, SendJustificationEmailRequest } from "../types";

export function listJustificationEmails(projectId: string) {
  return apiFetch<JustificationEmail[]>(`/projects/${projectId}/justification-emails`);
}

export function sendJustificationEmail(projectId: string, body: SendJustificationEmailRequest) {
  return apiFetch<JustificationEmail>(`/projects/${projectId}/justification-emails`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function uploadJustificationResponse(
  projectId: string,
  itemId: string,
  responseText: string,
  file: File | null,
) {
  const form = new FormData();
  if (responseText) form.set("response_text", responseText);
  if (file) form.set("file", file);
  return apiFetch<JustificationEmailItem>(`/projects/${projectId}/justification-emails/${itemId}/response`, {
    method: "POST",
    body: form,
  });
}

export function analyzeJustificationItem(projectId: string, itemId: string) {
  return apiFetch<JustificationEmailItem>(`/projects/${projectId}/justification-emails/${itemId}/analyze`, {
    method: "POST",
  });
}
