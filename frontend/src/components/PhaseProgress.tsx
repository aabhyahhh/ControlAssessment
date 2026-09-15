interface PhaseProgressProps {
  /** What is running, e.g. "Assessing design adequacy". */
  title: string;
  /** Items finished so far, and the total. */
  done: number;
  total: number;
  /** The item that just completed — a Control ID or filename. */
  label?: string | null;
  /** What's actually happening right now to that item — "Extracting text",
   *  "Reconciling against SOP", "Waiting for model response" — so the bar
   *  reads as a real account of backend work, not a bare N-of-M count. */
  activity?: string | null;
  /** Unit for the "N of M ___" line — "controls" or "files". */
  unit?: string;
}

/**
 * Percentage-of-completion bar for a long-running phase.
 *
 * Shown while document upload/extraction, adequacy assessment, or evidence
 * checklist generation is in flight — each can involve text extraction
 * and/or several LLM round-trips per item and run for minutes, which is far
 * too long to show a static "working…".
 *
 * `total === 0` renders an indeterminate bar rather than a misleading 0%:
 * before the first poll lands we know work is happening but not how much.
 */
export default function PhaseProgress({ title, done, total, label, activity, unit = "controls" }: PhaseProgressProps) {
  const known = total > 0;
  const pct = known ? Math.round((done / total) * 100) : 0;

  return (
    <div className="phase-progress" role="status" aria-live="polite">
      <div className="phase-progress-head">
        <span className="phase-progress-title">{title}</span>
        {known && <span className="phase-progress-pct">{pct}%</span>}
      </div>
      <div
        className="phase-progress-track"
        role="progressbar"
        aria-valuenow={known ? pct : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={title}
      >
        <div
          className={`phase-progress-fill${known ? "" : " indeterminate"}`}
          style={known ? { width: `${pct}%` } : undefined}
        />
      </div>
      {activity && <div className="phase-progress-activity">{activity}…</div>}
      <div className="phase-progress-foot">
        {known ? (
          <span>
            {done} of {total} {unit}
          </span>
        ) : (
          <span>Starting…</span>
        )}
        {label && !activity && <span className="phase-progress-label">Last completed: {label}</span>}
      </div>
    </div>
  );
}
