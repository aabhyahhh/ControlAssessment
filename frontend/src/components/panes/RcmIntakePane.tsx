import { useMemo, useState } from "react";
import { AlertTriangle } from "lucide-react";
import FieldCompletenessBar from "../FieldCompletenessBar";
import TypedSummary from "../TypedSummary";
import MetricCard from "../MetricCard";
import type { Phase1Result, RcmFieldCompleteness } from "../../types";

/** Human label for an RCM field key, so the summary reads as prose. */
function fieldLabel(field: string): string {
  const known: Record<string, string> = {
    control_type: "control type",
    control_nature: "control nature",
    control_frequency: "control frequency",
    control_owner: "control owner",
    control_description: "control description",
    process: "process",
  };
  return known[field] ?? field.replace(/_/g, " ");
}

function groupMissingFields(
  missing: { control_id: string; missing_fields: string[] }[],
): { field: string; controlIds: string[] }[] {
  const byField = new Map<string, string[]>();
  for (const m of missing) {
    for (const f of m.missing_fields) {
      if (!byField.has(f)) byField.set(f, []);
      byField.get(f)!.push(m.control_id);
    }
  }
  return [...byField.entries()]
    .map(([field, controlIds]) => ({ field, controlIds }))
    .sort((a, b) => b.controlIds.length - a.controlIds.length || a.field.localeCompare(b.field));
}

function missingFieldsSummary(
  missing: { control_id: string; missing_fields: string[] }[],
): string[] {
  const groups = groupMissingFields(missing);
  if (groups.length === 0)
    return [
      "Every control carries all recommended fields. The RCM is complete enough that step 2 has nothing to reconcile.",
    ];

  const controlCount = missing.length;
  const top = groups[0];
  const paras: string[] = [];

  paras.push(
    `${controlCount} control${controlCount === 1 ? "" : "s"} ${controlCount === 1 ? "has" : "have"} at least one ` +
      `recommended field blank. Only Control ID is required — the rest is reconciled against the SOP in step 2, ` +
      `so this is a map of what step 2 has to establish, not a list of errors.`,
  );
  if (groups.length === 1) {
    paras.push(
      `The only field involved is ${fieldLabel(top.field)}, absent on ${top.controlIds.length} control${top.controlIds.length === 1 ? "" : "s"}.`,
    );
  } else {
    const rest = groups.slice(1);
    paras.push(
      `The most common is ${fieldLabel(top.field)} (${top.controlIds.length}); the rest ${rest.length === 1 ? "is" : "are"} ` +
        rest.slice(0, 3).map((g) => `${fieldLabel(g.field)} (${g.controlIds.length})`).join(", ") +
        `${rest.length > 3 ? `, and ${rest.length - 3} more` : ""}.`,
    );
  }
  return paras;
}

interface RcmIntakePaneProps {
  result: Phase1Result;
}

export default function RcmIntakePane({ result }: RcmIntakePaneProps) {
  const stats = result.stats;
  const missing = result.missing_attributes ?? [];
  const rows = result.controls ?? [];
  const analyticsFields: RcmFieldCompleteness[] = result.analytics?.rcm_completeness.fields ?? [];
  const totalControls = result.analytics?.control_population.total ?? stats?.controls_in_racm ?? 0;

  const [activeField, setActiveField] = useState<string | null>(null);

  const visibleGroups = useMemo(() => {
    const groups = groupMissingFields(missing);
    return activeField ? groups.filter((g) => g.field === activeField) : groups;
  }, [missing, activeField]);

  const visibleRows = useMemo(() => {
    const base = rows.length
      ? rows
      : missing.map((m) => ({
          control_id: m.control_id,
          completeness_pct: 0,
          missing_fields: m.missing_fields,
          control_description: "",
        }));
    return activeField ? base.filter((r) => (r.missing_fields ?? []).includes(activeField)) : base;
  }, [rows, missing, activeField]);

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Controls in RCM" value={stats.controls_in_racm} tone="blue" />
          <MetricCard
            label="RCM Fields Populated"
            value={`${Math.round(stats.racm_completeness_pct * 100)}%`}
            tone="teal"
            sublabel="Across 5 recommended fields"
          />
          <MetricCard label="Controls With Blanks" value={missing.length} tone="amber" />
        </div>
      )}

      {analyticsFields.length > 0 && (
        <div className="pane-subsection">
          <h4>RCM Field Completeness</h4>
          <p className="pane-subsection-note">
            Only Control ID is required. This shows how many controls carry each recommended field before
            reconciliation — a blank field is scope for step 2, not a defect. Click a field to see which controls
            it's blank on.
          </p>
          <FieldCompletenessBar
            fields={analyticsFields}
            totalControls={totalControls}
            activeField={activeField}
            onSelectField={setActiveField}
          />
        </div>
      )}

      {missing.length > 0 && (
        <div className="pane-subsection">
          <h4>Fields To Reconcile In Step 2</h4>
          <TypedSummary paragraphs={missingFieldsSummary(missing)} />
          <div className="missing-field-groups">
            {visibleGroups.map((g) => (
              <div key={g.field} className="missing-field-group">
                <div className="missing-field-group-head">
                  <span className="missing-field-icon" aria-hidden="true">
                    <AlertTriangle size={14} strokeWidth={2} />
                  </span>
                  <code className="missing-field-name">{g.field}</code>
                  <span className="missing-field-count">
                    {g.controlIds.length} of {missing.length} control{missing.length === 1 ? "" : "s"}
                  </span>
                </div>
                <div className="missing-field-chips">
                  {g.controlIds.map((id) => (
                    <span key={id} className="missing-field-chip">{id}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="pane-subsection">
        <h4>
          Control Inventory
          {activeField && (
            <button type="button" className="pane-filter-clear" onClick={() => setActiveField(null)}>
              Clear filter: {fieldLabel(activeField)} blank ×
            </button>
          )}
        </h4>
        <div className="data-table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Control ID</th>
                <th>Completeness</th>
                <th>Blank Fields</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((row) => (
                <tr key={row.control_id}>
                  <td>{row.control_id}</td>
                  <td>{Math.round((row.completeness_pct ?? 0) * 100)}%</td>
                  <td className="data-table-reasoning">{(row.missing_fields ?? []).join(", ") || "—"}</td>
                  <td className="data-table-reasoning">{row.control_description || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
