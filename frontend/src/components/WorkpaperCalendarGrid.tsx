import { Fragment, useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";
import { formatMonthYear, formatMonthYearShort } from "../utils/date";
import type { WorkpaperCoverageRow } from "../types";

interface WorkpaperCalendarGridProps {
  rows: WorkpaperCoverageRow[];
}

/**
 * Control x month coverage grid — answers "do we have required workpaper
 * coverage across the entire audit period for each control" at a glance. A
 * hollow cell means no workpaper was filed for that control-month; it is
 * never read as the control having failed. Single CSS grid (row labels,
 * month headers and cells all as siblings in the SAME grid) so every column
 * lines up exactly — two separately-sized grids stacked on top of each
 * other cannot guarantee matching track widths and will drift out of
 * alignment as row/column counts change.
 */
export default function WorkpaperCalendarGrid({ rows }: WorkpaperCalendarGridProps) {
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

  // Sorted so controls with the most gaps lead — the question this answers
  // is "which controls need attention first", not an alphabetical listing.
  const sorted = [...rows].sort((a, b) => b.months_missing.length - a.months_missing.length);

  // Long labels stop fitting a single grid column once a period spans
  // roughly a year — beyond that, headers rotate vertically (a standard
  // pattern for dense calendar-style grids) so they read as one clean line
  // regardless of how narrow the pane gets, instead of wrapping mid-word.
  const rotateHeaders = months.length > 8;

  return (
    <div className="wp-calendar">
      <div
        className={`wp-calendar-grid${rotateHeaders ? " rotated-heads" : ""}`}
        style={{ gridTemplateColumns: `72px repeat(${months.length}, minmax(0, 1fr))` }}
      >
        <span />
        {months.map((m) => (
          <span key={m} className="wp-calendar-month-head">
            {rotateHeaders ? formatMonthYearShort(m) : formatMonthYear(m)}
          </span>
        ))}

        {sorted.map((r) => {
          const present = new Set(r.months_present);
          return (
            <Fragment key={r.control_id}>
              <span className="wp-calendar-row-label">{r.control_id}</span>
              {months.map((m) => {
                const isPresent = present.has(m);
                return (
                  <span
                    key={`${r.control_id}-${m}`}
                    className={`wp-calendar-cell${isPresent ? " present" : " missing"}`}
                    style={{ opacity: grow, transform: grow ? "scale(1)" : "scale(0.5)" }}
                    onMouseEnter={(e) =>
                      show(e, {
                        title: `${r.control_id} · ${formatMonthYear(m)}`,
                        value: isPresent ? "Workpaper filed" : "Not documented",
                        sub: isPresent
                          ? undefined
                          : "No workpaper was filed for this month — a coverage gap, not a control failure.",
                        color: isPresent ? "var(--pastel-green-ink)" : "var(--pastel-amber-ink)",
                      })
                    }
                    onMouseMove={move}
                    onMouseLeave={hide}
                  />
                );
              })}
            </Fragment>
          );
        })}
      </div>
      {card}
    </div>
  );
}
