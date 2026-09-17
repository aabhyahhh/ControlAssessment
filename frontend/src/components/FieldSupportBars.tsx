import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";
import type { ReconciliationFieldCounts } from "../types";

const RECON_FIELD_LABELS: Record<string, string> = {
  control_description: "Description",
  control_owner: "Owner",
  control_frequency: "Frequency",
  control_type: "Type",
  control_nature: "Nature",
  risk_description: "Risk",
  process: "Process",
};

function fieldLabel(field: string): string {
  return RECON_FIELD_LABELS[field] ?? field.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

interface FieldSupportBarsProps {
  fields: ReconciliationFieldCounts[];
  activeField: string | null;
  onSelectField: (field: string | null) => void;
}

const SEGMENT_ORDER = ["supported", "contradicted", "undocumented", "undetermined"] as const;
const SEGMENT_COLOR: Record<(typeof SEGMENT_ORDER)[number], string> = {
  supported: "var(--pastel-green-ink)",
  contradicted: "var(--pastel-red-ink)",
  undocumented: "var(--pane-line)",
  undetermined: "var(--pastel-amber-ink)",
};
const SEGMENT_LABEL: Record<(typeof SEGMENT_ORDER)[number], string> = {
  supported: "supported",
  contradicted: "contradicted",
  undocumented: "not mentioned",
  undetermined: "undetermined",
};

/**
 * One stacked bar per RCM field: what the SOPs/workpapers establish across
 * every control, at a glance. Answers "where does the source RCM disagree
 * with the governing documentation" per field, before drilling into the
 * control x field matrix. Every count comes straight from the engine's own
 * `reconciliation_summary.by_field` — no field list or category is
 * hardcoded here.
 */
export default function FieldSupportBars({ fields, activeField, onSelectField }: FieldSupportBarsProps) {
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

  if (!fields.length) return null;

  return (
    <div className="field-support-bars">
      {fields.map((f) => {
        const total = f.supported + f.contradicted + f.undocumented + f.undetermined;
        if (total === 0) return null;
        const isActive = activeField === f.field;
        const isDimmed = activeField != null && !isActive;
        const hasException = f.contradicted > 0 || f.undetermined > 0;
        return (
          <button
            type="button"
            key={f.field}
            className={`field-support-row${isActive ? " active" : ""}${isDimmed ? " dimmed" : ""}`}
            aria-pressed={isActive}
            disabled={!hasException}
            onClick={() => hasException && onSelectField(isActive ? null : f.field)}
          >
            <div className="field-support-row-head">
              <span className="field-support-label">{fieldLabel(f.field)}</span>
              <span className="field-support-count">{f.supported} of {total} supported</span>
            </div>
            <div className="field-support-track">
              {SEGMENT_ORDER.map((seg) => {
                const count = f[seg];
                if (count === 0) return null;
                return (
                  <span
                    key={seg}
                    className="field-support-segment"
                    style={{ width: `${(count / total) * grow * 100}%`, background: SEGMENT_COLOR[seg] }}
                    onMouseEnter={(e) =>
                      show(e, {
                        title: `${fieldLabel(f.field)} · ${SEGMENT_LABEL[seg]}`,
                        value: `${count} of ${total} controls`,
                        items: f.control_ids[seg].slice(0, 6),
                        color: SEGMENT_COLOR[seg],
                      })
                    }
                    onMouseMove={move}
                    onMouseLeave={hide}
                  />
                );
              })}
            </div>
          </button>
        );
      })}
      <div className="field-support-legend">
        {SEGMENT_ORDER.map((seg) => (
          <span key={seg} className="field-support-legend-item">
            <span className="field-support-legend-swatch" style={{ background: SEGMENT_COLOR[seg] }} />
            {SEGMENT_LABEL[seg]}
          </span>
        ))}
      </div>
      {card}
    </div>
  );
}
