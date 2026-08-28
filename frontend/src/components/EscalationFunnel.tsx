interface FunnelStage {
  label: string;
  count: number;
  tone: "blue" | "amber" | "red";
}

interface EscalationFunnelProps {
  stages: FunnelStage[];
  /** Denominator for every bar, so widths are comparable across stages. */
  total: number;
  caption?: string;
}

const TONE_FILL: Record<FunnelStage["tone"], string> = {
  blue: "linear-gradient(90deg, var(--blue-2), var(--blue-3))",
  amber: "linear-gradient(90deg, var(--pastel-amber-ink), #d9a441)",
  red: "linear-gradient(90deg, var(--pastel-red-ink), #e05252)",
};

/**
 * How a control population narrows to the few that block sign-off.
 *
 * Every bar is drawn against the SAME denominator (the full population) so the
 * narrowing is legible as shape. Scaling each bar to its own stage would make
 * a 4-of-12 tier look as wide as the 12 — which is the opposite of the point.
 */
export default function EscalationFunnel({ stages, total, caption }: EscalationFunnelProps) {
  if (!stages.length || total <= 0) return null;

  return (
    <div className="escalation-funnel">
      <h4 className="funnel-title">Escalation funnel</h4>
      {caption && <p className="funnel-caption">{caption}</p>}
      <div className="funnel-stages">
        {stages.map((s) => (
          <div key={s.label} className="funnel-stage">
            <div className="funnel-stage-head">
              <span className="funnel-stage-label">{s.label}</span>
              <span className="funnel-stage-count">{s.count}</span>
            </div>
            <div className="funnel-track">
              <div
                className="funnel-fill"
                style={{
                  width: `${Math.max((s.count / total) * 100, s.count > 0 ? 4 : 0)}%`,
                  background: TONE_FILL[s.tone],
                }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
