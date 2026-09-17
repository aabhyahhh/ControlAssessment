import { useHoverCard } from "./HoverCard";

export interface FunnelStage {
  label: string;
  count: number;
  /** Controls excluded from this stage because they could not be assessed
   *  (missing data), kept apart from controls that were assessed and
   *  genuinely didn't pass. Rendered as a distinct neutral segment, never
   *  folded into the counted total. */
  unassessed?: number;
  /** Extra hover-card lines, e.g. the control IDs that dropped out here. */
  detail?: string[];
}

interface EscalationFunnelProps {
  title: string;
  stages: FunnelStage[];
  /** Denominator for every bar, so widths are comparable across stages. */
  total: number;
  caption?: string;
}

/**
 * A real population narrowing across gates, drawn as bars against one shared
 * denominator (the starting population) so the narrowing reads as shape —
 * scaling each bar to its own stage would make a 4-of-12 tier look as wide
 * as the 12, which is the opposite of the point.
 *
 * Only use this where every stage is a genuine strict subset of the one
 * before it (the caller is responsible for that invariant — this component
 * has no way to verify it). A stage's `unassessed` slice renders separately
 * in neutral grey so "excluded because we don't know" is never visually
 * indistinguishable from "assessed and didn't qualify".
 */
export default function EscalationFunnel({ title, stages, total, caption }: EscalationFunnelProps) {
  const { show, move, hide, card } = useHoverCard();
  if (!stages.length || total <= 0) return null;

  return (
    <div className="escalation-funnel">
      <h4 className="funnel-title">{title}</h4>
      {caption && <p className="funnel-caption">{caption}</p>}
      <div className="funnel-stages">
        {stages.map((s) => {
          const unassessed = s.unassessed ?? 0;
          return (
            <div key={s.label} className="funnel-stage">
              <div className="funnel-stage-head">
                <span className="funnel-stage-label">{s.label}</span>
                <span className="funnel-stage-count">
                  {s.count}
                  {unassessed > 0 && <span className="funnel-stage-unassessed"> (+{unassessed} not assessed)</span>}
                </span>
              </div>
              <div
                className="funnel-track"
                onMouseEnter={(e) =>
                  show(e, {
                    title: s.label,
                    value: `${s.count} of ${total}`,
                    sub: unassessed > 0 ? `${unassessed} control(s) could not be assessed at this gate` : undefined,
                    items: s.detail,
                    color: "var(--pastel-blue-ink)",
                  })
                }
                onMouseMove={move}
                onMouseLeave={hide}
              >
                <div
                  className="funnel-fill"
                  style={{ width: `${Math.max((s.count / total) * 100, s.count > 0 ? 4 : 0)}%` }}
                />
                {unassessed > 0 && (
                  <div
                    className="funnel-fill-unassessed"
                    style={{
                      left: `${(s.count / total) * 100}%`,
                      width: `${Math.max((unassessed / total) * 100, 2)}%`,
                    }}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
      {card}
    </div>
  );
}
