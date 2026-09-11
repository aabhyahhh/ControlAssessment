import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";
import type { RcmFieldCompleteness } from "../types";

/** Human label for an RCM field key, so the chart reads as prose rather than
 *  a raw column name. Falls back to a de-slugged version of any field the
 *  backend adds later, so nothing needs to be hardcoded here to stay correct. */
function fieldLabel(field: string): string {
  const known: Record<string, string> = {
    control_owner: "Control owner",
    control_description: "Control description",
    control_frequency: "Control frequency",
    control_type: "Control type",
    control_nature: "Control nature",
    process: "Process",
  };
  return known[field] ?? field.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

interface FieldCompletenessBarProps {
  fields: RcmFieldCompleteness[];
  totalControls: number;
  /** Currently filtered field, if any — highlights the matching row. */
  activeField?: string | null;
  onSelectField?: (field: string | null) => void;
}

/**
 * One horizontal bar per RCM field: populated vs blank, as a composition —
 * never a graded score. This answers "how complete is the control
 * population's source data before reconciliation", not "how good is the
 * RCM". A field is never coloured red for being blank: only Control ID is
 * required, so a blank recommended field is step-2 reconciliation scope,
 * rendered in the same neutral/attention amber used everywhere else for
 * "incomplete", never in the "contradiction" red.
 *
 * Fields are read entirely from the engine's own analytics payload — this
 * component invents no field names, counts, or thresholds.
 */
export default function FieldCompletenessBar({
  fields,
  totalControls,
  activeField,
  onSelectField,
}: FieldCompletenessBarProps) {
  const { show, move, hide, card } = useHoverCard();
  const [grow, setGrow] = useState(0);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [fields]);

  if (!fields.length || totalControls === 0) return null;

  // Sorted so the fields most in need of step-2 reconciliation lead — the
  // question this chart answers is "what will step 2 have to establish
  // first", not an alphabetical field listing.
  const sorted = [...fields].sort((a, b) => b.blank - a.blank || a.field.localeCompare(b.field));

  return (
    <div className="field-completeness-bar" role="group" aria-label="RCM field completeness by field — click a field to filter">
      {sorted.map((f) => {
        const populatedPct = totalControls ? f.populated / totalControls : 0;
        const isActive = activeField === f.field;
        const isDimmed = activeField != null && !isActive;
        // A field with nothing blank has no "reconcile in step 2" scope to
        // filter to — clicking it would just empty the sections below with
        // no explanation, so it isn't a filter trigger.
        const isFilterable = f.blank > 0;
        return (
          <button
            type="button"
            key={f.field}
            className={`fc-bar-row${isActive ? " active" : ""}${isDimmed ? " dimmed" : ""}`}
            aria-pressed={isActive}
            disabled={!isFilterable}
            onClick={() => isFilterable && onSelectField?.(isActive ? null : f.field)}
          >
            <span className="fc-bar-label">{fieldLabel(f.field)}</span>
            <span
              className="fc-bar-track"
              onMouseEnter={(e) =>
                show(e, {
                  title: fieldLabel(f.field),
                  value: `${f.populated} of ${totalControls} populated`,
                  sub:
                    f.blank === 0
                      ? "Populated on every control in scope."
                      : `Blank on ${f.blank} control${f.blank === 1 ? "" : "s"} — reconciled against the SOP in step 2.`,
                  items: f.blank_control_ids.slice(0, 6),
                  color: f.blank === 0 ? "var(--pastel-green-ink)" : "var(--pastel-amber-ink)",
                })
              }
              onMouseMove={move}
              onMouseLeave={hide}
            >
              <span
                className="fc-bar-fill"
                style={{ width: `${populatedPct * grow * 100}%` }}
              />
            </span>
            <span className="fc-bar-count">
              {f.populated}/{totalControls}
            </span>
          </button>
        );
      })}
      {card}
    </div>
  );
}
