import { useEffect, useState } from "react";

export interface AttritionStage {
  label: string;
  count: number;
  /** Signed delta note explaining what dropped out at this stage, e.g.
   *  "-15 never named on the evidence list". Omitted on the first stage. */
  deltaNote?: string;
}

interface AttritionFunnelProps {
  stages: AttritionStage[];
  /** Denominator every bar is drawn against, so the narrowing reads as
   *  shape rather than four independently-scaled bars. */
  total: number;
}

/**
 * Full-width bars, one per stage, each reporting a percent-of-expected and
 * (from the second bar on) a delta note explaining what fell out since the
 * previous stage. Every stage must be a genuine subset of the one before it
 * — the caller is responsible for that invariant, same as EscalationFunnel.
 */
export default function AttritionFunnel({ stages, total }: AttritionFunnelProps) {
  const [grow, setGrow] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [stages]);

  if (!stages.length || total <= 0) return null;

  return (
    <div className="attrition-funnel">
      {stages.map((s) => {
        const pct = Math.round((s.count / total) * 100);
        // A bar under ~12% wide can't legibly hold its own count label
        // (the text would spill past the coloured fill onto the neutral
        // track) — render the count just outside the bar instead of
        // cramming it in for every stage regardless of width.
        const fillPct = Math.max((s.count / total) * grow * 100, s.count > 0 ? 3 : 0);
        const countFitsInside = fillPct >= 12;
        return (
          <div key={s.label} className="attrition-stage">
            <div className="attrition-stage-head">
              <span className="attrition-stage-label">{s.label}</span>
              <span className="attrition-stage-pct">{pct}% of expected</span>
            </div>
            <div className="attrition-track">
              <div className="attrition-fill" style={{ width: `${fillPct}%` }}>
                {countFitsInside && <span className="attrition-fill-count">{s.count}</span>}
              </div>
              {!countFitsInside && (
                <span className="attrition-fill-count-outside" style={{ left: `${fillPct}%` }}>
                  {s.count}
                </span>
              )}
            </div>
            {s.deltaNote && <p className="attrition-delta">{s.deltaNote}</p>}
          </div>
        );
      })}
    </div>
  );
}
