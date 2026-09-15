import { useCountUp } from "../hooks/useCountUp";

interface MetricCardProps {
  label: string;
  /** `undefined` renders "—" rather than a blank tile — real project state
   *  can genuinely be missing a figure (e.g. a step not yet run), and that
   *  must never be silently indistinguishable from a broken render. */
  value: string | number | undefined;
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
