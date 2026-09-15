import { useEffect, useState } from "react";
import StatusBadge from "./StatusBadge";
import type { DeficiencyRow, ReconciliationSummaryAnalytics } from "../types";

interface RankedExceptionListProps {
  controlsByExceptionCount: ReconciliationSummaryAnalytics["controls_by_exception_count"];
  deficiencyByControl: Map<string, DeficiencyRow>;
  onSelectControl?: (controlId: string) => void;
}

/**
 * Controls ranked by how many reconciliation exceptions they carry — the
 * "chase this first" list. A red bar means at least one contradiction; an
 * amber bar means only undetermined cells (documentation the LLM couldn't
 * resolve, not a disagreement). Reuses the engine's own ranking
 * (`controls_by_exception_count` is already sorted) rather than
 * re-deriving an order here.
 */
export default function RankedExceptionList({
  controlsByExceptionCount,
  deficiencyByControl,
  onSelectControl,
}: RankedExceptionListProps) {
  const [grow, setGrow] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [controlsByExceptionCount]);

  if (!controlsByExceptionCount.length) return null;

  const max = Math.max(...controlsByExceptionCount.map((c) => c.contradicted + c.undetermined));

  return (
    <div className="ranked-exceptions">
      {controlsByExceptionCount.slice(0, 10).map((c) => {
        const total = c.contradicted + c.undetermined;
        const verdict = deficiencyByControl.get(c.control_id)?.verdict;
        return (
          <button
            type="button"
            key={c.control_id}
            className="ranked-exceptions-row"
            onClick={() => onSelectControl?.(c.control_id)}
          >
            <span className="ranked-exceptions-id">{c.control_id}</span>
            <span className="ranked-exceptions-track">
              {c.contradicted > 0 && (
                <span
                  className="ranked-exceptions-fill contradicted"
                  style={{ width: `${(c.contradicted / max) * grow * 100}%` }}
                />
              )}
              {c.undetermined > 0 && (
                <span
                  className="ranked-exceptions-fill undetermined"
                  style={{ width: `${(c.undetermined / max) * grow * 100}%` }}
                />
              )}
            </span>
            {verdict && <StatusBadge label={verdict} />}
          </button>
        );
      })}
    </div>
  );
}
