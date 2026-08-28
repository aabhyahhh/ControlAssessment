import { useHoverCard } from "./HoverCard";
import type { TimelineSufficiencyRow } from "../types";

/**
 * Evidence coverage drawn as an actual timeline: one track per control, with
 * the audit period as the full width and the control's evidence span painted
 * onto it. A table of dates made the reader reconstruct the picture in their
 * head — the whole question here ("is the evidence spread across the
 * period?") is inherently spatial.
 *
 * Controls with no dated evidence get an explicit empty track rather than
 * being dropped, so a gap can't be mistaken for a control that wasn't
 * assessed.
 */
interface TimelineChartProps {
  rows: TimelineSufficiencyRow[];
  /** Audit period bounds (ISO). Falls back to the evidence range when absent. */
  periodStart?: string | null;
  periodEnd?: string | null;
}

const TONE: Record<string, { fill: string; ink: string; label: string }> = {
  sufficient: { fill: "var(--pastel-green)", ink: "var(--pastel-green-ink)", label: "Sufficient" },
  insufficient: { fill: "var(--pastel-red)", ink: "var(--pastel-red-ink)", label: "Insufficient" },
  undetermined: { fill: "var(--pastel-amber)", ink: "var(--pastel-amber-ink)", label: "Undetermined" },
};

const toTime = (d?: string | null): number | null => {
  if (!d) return null;
  const t = new Date(d).getTime();
  return Number.isNaN(t) ? null : t;
};

const fmt = (t: number) =>
  new Date(t).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

export default function TimelineChart({ rows, periodStart, periodEnd }: TimelineChartProps) {
  const { show, move, hide, card } = useHoverCard();

  // Establish the axis. Prefer the declared audit period; otherwise span the
  // widest evidence range present so the tracks still mean something.
  const evidenceTimes = rows.flatMap((r) =>
    [toTime(r.earliest_evidence_date), toTime(r.latest_evidence_date)].filter(
      (t): t is number => t !== null,
    ),
  );
  const start = toTime(periodStart) ?? (evidenceTimes.length ? Math.min(...evidenceTimes) : null);
  const end = toTime(periodEnd) ?? (evidenceTimes.length ? Math.max(...evidenceTimes) : null);

  // A zero-width axis would make every span NaN% — bail out to a readable
  // message instead of rendering a broken chart.
  if (start === null || end === null || end <= start) {
    return (
      <p className="timeline-empty">
        No dated evidence was found, so coverage across the audit period can't be charted.
      </p>
    );
  }

  const span = end - start;
  const pct = (t: number) => ((t - start) / span) * 100;

  // Quarter gridlines give the eye something to measure against.
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    left: f * 100,
    label: fmt(start + f * span),
  }));

  return (
    <div className="timeline-chart">
      <div className="timeline-axis">
        {ticks.map((t, i) => (
          <span
            key={i}
            className="timeline-axis-tick"
            style={{ left: `${t.left}%` }}
            /* First and last labels would overflow the container if centred. */
            data-align={i === 0 ? "start" : i === ticks.length - 1 ? "end" : "mid"}
          >
            {t.label}
          </span>
        ))}
      </div>

      <div className="timeline-rows">
        {rows.map((r) => {
          const tone = TONE[r.status] ?? TONE.undetermined;
          const from = toTime(r.earliest_evidence_date);
          const to = toTime(r.latest_evidence_date);
          const hasSpan = from !== null && to !== null;

          // Clamp to the axis: evidence dated outside the declared period is
          // real and must still be drawn, just not off the edge of the chart.
          const left = hasSpan ? Math.max(0, Math.min(100, pct(from))) : 0;
          const right = hasSpan ? Math.max(0, Math.min(100, pct(to))) : 0;
          const width = hasSpan ? Math.max(right - left, 1.2) : 0;

          const coverage = Math.round((r.coverage_pct ?? 0) * 100);

          return (
            <div
              key={r.control_id}
              className="timeline-row"
              onMouseEnter={(e) =>
                show(e, {
                  title: r.control_id,
                  value: tone.label,
                  sub: hasSpan ? `${fmt(from)} → ${fmt(to)}` : "No dated evidence",
                  items: [
                    r.expected_instances != null
                      ? `${r.evidence_instances_found} of ${r.expected_instances} expected instances (${coverage}% coverage)`
                      : `${r.evidence_instances_found} evidence instance(s) found`,
                    ...(r.flags.length ? r.flags : ["No flags raised"]),
                  ],
                  color: tone.ink,
                })
              }
              onMouseMove={move}
              onMouseLeave={hide}
            >
              <span className="timeline-row-label">{r.control_id}</span>
              <div className="timeline-track">
                {ticks.map((t, i) => (
                  <span key={i} className="timeline-gridline" style={{ left: `${t.left}%` }} />
                ))}
                {hasSpan ? (
                  <div
                    className="timeline-span"
                    style={{
                      left: `${left}%`,
                      width: `${width}%`,
                      background: tone.fill,
                      borderColor: tone.ink,
                    }}
                  >
                    <span className="timeline-span-cap" style={{ background: tone.ink }} />
                    <span
                      className="timeline-span-cap end"
                      style={{ background: tone.ink }}
                    />
                  </div>
                ) : (
                  <span className="timeline-no-evidence">no dated evidence</span>
                )}
              </div>
              <span className="timeline-row-status" style={{ color: tone.ink }}>
                {coverage}%
              </span>
            </div>
          );
        })}
      </div>

      <div className="timeline-legend">
        {Object.entries(TONE).map(([key, t]) => (
          <span key={key} className="timeline-legend-item">
            <span className="timeline-legend-swatch" style={{ background: t.fill, borderColor: t.ink }} />
            {t.label}
          </span>
        ))}
      </div>
      {card}
    </div>
  );
}
