import { useEffect, useState } from "react";

interface MetricCardProps {
  label: string;
  value: string | number;
  /** Accent applied to the value. */
  tone?: "blue" | "green" | "amber" | "red" | "violet" | "teal";
  sublabel?: string;
}

const TONES = {
  blue: { ink: "var(--pastel-blue-ink)" },
  green: { ink: "var(--pastel-green-ink)" },
  amber: { ink: "var(--pastel-amber-ink)" },
  red: { ink: "var(--pastel-red-ink)" },
  violet: { ink: "var(--pastel-violet-ink)" },
  teal: { ink: "var(--pastel-teal-ink)" },
} as const;

/** Counts a numeric value up on mount; passes text values straight through. */
function useCountUp(value: string | number): string | number {
  const target = typeof value === "number" ? value : Number(String(value).replace(/[^0-9.]/g, ""));
  const isNumeric = typeof value === "number" || (!Number.isNaN(target) && /\d/.test(String(value)));
  const suffix = typeof value === "string" ? String(value).replace(/[0-9.,\s]/g, "") : "";
  const [shown, setShown] = useState(isNumeric ? 0 : value);

  useEffect(() => {
    if (!isNumeric) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const duration = 700;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = target * eased;
      setShown(Number.isInteger(target) ? Math.round(current) : Number(current.toFixed(1)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, target, isNumeric]);

  return isNumeric ? `${shown}${suffix}` : shown;
}

export default function MetricCard({ label, value, tone = "blue", sublabel }: MetricCardProps) {
  const { ink } = TONES[tone];
  const shown = useCountUp(value);

  return (
    // The tone shows in the value's colour alone — see .metric-card in
    // styles.css for why the pastel top rule was dropped.
    <div className="metric-card">
      <div className="metric-card-value" style={{ color: ink }}>
        {shown}
      </div>
      <div className="metric-card-label">{label}</div>
      {sublabel && <div className="metric-card-sublabel">{sublabel}</div>}
    </div>
  );
}
