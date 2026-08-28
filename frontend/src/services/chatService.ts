import { apiFetch, getToken } from "./api";
import type { Artifact, ChatMessage, ControlAttributes } from "../types";

/** Stored transcript for a project, oldest first. */
export function listChatMessages(projectId: string) {
  return apiFetch<ChatMessage[]>(`/projects/${projectId}/chat`);
}

/**
 * Persists a locally-generated message (upload confirmations, phase
 * summaries) so it survives navigation. Fire-and-forget: a failure here
 * must never block the UI, it just costs that line on reload.
 */
export function appendChatMessage(projectId: string, role: "user" | "assistant", content: string) {
  return apiFetch<ChatMessage>(`/projects/${projectId}/chat/messages`, {
    method: "POST",
    body: JSON.stringify({ role, content }),
  });
}

export interface SSEEventHandlers {
  onToken?: (text: string) => void;
  onToolStart?: (data: { tool_name: string; args: unknown }) => void;
  onToolEnd?: (data: { tool_name: string; result: unknown; duration: number }) => void;
  onPhaseProgress?: (data: { phase: number; control_id: string; current: number; total: number }) => void;
  onResultsReady?: (data: { phase: number; result: unknown }) => void;
  onAttributesReady?: (data: { attributes: ControlAttributes[] }) => void;
  onArtifactReady?: (data: { artifact: Artifact }) => void;
  onAwaitingApproval?: (data: { phase: number }) => void;
  onDone?: () => void;
  onError?: (data: { message: string; correlation_id?: string }) => void;
}

/**
 * Sends a chat message, then opens an SSE stream to receive the agent's
 * response as a sequence of named events. Returns an abort function.
 */
export function sendChatMessage(
  projectId: string,
  message: string,
  handlers: SSEEventHandlers,
): () => void {
  const controller = new AbortController();

  (async () => {
    const token = getToken();
    const res = await fetch(`/api/projects/${projectId}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message }),
      signal: controller.signal,
    });

    if (!res.ok || !res.body) {
      handlers.onError?.({ message: `Request failed (${res.status})` });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sepIndex: number;
        while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
          const rawEvent = buffer.slice(0, sepIndex);
          buffer = buffer.slice(sepIndex + 2);
          if (!rawEvent.trim() || rawEvent.startsWith(":")) continue;

          let eventName = "message";
          let dataLine = "";
          for (const line of rawEvent.split("\n")) {
            if (line.startsWith("event:")) eventName = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
          }

          let data: unknown = null;
          try {
            data = dataLine ? JSON.parse(dataLine) : null;
          } catch {
            data = dataLine;
          }

          switch (eventName) {
            case "token":
              handlers.onToken?.((data as { text: string })?.text ?? "");
              break;
            case "tool_start":
              handlers.onToolStart?.(data as never);
              break;
            case "tool_end":
              handlers.onToolEnd?.(data as never);
              break;
            case "phase_progress":
              handlers.onPhaseProgress?.(data as never);
              break;
            case "results_ready":
              handlers.onResultsReady?.(data as never);
              break;
            case "attributes_ready":
              handlers.onAttributesReady?.(data as never);
              break;
            case "artifact_ready":
              handlers.onArtifactReady?.(data as never);
              break;
            case "awaiting_approval":
              handlers.onAwaitingApproval?.(data as never);
              break;
            case "done":
              handlers.onDone?.();
              break;
            case "error":
              handlers.onError?.(data as never);
              break;
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        handlers.onError?.({ message: "Connection lost" });
      }
    }
  })();

  return () => controller.abort();
}
