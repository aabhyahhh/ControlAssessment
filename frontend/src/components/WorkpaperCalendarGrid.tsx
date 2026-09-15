import { Fragment, useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";
import type { WorkpaperCoverageAnalytics, WorkpaperCoverageRow } from "../types";

interface WorkpaperCalendarGridProps {
  rows: WorkpaperCoverageRow[];
  analytics: WorkpaperCoverageAnalytics;
}

/**
 * Control x month coverage grid, plus a "MISSING" summary row sized per
 * month across the whole population — answers "do we have required
 * workpaper coverage across the entire audit period for each control", and
 * where the thin months are, at a glance. A hollow cell means no workpaper
 * was filed for that control-month; it is never read as the control having
 * failed.
 */
export default function WorkpaperCalendarGrid({ rows, analytics }: WorkpaperCalendarGridProps) {
  const { show, move, hide, card } = useHoverCard();
  const [grow, setGrow] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [rows]);

  const months = rows[0]?.months_expected ?? [];
  if (!months.length) return null;

  const missingByMonth = new Map(analytics.months_most_missing.map((m) => [m.month, m.missing_control_count]));
  const maxMissing = Math.max(1, ...analytics.months_most_missing.map((m) => m.missing_control_count));

  // Sorted so controls with the most gaps lead — the question this answers
  // is "which controls need attention first", not an alphabetical listing.
  const sorted = [...rows].sort((a, b) => b.months_missing.length - a.months_missing.length);

  return (
    <div className="wp-calendar">
      <div className="wp-calendar-scroll">
        <div
          className="wp-calendar-grid"
          style={{ gridTemplateColumns: `100px repeat(${months.length}, minmax(28px, 1fr)) 34px` }}
        >
          <span />
          {months.map((m) => (
            <span key={m} className="wp-calendar-month-head">
              {m.slice(5)}
            </span>
          ))}
          <span />

          {sorted.map((r) => {
            const present = new Set(r.months_present);
            const missingCount = r.months_missing.length;
            return (
              <Fragment key={r.control_id}>
                <span className="wp-calendar-row-label">
                  {r.control_id}
                </span>
                {months.map((m) => {
                  const isPresent = present.has(m);
                  return (
                    <span
                      key={`${r.control_id}-${m}`}
                      className={`wp-calendar-cell${isPresent ? " present" : " missing"}`}
                      style={{ opacity: grow, transform: grow ? "scale(1)" : "scale(0.5)" }}
                      onMouseEnter={(e) =>
                        show(e, {
                          title: `${r.control_id} · ${m}`,
                          value: isPresent ? "Workpaper filed" : "Not documented",
                          sub: isPresent ? undefined : "No workpaper was filed for this month — a coverage gap, not a control failure.",
                          color: isPresent ? "var(--pastel-green-ink)" : "var(--pastel-amber-ink)",
                        })
                      }
                      onMouseMove={move}
                      onMouseLeave={hide}
                    />
                  );
                })}
                <span className="wp-calendar-delta">
                  {missingCount > 0 ? `−${missingCount}` : ""}
                </span>
              </Fragment>
            );
          })}
        </div>

        <div className="wp-calendar-missing-row" style={{ gridTemplateColumns: `100px repeat(${months.length}, minmax(28px, 1fr)) 34px` }}>
          <span className="wp-calendar-missing-label">MISSING</span>
          {months.map((m) => {
            const count = missingByMonth.get(m) ?? 0;
            return (
              <span key={m} className="wp-calendar-missing-cell-wrap">
                {count > 0 && (
                  <span
                    className="wp-calendar-missing-bar"
                    style={{ height: `${(count / maxMissing) * grow * 100}%` }}
                    onMouseEnter={(e) =>
                      show(e, {
                        title: m,
                        value: `${count} control${count === 1 ? "" : "s"} missing this month`,
                        color: "var(--pastel-amber-ink)",
                      })
                    }
                    onMouseMove={move}
                    onMouseLeave={hide}
                  />
                )}
              </span>
            );
          })}
          <span />
        </div>
      </div>
      {card}
    </div>
  );
}
