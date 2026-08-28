import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";
import type { ChatMessage } from "../types";

interface ChatBubbleProps {
  message: ChatMessage;
}

/**
 * Renders `**bold**` spans inline. The agent's mandatory closing line uses
 * `**Next:**`, which would otherwise show raw asterisks to the user — and
 * a full markdown library is overkill for the handful of emphasis marks the
 * agent actually emits.
 */
function renderInline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      part
    ),
  );
}

/** Wall-clock time for the message. Time only, not the date: an engagement's
 *  transcript is read within a session, and a full date on every bubble is
 *  noise. Falls back to nothing if the stamp is missing or unparseable
 *  rather than rendering "Invalid Date". */
function formatStamp(iso: string | undefined): string {
  if (!iso) return "";
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  return t.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export default function ChatBubble({ message }: ChatBubbleProps) {
  const isUser = message.role === "user";
  const isTool = message.role === "tool";
  // Errors are marked with a leading "[error] " token rather than an emoji:
  // the glyph rendered in each platform's own cartoon style, which is wrong
  // for an audit tool. The token is stripped here and shown as a line icon.
  const isError = message.content.startsWith("[error] ");
  const body = isError ? message.content.slice("[error] ".length) : message.content;
  const lines = body.split("\n");
  const stamp = formatStamp(message.createdAt);

  return (
    <div className={`chat-bubble-row ${isUser ? "user" : "agent"}`}>
      <div
        className={`chat-bubble ${isUser ? "user" : "agent"}${isTool ? " tool" : ""}${isError ? " error" : ""}`}
      >
        {!isUser && (
          <div className="chat-bubble-label">
            <span>{isTool ? "TOOL" : "AGENT"}</span>
            {stamp && <time className="chat-bubble-time">{stamp}</time>}
          </div>
        )}
        <div className="chat-bubble-content">
          {isError && (
            <AlertTriangle size={15} strokeWidth={2} className="chat-bubble-error-icon" aria-label="Error" />
          )}
          {lines.map((line, i) => {
            if (!line.trim()) return <div key={i} className="chat-bubble-gap" />;
            const isNext = line.trimStart().startsWith("**Next:**");
            return (
              <p key={i} className={isNext ? "chat-next-line" : undefined}>
                {renderInline(line)}
              </p>
            );
          })}
        </div>
        {/* User bubbles have no label row to carry the stamp, so it goes
            under the content instead. */}
        {isUser && stamp && <time className="chat-bubble-time user">{stamp}</time>}
      </div>
    </div>
  );
}
