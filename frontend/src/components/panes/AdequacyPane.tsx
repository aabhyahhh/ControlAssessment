import { useMemo, useRef, useState } from "react";
import MetricCard from "../MetricCard";
import RadarChart, { type RadarAxis } from "../RadarChart";
import StatusBadge from "../StatusBadge";
import FieldSupportBars from "../FieldSupportBars";
import WorkpaperCalendarGrid from "../WorkpaperCalendarGrid";
import RankedExceptionList from "../RankedExceptionList";
import StepFooterNote from "../StepFooterNote";
import TypedSummary from "../TypedSummary";
import { useHoverCard } from "../HoverCard";
import type {
  DeficiencyRow,
  DesignProfileAnalytics,
  Phase2Result,
  ReconciliationRow,
} from "../../types";

interface AdequacyPaneProps {
  result: Phase2Result;
}

const DIMENSION_LABELS: Record<string, string> = {
  evidence_design: "documentation",
  ownership: "authority",
  frequency: "frequency",
  automation: "automation",
  exception_management: "exception",
};

const RECON_FIELD_LABELS: Record<string, string> = {
  control_description: "description",
  control_owner: "owner",
  control_frequency: "frequency",
  control_type: "type",
  control_nature: "nature",
  risk_description: "risk",
  process: "process",
};

/** Re-grounded design profile: each axis is the SHARE of the assessable
 *  population the documentation actually supports on that dimension — a
 *  real ratio over a real population, never an invented score. A dimension
 *  where every control is "not_assessed" has no ratio to show. */
function buildAxes(profile: DesignProfileAnalytics | undefined): RadarAxis[] {
  if (!profile) return [];
  return profile.dimensions.map((d) => {
    const assessed = profile.total_controls - d.not_assessed;
    const ratio = assessed > 0 ? d.supported / assessed : 0;
    return {
      key: d.dimension,
      label: DIMENSION_LABELS[d.dimension] ?? d.dimension,
      value: ratio,
      display: assessed > 0 ? `${d.supported}/${assessed}` : "—",
      weak: d.contradicted > 0,
      detail: [
        `${d.supported} of ${assessed || 0} assessable control${assessed === 1 ? "" : "s"} supported`,
        d.contradicted > 0 ? `${d.contradicted} contradicted by the documentation` : "No contradictions found",
        d.undocumented > 0 ? `${d.undocumented} not addressed by the documentation` : "",
        d.not_assessed > 0 ? `${d.not_assessed} not assessed (no LLM available)` : "",
      ].filter(Boolean),
    };
  });
}

function ReconciliationTable({
  rows,
  activeField,
  onSelectField,
}: {
  rows: ReconciliationRow[];
  activeField: string | null;
  onSelectField: (field: string | null) => void;
}) {
  const { show, move, hide, card } = useHoverCard();
  const fields = Object.keys(RECON_FIELD_LABELS);

  const visibleRows = activeField
    ? rows.filter((r) => {
        const cell = r.fields?.[activeField];
        return cell && (cell.status === "contradicted" || cell.status === "undetermined");
      })
    : rows;

  return (
    <div className="data-table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Control ID</th>
            <th>In Docs</th>
            <th>Reconciled</th>
            {fields.map((f) => (
              <th
                key={f}
                className={`recon-field-header${activeField === f ? " active" : ""}`}
                onClick={() => onSelectField(activeField === f ? null : f)}
                style={{ cursor: "pointer" }}
                title="Click to filter to exceptions on this field"
              >
                {RECON_FIELD_LABELS[f]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {visibleRows.map((r) => (
            <tr key={r.control_id} id={`recon-row-${r.control_id}`}>
              <td>{r.control_id}</td>
              <td>
                <StatusBadge label={r.described_in_docs ? "Yes" : "No"} />
              </td>
              <td>{r.reconciliation_pct == null ? "—" : `${Math.round(r.reconciliation_pct * 100)}%`}</td>
              {fields.map((f) => {
                const cell = r.fields?.[f];
                const st = cell?.status ?? "absent";
                const mark = st === "supported" ? "✓" : st === "contradicted" ? "✕" : st === "undetermined" ? "?" : "–";
                return (
                  <td
                    key={f}
                    style={{ textAlign: "center", cursor: cell?.doc_value ? "help" : "default" }}
                    onMouseEnter={(e) =>
                      cell &&
                      show(e, {
                        title: `${r.control_id} · ${RECON_FIELD_LABELS[f]}`,
                        value: st,
                        items: [
                          `RCM: ${cell.rcm_value || "(blank)"}`,
                          `Docs: ${cell.doc_value || "(not stated)"}`,
                        ],
                        color:
                          st === "contradicted"
                            ? "var(--pastel-red-ink)"
                            : st === "supported"
                              ? "var(--pastel-green-ink)"
                              : "var(--muted)",
                      })
                    }
                    onMouseMove={move}
                    onMouseLeave={hide}
                  >
                    {mark}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {card}
      {visibleRows.length === 0 && (
        <p style={{ color: "var(--muted)", padding: "12px 4px" }}>No controls have an exception on this field.</p>
      )}
    </div>
  );
}

export default function AdequacyPane({ result }: AdequacyPaneProps) {
  const stats = result.stats;
  const deficiencies = result.deficiencies ?? [];
  const reconciliation = result.reconciliation ?? [];
  const workpaperCoverage = result.workpaper_coverage ?? [];
  const coverageGaps = result.coverage_gaps ?? [];
  const analytics = result.analytics;
  const [activeReconField, setActiveReconField] = useState<string | null>(null);

  const totalControls = deficiencies.length;
  const axes = useMemo(() => buildAxes(analytics?.design_profile), [analytics]);
  const deficiencyByControl = useMemo(
    () => new Map(deficiencies.map((d) => [d.control_id, d])),
    [deficiencies],
  );

  const reconDisclosureRef = useRef<HTMLDetailsElement>(null);

  // The reconciliation matrix lives behind a collapsed <details> disclosure
  // (it's secondary detail, not the primary view) — jumping to a control
  // from the ranked-exceptions list has to open it first, or the target row
  // is neither visible nor scrollable-to.
  const scrollToControl = (controlId: string) => {
    if (reconDisclosureRef.current) reconDisclosureRef.current.open = true;
    requestAnimationFrame(() => {
      const el = document.getElementById(`recon-row-${controlId}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  };

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Adequate" value={stats.adequate_count} tone="green" />
          <MetricCard
            label="Partially Adequate"
            value={stats.partially_adequate_count}
            tone="amber"
            sublabel="Fields unconfirmed"
          />
          <MetricCard
            label="Inadequate"
            value={stats.inadequate_count}
            tone="red"
            sublabel={`${stats.unreconciled_count} absent from SOPs`}
          />
          <MetricCard label="Workpaper Gaps" value={stats.workpaper_gap_count} tone="amber" sublabel="Missing a month" />
        </div>
      )}

      {analytics?.reconciliation_summary && analytics.reconciliation_summary.by_field.length > 0 && (
        <div className="pane-subsection">
          <h4>What The Documents Establish</h4>
          <p className="pane-subsection-note">
            Per RCM field, across all controls. A long amber band means the SOPs are silent on that field — not
            that the control is wrong. Click a field with an exception to see the affected controls.
          </p>
          <FieldSupportBars
            fields={analytics.reconciliation_summary.by_field}
            activeField={activeReconField}
            onSelectField={setActiveReconField}
          />
          {analytics.reconciliation_summary.most_contradicted_fields[0] && (
            <p className="field-support-caption">
              {RECON_FIELD_LABELS[analytics.reconciliation_summary.most_contradicted_fields[0].field] ??
                analytics.reconciliation_summary.most_contradicted_fields[0].field}{" "}
              · {analytics.reconciliation_summary.most_contradicted_fields[0].control_count} control
              {analytics.reconciliation_summary.most_contradicted_fields[0].control_count === 1 ? "" : "s"}{" "}
              contradicted by the documentation
            </p>
          )}
        </div>
      )}

      {analytics?.workpaper_coverage && workpaperCoverage.length > 0 && (
        <div className="pane-subsection">
          <h4>Workpaper Coverage Across The Period</h4>
          <p className="pane-subsection-note">
            {analytics.workpaper_coverage.total_missing_control_months} control-months are missing across the{" "}
            {workpaperCoverage[0]?.months_expected.length ?? 0}-month period
            {analytics.workpaper_coverage.months_most_missing[0]
              ? `; ${analytics.workpaper_coverage.months_most_missing[0].month.slice(5)} is the thinnest`
              : ""}
            . A cluster down one column usually means a period-end handover, not many separate failures.
          </p>
          <WorkpaperCalendarGrid rows={workpaperCoverage} analytics={analytics.workpaper_coverage} />
        </div>
      )}

      {analytics?.reconciliation_summary && analytics.reconciliation_summary.controls_by_exception_count.length > 0 && (
        <div className="pane-subsection">
          <h4>Most Reconciliation Outstanding</h4>
          <p className="pane-subsection-note">Click a control to view its full reconciliation row below.</p>
          <RankedExceptionList
            controlsByExceptionCount={analytics.reconciliation_summary.controls_by_exception_count}
            deficiencyByControl={deficiencyByControl}
            onSelectControl={scrollToControl}
          />
        </div>
      )}

      {reconciliation.length > 0 && (
        <details className="pane-disclosure" ref={reconDisclosureRef}>
          <summary>View control × field reconciliation matrix</summary>
          <div className="pane-subsection" style={{ marginTop: 12 }}>
            <p className="pane-subsection-note">
              ✓ supported, ✕ contradicted, – not mentioned, ? undetermined. Hover a cell for the RCM value vs what
              the documents say.
            </p>
            <ReconciliationTable
              rows={reconciliation}
              activeField={activeReconField}
              onSelectField={setActiveReconField}
            />
          </div>
        </details>
      )}

      {totalControls > 0 && (
        <details className="pane-disclosure">
          <summary>View design dimension profile</summary>
          <div className="pane-subsection" style={{ marginTop: 12 }}>
            {analytics?.design_profile?.assessed === false ? (
              <p style={{ color: "var(--muted)" }}>
                Design alignment could not be assessed for any control (no LLM available).
              </p>
            ) : (
              <>
                <p className="pane-subsection-note">
                  Share of assessable controls whose documentation supports each design dimension — not a score.
                  A dented profile shows where the SOPs corroborate the RCM least across the portfolio.
                </p>
                <div className="pane-center">
                  <RadarChart
                    axes={axes}
                    unitLabel="supported"
                    weakLabel="Contradicted by the documentation"
                    okLabel="No contradictions found"
                  />
                </div>
                <div className="design-chip-row">
                  {analytics?.design_profile.dimensions.map((d) => (
                    <span key={d.dimension} className={`design-chip${d.contradicted > 0 ? " weak" : ""}`}>
                      {DIMENSION_LABELS[d.dimension] ?? d.dimension}{" "}
                      <strong>{d.supported}/{d.supported + d.contradicted + d.undocumented}</strong>
                      {d.contradicted > 0 && ` · ${d.contradicted} contradicted`}
                    </span>
                  ))}
                </div>
              </>
            )}
            <div className="data-table-scroll" style={{ marginTop: 16 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Control ID</th>
                    <th>Design Verdict</th>
                    <th>Weak Dimensions</th>
                  </tr>
                </thead>
                <tbody>
                  {deficiencies.map((d: DeficiencyRow) => (
                    <tr key={d.control_id}>
                      <td>{d.control_id}</td>
                      <td>
                        <StatusBadge label={d.verdict} />
                      </td>
                      <td className="data-table-reasoning">{d.weak_dimensions.join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </details>
      )}

      {coverageGaps.length > 0 && (
        <div className="pane-subsection">
          <h4>SOP Steps With No Matching Control</h4>
          <div className="data-table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Step</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {coverageGaps.map((g) => (
                  <tr key={g.sop_step_id}>
                    <td>{g.sop_step_id}</td>
                    <td className="data-table-reasoning">{g.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <StepFooterNote text="Every figure derives from project state at render time — control count, period length and document counts drive the geometry. Nothing is fixed in the markup." />
    </div>
  );
}
