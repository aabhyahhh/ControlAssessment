/**
 * Closing note under a step pane's last section, reminding the reader that
 * every figure above is live-computed rather than fixed markup. Purely
 * informational — never a place to state a data-specific claim (that
 * belongs in the pane's own TypedSummary/analytics), so its copy is a
 * static disclaimer, not a rendering of project state.
 */
export default function StepFooterNote({ text }: { text: string }) {
  return <p className="step-footer-note">{text}</p>;
}
