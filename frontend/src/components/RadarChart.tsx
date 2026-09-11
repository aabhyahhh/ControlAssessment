import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";

export interface RadarAxis {
  key: string;
  label: string;
  /** 0-1. */
  value: number;
  /** Raw value shown in the chip and hover card (e.g. "3.4"). */
  display: string;
  /** True when this dimension is one of the weak ones. */
  weak?: boolean;
  /** Extra hover-card lines. */
  detail?: string[];
}

interface RadarChartProps {
  axes: RadarAxis[];
  size?: number;
  /** Rings drawn behind the shape. */
  rings?: number;
  /** Word shown in the hover card's "sub" line, e.g. "of controls supported"
   *  — the axis's own `display` (e.g. "6/9") already carries the ratio, so
   *  this only needs to name what's being measured. */
  unitLabel?: string;
  /** Text shown for a flagged axis; the caller decides what "weak" means
   *  for its own data (contradicted, ineffective, etc). */
  weakLabel?: string;
  okLabel?: string;
}

/**
 * Portfolio profile across N dimensions.
 *
 * Drawn as a polygon over concentric rings rather than a bar set because the
 * question this answers is about SHAPE — where the profile caves in — and a
 * dented polygon shows that at a glance where twelve bars do not.
 *
 * The polygon grows from the centre on mount, and each vertex lifts under the
 * cursor so an individual dimension can be read without a legend.
 */
export default function RadarChart({
  axes,
  size = 300,
  rings = 4,
  unitLabel,
  weakLabel = "Flagged",
  okLabel = "Within tolerance",
}: RadarChartProps) {
  const { show, move, hide, card } = useHoverCard();
  const [hovered, setHovered] = useState<string | null>(null);
  const [grow, setGrow] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const duration = 850;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setGrow(1 - Math.pow(1 - t, 3)); // easeOutCubic
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [axes]);

  const cx = size / 2;
  const cy = size / 2;
  // Leave room for the labels that sit outside the outermost ring.
  const radius = size / 2 - 34;
  const n = axes.length;

  // Start at 12 o'clock and go clockwise.
  const angleFor = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pointAt = (i: number, r: number) => {
    const a = angleFor(i);
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r] as const;
  };

  const ringPolygon = (frac: number) =>
    axes.map((_, i) => pointAt(i, radius * frac).join(",")).join(" ");

  const shapePoints = axes
    .map((ax, i) => pointAt(i, radius * Math.max(0.04, ax.value) * grow).join(","))
    .join(" ");

  return (
    <div className="radar-chart chart-animate-in">
      {/* No width/height attributes: the viewBox plus the CSS below let the
          chart scale down with its container. A fixed 300px width clipped
          the radar as soon as the data pane was dragged narrower than that. */}
      <svg viewBox={`0 0 ${size} ${size}`} role="img" preserveAspectRatio="xMidYMid meet">
        <defs>
          <linearGradient id="radar-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--radar-accent)" stopOpacity="0.55" />
            <stop offset="100%" stopColor="var(--radar-accent)" stopOpacity="0.18" />
          </linearGradient>
        </defs>

        {/* Rings: the scale the polygon is read against. */}
        {Array.from({ length: rings }, (_, r) => (
          <polygon
            key={r}
            points={ringPolygon((r + 1) / rings)}
            className="radar-ring"
          />
        ))}

        {/* Spokes */}
        {axes.map((ax, i) => {
          const [x, y] = pointAt(i, radius);
          return <line key={ax.key} x1={cx} y1={cy} x2={x} y2={y} className="radar-spoke" />;
        })}

        <polygon points={shapePoints} className="radar-shape" />

        {/* Vertices last, so they sit above the fill and stay hittable. */}
        {axes.map((ax, i) => {
          const [x, y] = pointAt(i, radius * Math.max(0.04, ax.value) * grow);
          const isHot = hovered === ax.key;
          return (
            <circle
              key={ax.key}
              cx={x}
              cy={y}
              r={isHot ? 6.5 : 4}
              className={`radar-vertex${ax.weak ? " weak" : ""}`}
              onMouseEnter={(e) => {
                setHovered(ax.key);
                show(e, {
                  title: ax.label,
                  value: unitLabel ? `${ax.display} ${unitLabel}` : ax.display,
                  sub: ax.weak ? weakLabel : okLabel,
                  items: ax.detail,
                  color: ax.weak ? "var(--pastel-red-ink)" : "var(--pastel-green-ink)",
                });
              }}
              onMouseMove={move}
              onMouseLeave={() => {
                setHovered(null);
                hide();
              }}
            />
          );
        })}

        {/* Axis labels, pushed just outside the outer ring. */}
        {axes.map((ax, i) => {
          const [x, y] = pointAt(i, radius + 18);
          const a = angleFor(i);
          const anchor = Math.abs(Math.cos(a)) < 0.3 ? "middle" : Math.cos(a) > 0 ? "start" : "end";
          return (
            <text
              key={ax.key}
              x={x}
              y={y}
              textAnchor={anchor}
              dominantBaseline="middle"
              className={`radar-label${hovered === ax.key ? " hot" : ""}`}
            >
              {ax.label}
            </text>
          );
        })}
      </svg>
      {card}
    </div>
  );
}
