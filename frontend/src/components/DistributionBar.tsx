import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";

export interface DistributionSegment {
  key: string;
  label: string;
  count: number;
  color: string;
  /** Extra hover-card lines, e.g. the control IDs in this segment. */
  detail?: string[];
  /** Control IDs shown inline in the legend row (not just on hover) — a
   *  reviewer scanning the legend can see exactly which controls sit in a
   *  segment without hovering the bar. Truncated with "+N" when there are
   *  more than a few; pass the full list, truncation happens here. */
  idsPreview?: string[];
}

interface DistributionBarProps {
  segments: DistributionSegment[];
  /** Currently filtered segment, if any. */
  activeKey?: string | null;
  onSelect?: (key: string | null) => void;
}

/**
 * One horizontal stacked bar showing how a control population splits across
 * a fixed set of categories (severity, gap type, …) — proportions at a
 * glance, with each segment clickable to filter the list below it. Used in
 * place of a pie/donut: a stacked bar reads relative size more accurately
 * and supports the click-filter directly on the segment being read.
 */
export default function DistributionBar({ segments, activeKey, onSelect }: DistributionBarProps) {
  const { show, move, hide, card } = useHoverCard();
  const [grow, setGrow] = useState(0);
  const total = segments.reduce((sum, s) => sum + s.count, 0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [segments]);

  if (total === 0) return null;

  return (
    <div className="distribution-bar">
      <div className="distribution-bar-track" role="group" aria-label="Distribution across categories — click a segment to filter">
        {segments
          .filter((s) => s.count > 0)
          .map((s) => (
            <button
              type="button"
              key={s.key}
              className={`distribution-bar-segment${activeKey === s.key ? " active" : ""}${activeKey != null && activeKey !== s.key ? " dimmed" : ""}`}
              style={{ width: `${(s.count / total) * grow * 100}%`, background: s.color }}
              aria-pressed={activeKey === s.key}
              onClick={() => onSelect?.(activeKey === s.key ? null : s.key)}
              onMouseEnter={(e) =>
                show(e, {
                  title: s.label,
                  value: `${s.count} of ${total}`,
                  sub: `${Math.round((s.count / total) * 100)}% of the assessed population`,
                  items: s.detail,
                  color: s.color,
                })
              }
              onMouseMove={move}
              onMouseLeave={hide}
            />
          ))}
      </div>
      <div className="distribution-bar-legend">
        {segments.map((s) => {
          const ids = s.idsPreview ?? [];
          const shown = ids.slice(0, 3);
          const extra = ids.length - shown.length;
          return (
            <button
              type="button"
              key={s.key}
              className={`distribution-legend-item${activeKey === s.key ? " active" : ""}`}
              onClick={() => onSelect?.(activeKey === s.key ? null : s.key)}
            >
              <span className="distribution-legend-swatch" style={{ background: s.color }} />
              <span className="distribution-legend-label">
                {s.label} <strong>{s.count}</strong>
              </span>
              {ids.length > 0 && (
                <span className="distribution-legend-ids">
                  {shown.join(" ")}
                  {extra > 0 && ` +${extra}`}
                </span>
              )}
              {ids.length === 0 && s.idsPreview !== undefined && (
                <span className="distribution-legend-ids">—</span>
              )}
            </button>
          );
        })}
      </div>
      {card}
    </div>
  );
}
