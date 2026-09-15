import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";
import type { RcmFieldCompleteness } from "../types";

/** Human label for an RCM field key, so the matrix reads as prose rather
 *  than a raw column name. Falls back to a de-slugged version of any field
 *  the backend adds later, so nothing needs to be hardcoded here to stay
 *  correct. */
function fieldLabel(field: string): string {
  const known: Record<string, string> = {
    control_owner: "Owner",
    control_description: "Description",
    control_frequency: "Frequency",
    control_type: "Type",
    control_nature: "Nature",
    process: "Process",
  };
  return known[field] ?? field.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

interface FieldCompletenessMatrixProps {
  fields: RcmFieldCompleteness[];
  /** Control IDs in RCM row order — the matrix's column order, shared by
   *  every row so a given dot column always means the same control. */
  controlIds: string[];
  /** Currently filtered field, if any — highlights the matching row. */
  activeField?: string | null;
  onSelectField?: (field: string | null) => void;
}

/**
 * One row per RCM field, one dot per control (in RCM order): filled means
 * the field is populated on that control, outlined means blank. Answers
 * "how complete is the control population's source data before
 * reconciliation" as a composition across the whole population at once —
 * never a graded score, and a blank dot is never coloured as an error since
 * only Control ID is required; the rest is step-2 reconciliation scope.
 *
 * Fields and control order come entirely from the engine's own analytics
 * payload and the RCM's own row order — nothing here is hardcoded.
 */
export default function FieldCompletenessMatrix({
  fields,
  controlIds,
  activeField,
  onSelectField,
}: FieldCompletenessMatrixProps) {
  const { show, move, hide, card } = useHoverCard();
  const [grow, setGrow] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [fields, controlIds]);

  if (!fields.length || !controlIds.length) return null;

  // Sorted so the fields most in need of step-2 reconciliation lead — this
  // answers "what will step 2 have to establish first", not an alphabetical
  // field listing.
  const sorted = [...fields].sort((a, b) => b.blank - a.blank || a.field.localeCompare(b.field));

  return (
    <div className="fc-matrix">
      {sorted.map((f, rowIndex) => {
        const blankSet = new Set(f.blank_control_ids);
        const isActive = activeField === f.field;
        const isDimmed = activeField != null && !isActive;
        const isFilterable = f.blank > 0;
        return (
          <div key={f.field} className={`fc-matrix-row${isDimmed ? " dimmed" : ""}`}>
            <button
              type="button"
              className={`fc-matrix-row-label${isActive ? " active" : ""}`}
              disabled={!isFilterable}
              aria-pressed={isActive}
              onClick={() => isFilterable && onSelectField?.(isActive ? null : f.field)}
            >
              {fieldLabel(f.field)}
            </button>
            <div
              className="fc-matrix-dots"
              style={{
                // Staggers each row's dot fade-in slightly after the row
                // above it, capped so a long control list doesn't cascade
                // for seconds — see the shared .stagger convention.
                transitionDelay: `${Math.min(rowIndex, 8) * 40}ms`,
              }}
            >
              {controlIds.map((cid) => {
                const isBlank = blankSet.has(cid);
                return (
                  <span
                    key={cid}
                    className={`fc-matrix-dot${isBlank ? " blank" : " filled"}`}
                    style={{ opacity: grow, transform: grow ? "scale(1)" : "scale(0.4)" }}
                    onMouseEnter={(e) =>
                      show(e, {
                        title: `${cid} · ${fieldLabel(f.field)}`,
                        value: isBlank ? "Blank" : "Populated",
                        sub: isBlank
                          ? "Reconciled against the SOP in step 2."
                          : undefined,
                        color: isBlank ? "var(--pastel-amber-ink)" : "var(--pastel-green-ink)",
                      })
                    }
                    onMouseMove={move}
                    onMouseLeave={hide}
                  />
                );
              })}
            </div>
            <span className="fc-matrix-count">
              {f.populated}/{controlIds.length}
            </span>
          </div>
        );
      })}
      {card}
    </div>
  );
}
