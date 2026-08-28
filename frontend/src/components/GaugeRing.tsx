import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";

interface GaugeBand {
  threshold: number;
  color: string;
  ink: string;
  label: string;
}

interface GaugeRingProps {
  value: number; // 0-1
  size?: number;
  thickness?: number;
  color?: string;
  label?: string;
  sublabel?: string;
  bands?: GaugeBand[];
  /** Extra lines for the hover card. */
  detail?: string[];
  /**
   * Colour the arc from the ANIMATING value rather than the final one, so it
   * sweeps red -> amber -> green as it fills. Makes the rating legible from
   * the motion itself, not just the number.
   */
  colorByValue?: boolean;
}

const DEFAULT_BANDS: GaugeBand[] = [
  { threshold: 0.5, color: "var(--pastel-red)", ink: "var(--pastel-red-ink)", label: "Needs attention" },
  { threshold: 0.8, color: "var(--pastel-amber)", ink: "var(--pastel-amber-ink)", label: "Fair" },
  { threshold: 1.01, color: "var(--pastel-green)", ink: "var(--pastel-green-ink)", label: "Good" },
];

function bandFor(value: number, bands: GaugeBand[]): GaugeBand {
  for (const band of bands) {
    if (value < band.threshold) return band;
  }
  return bands[bands.length - 1];
}

export default function GaugeRing({
  value, size = 150, thickness = 14, color, label, sublabel, bands = DEFAULT_BANDS, detail,
  colorByValue = false,
}: GaugeRingProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const arcFraction = 0.75; // 270-degree sweep, gap at the bottom
  const arcLength = circumference * arcFraction;
  const rotation = 135;

  const { show, move, hide, card } = useHoverCard();
  const [hovered, setHovered] = useState(false);

  // Animate from empty to the real value, and count the number up with it
  // so the figure and the arc arrive together.
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const start = performance.now();
    const duration = 900;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      // easeOutCubic
      setProgress(clamped * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [clamped]);

  const dashOffset = arcLength * (1 - progress);

  // The band the ARC should wear right now. With colorByValue it tracks the
  // animating figure so the ring passes through red and amber on its way to
  // the final rating; otherwise it settles on the final band immediately.
  const band = bandFor(colorByValue ? progress : clamped, bands);
  const fill = color ?? band.color;
  const ink = band.ink;
  // The hover card always describes the real value, never the mid-animation
  // one — a tooltip that reads "Needs attention" for a 92% gauge would be a
  // lie the moment the user hovers early.
  const finalBand = bandFor(clamped, bands);

  return (
    <div
      className="gauge-ring chart-animate-in"
      style={{ width: size }}
      onMouseEnter={(e) => {
        setHovered(true);
        show(e, {
          title: label ?? "Score",
          value: `${Math.round(clamped * 100)}%`,
          sub: `${finalBand.label}${sublabel ? ` · ${sublabel}` : ""}`,
          items: detail,
          color: finalBand.ink,
        });
      }}
      onMouseMove={move}
      onMouseLeave={() => {
        setHovered(false);
        hide();
      }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--track)"
          strokeWidth={thickness}
          strokeDasharray={`${arcLength} ${circumference}`}
          strokeLinecap="round"
          transform={`rotate(${rotation} ${size / 2} ${size / 2})`}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={fill}
          strokeWidth={hovered ? thickness + 3 : thickness}
          strokeDasharray={`${arcLength} ${circumference}`}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform={`rotate(${rotation} ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-width 160ms ease, stroke 320ms ease" }}
        />
        <text
          x="50%"
          y="50%"
          textAnchor="middle"
          dominantBaseline="central"
          className="gauge-ring-value"
          style={{ fill: ink, transition: "fill 320ms ease" }}
        >
          {Math.round(progress * 100)}%
        </text>
      </svg>
      {(label || sublabel) && (
        <div className="gauge-ring-caption">
          {label && <div className="gauge-ring-label">{label}</div>}
          {sublabel && <div className="gauge-ring-sublabel">{sublabel}</div>}
        </div>
      )}
      {card}
    </div>
  );
}
