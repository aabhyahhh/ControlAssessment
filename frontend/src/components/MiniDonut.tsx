import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";

interface DonutSegment {
  label: string;
  value: number;
  /** Pastel fill. */
  color: string;
  /** Saturated tone for the legend text/border; falls back to `color`. */
  ink?: string;
  /** Optional detail lines for the hover card. */
  items?: string[];
}

interface MiniDonutProps {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
}

export default function MiniDonut({ segments, size = 132, thickness = 18, centerLabel }: MiniDonutProps) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const { show, move, hide, card } = useHoverCard();
  const [hovered, setHovered] = useState<string | null>(null);

  // Draw the ring on mount: start every arc at zero length, then flip to the
  // real value on the next frame so the CSS transition animates the sweep.
  const [drawn, setDrawn] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setDrawn(true));
    return () => cancelAnimationFrame(id);
  }, []);

  let offsetAccum = 0;
  const arcs = segments.map((s) => {
    const fraction = total > 0 ? s.value / total : 0;
    const arcLength = circumference * fraction;
    const isHovered = hovered === s.label;
    const arc = (
      <circle
        key={s.label}
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={s.color}
        strokeWidth={isHovered ? thickness + 4 : thickness}
        strokeDasharray={`${drawn ? arcLength : 0} ${circumference}`}
        strokeDashoffset={-offsetAccum}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{
          transition: "stroke-dasharray 900ms var(--ease-out-soft), stroke-width 160ms ease",
          cursor: "pointer",
        }}
        onMouseEnter={(e) => {
          setHovered(s.label);
          show(e, {
            title: s.label,
            value: `${s.value}`,
            sub: total > 0 ? `${Math.round((s.value / total) * 100)}% of ${total}` : undefined,
            items: s.items,
            color: s.ink ?? s.color,
          });
        }}
        onMouseMove={move}
        onMouseLeave={() => {
          setHovered(null);
          hide();
        }}
      />
    );
    offsetAccum += arcLength;
    return arc;
  });

  return (
    <div className="mini-donut chart-animate-in">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--track)" strokeWidth={thickness} />
        {arcs}
        <text x="50%" y="46%" textAnchor="middle" dominantBaseline="central" className="mini-donut-total">
          {total}
        </text>
        {centerLabel && (
          <text x="50%" y="62%" textAnchor="middle" dominantBaseline="central" className="mini-donut-caption">
            {centerLabel}
          </text>
        )}
      </svg>
      <div className="mini-donut-legend">
        {segments.map((s) => (
          <div
            key={s.label}
            className={`mini-donut-legend-item${hovered === s.label ? " active" : ""}`}
            onMouseEnter={() => setHovered(s.label)}
            onMouseLeave={() => setHovered(null)}
          >
            <span
              className="mini-donut-swatch"
              style={{ background: s.color, borderColor: s.ink ?? s.color }}
            />
            <span>
              {s.label}: <strong>{s.value}</strong>
            </span>
          </div>
        ))}
      </div>
      {card}
    </div>
  );
}
