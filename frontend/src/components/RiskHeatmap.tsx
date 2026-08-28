import { Fragment } from "react";
import { useHoverCard } from "./HoverCard";

interface HeatmapCell {
  likelihood: string;
  impact: string;
  count: number;
  control_ids: string[];
}

interface RiskHeatmapProps {
  axes: { likelihood: string[]; impact: string[] };
  cells: HeatmapCell[];
  onCellClick?: (cell: HeatmapCell) => void;
}

const BAND_INDEX: Record<string, number> = { Low: 0, Medium: 1, High: 2 };

/** Pastel fill + saturated ink per severity, matching the ControlIris family. */
function severity(likelihoodIdx: number, impactIdx: number) {
  const score = likelihoodIdx + impactIdx; // 0-4
  if (score <= 1) return { bg: "var(--pastel-green)", ink: "var(--pastel-green-ink)", label: "Low risk" };
  if (score <= 2) return { bg: "var(--pastel-amber)", ink: "var(--pastel-amber-ink)", label: "Moderate risk" };
  if (score <= 3) return { bg: "#fee9d6", ink: "#c2410c", label: "Elevated risk" };
  return { bg: "var(--pastel-red)", ink: "var(--pastel-red-ink)", label: "High risk" };
}

export default function RiskHeatmap({ axes, cells, onCellClick }: RiskHeatmapProps) {
  const cellMap = new Map(cells.map((c) => [`${c.likelihood}|${c.impact}`, c]));
  // Impact runs high-to-low down the rows so the grid reads like a
  // conventional risk matrix (worst case top-right).
  const impactRows = [...axes.impact].reverse();
  const { show, move, hide, card } = useHoverCard();

  return (
    <div className="risk-heatmap chart-animate-in">
      <div className="risk-heatmap-grid" style={{ gridTemplateColumns: `74px repeat(${axes.likelihood.length}, 1fr)` }}>
        <div className="risk-heatmap-corner" />
        {axes.likelihood.map((l) => (
          <div key={l} className="risk-heatmap-axis-label risk-heatmap-axis-label-top">
            {l}
          </div>
        ))}
        {impactRows.map((impact, rowIdx) => (
          <Fragment key={`row-${impact}`}>
            <div className="risk-heatmap-axis-label risk-heatmap-axis-label-left">{impact}</div>
            {axes.likelihood.map((likelihood, colIdx) => {
              const cell = cellMap.get(`${likelihood}|${impact}`);
              const count = cell?.count ?? 0;
              const li = BAND_INDEX[likelihood] ?? 1;
              const ii = BAND_INDEX[impact] ?? 1;
              const sev = severity(li, ii);
              const interactive = !!cell && count > 0;
              return (
                <button
                  key={`${likelihood}-${impact}`}
                  type="button"
                  className={`risk-heatmap-cell${interactive ? " interactive" : ""}`}
                  style={{
                    background: sev.bg,
                    color: sev.ink,
                    // Cascade in cell by cell rather than all at once.
                    animationDelay: `${(rowIdx * axes.likelihood.length + colIdx) * 45}ms`,
                  }}
                  disabled={!interactive}
                  onClick={() => cell && onCellClick?.(cell)}
                  onMouseEnter={(e) =>
                    show(e, {
                      title: `${likelihood} likelihood · ${impact} impact`,
                      value: `${count} control${count === 1 ? "" : "s"}`,
                      sub: sev.label,
                      items: cell?.control_ids,
                      color: sev.ink,
                    })
                  }
                  onMouseMove={move}
                  onMouseLeave={hide}
                >
                  {count}
                </button>
              );
            })}
          </Fragment>
        ))}
      </div>
      <div className="risk-heatmap-axes-caption">
        <span>Likelihood →</span>
        <span>Impact ↑</span>
      </div>
      {card}
    </div>
  );
}
