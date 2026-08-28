/**
 * The three-dot "agent is working" bubble. Shown in the agent's own bubble
 * position so the wait reads as the agent composing a reply, rather than the
 * UI having frozen.
 *
 * `label` names the actual work in progress ("Running evidence review…") when
 * we know it — a bare animation tells the user something is happening but not
 * what, and phase runs here can take a couple of minutes.
 */
interface TypingIndicatorProps {
  label?: string;
}

export default function TypingIndicator({ label }: TypingIndicatorProps) {
  return (
    <div className="chat-bubble-row agent">
      <div className="chat-bubble agent typing-bubble" role="status" aria-live="polite">
        <div className="chat-bubble-label">AGENT</div>
        <div className="typing-row">
          <span className="typing-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          {label && <span className="typing-label">{label}</span>}
          <span className="sr-only">{label ?? "The agent is working"}</span>
        </div>
      </div>
    </div>
  );
}
