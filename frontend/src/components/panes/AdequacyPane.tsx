import { useMemo, useState } from "react";
import MetricCard from "../MetricCard";
import RadarChart, { type RadarAxis } from "../RadarChart";
import StatusBadge from "../StatusBadge";
import { useHoverCard } from "../HoverCard";
import type {
  DeficiencyRow,
  DesignProfileAnalytics,
  Phase2Result,
  ReconciliationRow,
  ReconciliationSummaryAnalytics,
  WorkpaperCoverageAnalytics,
  WorkpaperCoverageRow,
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

function ExceptionSummaryStrip({
  summary,
  activeField,
  onSelectField,
}: {
  summary: ReconciliationSummaryAnalytics;
  activeField: string | null;
  onSelectField: (field: string | null) => void;
}) {
  const { cell_counts: c } = summary;
  const total = c.supported + c.contradicted + c.undocumented + c.undetermined;
  if (total === 0) return null;

  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="recon-exception-strip">
      <div className="recon-exception-metrics">
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--pastel-green-ink)" }}>
            {pct(c.supported)}%
          </span>
          <span className="recon-exception-label">Supported</span>
        </div>
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--pastel-red-ink)" }}>
            {pct(c.contradicted)}%
          </span>
          <span className="recon-exception-label">Contradicted</span>
        </div>
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--muted)" }}>
            {pct(c.undocumented)}%
          </span>
          <span className="recon-exception-label">Undocumented</span>
        </div>
        {c.undetermined > 0 && (
          <div className="recon-exception-metric">
            <span className="recon-exception-value" style={{ color: "var(--muted)" }}>
              {pct(c.undetermined)}%
            </span>
            <span className="recon-exception-label">Undetermined</span>
          </div>
        )}
      </div>

      {summary.most_contradicted_fields.length > 0 && (
        <div className="recon-exception-detail">
          <span className="recon-exception-detail-label">Most contradicted field:</span>
          {summary.most_contradicted_fields.slice(0, 3).map((f) => (
            <button
              key={f.field}
              type="button"
              className={`recon-field-chip${activeField === f.field ? " active" : ""}`}
              onClick={() => onSelectField(activeField === f.field ? null : f.field)}
            >
              {RECON_FIELD_LABELS[f.field] ?? f.field} ({f.control_count})
            </button>
          ))}
        </div>
      )}

      {summary.controls_by_exception_count.length > 0 && (
        <div className="recon-exception-detail">
          <span className="recon-exception-detail-label">Most exceptions:</span>
          {summary.controls_by_exception_count.slice(0, 5).map((c2) => (
            <span key={c2.control_id} className="recon-control-chip">
              {c2.control_id} ({c2.contradicted + c2.undetermined})
            </span>
          ))}
        </div>
      )}
    </div>
  );
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
            <tr key={r.control_id}>
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

function WorkpaperRollup({ analytics }: { analytics: WorkpaperCoverageAnalytics }) {
  if (analytics.overall_coverage_pct == null) return null;
  return (
    <div className="recon-exception-strip">
      <div className="recon-exception-metrics">
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--pastel-green-ink)" }}>
            {analytics.controls_complete}
          </span>
          <span className="recon-exception-label">Fully covered</span>
        </div>
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--pastel-amber-ink)" }}>
            {analytics.controls_with_missing}
          </span>
          <span className="recon-exception-label">Missing ≥1 month</span>
        </div>
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--pastel-amber-ink)" }}>
            {analytics.total_missing_control_months}
          </span>
          <span className="recon-exception-label">Missing control-months</span>
        </div>
        <div className="recon-exception-metric">
          <span className="recon-exception-value" style={{ color: "var(--text)" }}>
            {Math.round(analytics.overall_coverage_pct * 100)}%
          </span>
          <span className="recon-exception-label">Documentation coverage</span>
        </div>
      </div>
      {analytics.months_most_missing.length > 0 && (
        <div className="recon-exception-detail">
          <span className="recon-exception-detail-label">Most frequently missing:</span>
          {analytics.months_most_missing.slice(0, 4).map((m) => (
            <span key={m.month} className="recon-control-chip">
              {m.month} ({m.missing_control_count})
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function WorkpaperCoverage({ rows }: { rows: WorkpaperCoverageRow[] }) {
  const { show, move, hide, card } = useHoverCard();
  const months = rows[0]?.months_expected ?? [];
  if (!months.length) return null;
  return (
    <div className="data-table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Control ID</th>
            <th>Coverage</th>
            {months.map((m) => (
              <th key={m} style={{ writingMode: "vertical-rl", fontSize: 10 }}>
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const present = new Set(r.months_present);
            return (
              <tr key={r.control_id}>
                <td>{r.control_id}</td>
                <td
                  style={{ cursor: "help" }}
                  onMouseEnter={(e) =>
                    show(e, {
                      title: r.control_id,
                      value: `${Math.round(r.coverage_pct * 100)}%`,
                      items: [
                        `${r.months_present.length}/${months.length} months documented`,
                        r.months_missing.length
                          ? `Not documented: ${r.months_missing.join(", ")}`
                          : "No months missing",
                      ],
                      color: r.months_missing.length ? "var(--pastel-amber-ink)" : "var(--pastel-green-ink)",
                    })
                  }
                  onMouseMove={move}
                  onMouseLeave={hide}
                >
                  {Math.round(r.coverage_pct * 100)}%
                </td>
                {months.map((m) => (
                  <td
                    key={m}
                    style={{
                      textAlign: "center",
                      background: present.has(m) ? "var(--pastel-green)" : "var(--pastel-amber)",
                      color: present.has(m) ? "var(--pastel-green-ink)" : "var(--pastel-amber-ink)",
                    }}
                  >
                    {present.has(m) ? "●" : "○"}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {card}
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
  const [tab, setTab] = useState<"reconcile" | "design" | "workpapers">("reconcile");
  const [activeReconField, setActiveReconField] = useState<string | null>(null);

  const totalControls = deficiencies.length;
  const axes = useMemo(() => buildAxes(analytics?.design_profile), [analytics]);

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Adequate" value={stats.adequate_count} tone="green" />
          <MetricCard label="Partially Adequate" value={stats.partially_adequate_count} tone="amber" />
          <MetricCard label="Inadequate" value={stats.inadequate_count} tone="red" />
          <MetricCard label="Not In Docs" value={stats.unreconciled_count} tone="red" />
          <MetricCard label="Workpaper Gaps" value={stats.workpaper_gap_count} tone="amber" />
        </div>
      )}

      <div className="phase4-view-toggle">
        <button
          type="button"
          className={`kpmg-btn ${tab === "reconcile" ? "primary" : "ghost"} attr-btn-sm`}
          onClick={() => setTab("reconcile")}
        >
          Reconciliation
        </button>
        <button
          type="button"
          className={`kpmg-btn ${tab === "workpapers" ? "primary" : "ghost"} attr-btn-sm`}
          onClick={() => setTab("workpapers")}
        >
          Workpaper Coverage
        </button>
        <button
          type="button"
          className={`kpmg-btn ${tab === "design" ? "primary" : "ghost"} attr-btn-sm`}
          onClick={() => setTab("design")}
        >
          Design Profile
        </button>
      </div>

      {tab === "reconcile" && (
        <div className="pane-subsection">
          <h4>RCM ↔ Documentation Reconciliation</h4>
          <p className="pane-subsection-note">
            Each RCM field checked against the SOP and workpapers: ✓ supported, ✕ contradicted, – not mentioned,
            ? undetermined. Hover a cell for the RCM value vs what the documents say; click a column header to
            filter to its exceptions.
          </p>
          {analytics?.reconciliation_summary && (
            <ExceptionSummaryStrip
              summary={analytics.reconciliation_summary}
              activeField={activeReconField}
              onSelectField={setActiveReconField}
            />
          )}
          {reconciliation.length ? (
            <ReconciliationTable
              rows={reconciliation}
              activeField={activeReconField}
              onSelectField={setActiveReconField}
            />
          ) : (
            <p style={{ color: "var(--muted)" }}>No reconciliation rows.</p>
          )}
        </div>
      )}

      {tab === "workpapers" && (
        <div className="pane-subsection">
          <h4>Monthly Workpaper Coverage</h4>
          <p className="pane-subsection-note">
            One workpaper is expected per calendar month of the audit period. Filled dots are months a workpaper
            was found for; hollow dots mean no workpaper was filed for that month — not that the control failed.
          </p>
          {analytics?.workpaper_coverage && <WorkpaperRollup analytics={analytics.workpaper_coverage} />}
          {workpaperCoverage.length ? (
            <WorkpaperCoverage rows={workpaperCoverage} />
          ) : (
            <p style={{ color: "var(--muted)" }}>No workpapers were matched to a month.</p>
          )}
        </div>
      )}

      {tab === "design" && totalControls > 0 && (
        <div className="pane-subsection">
          <h4>Design Profile</h4>
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
    </div>
  );
}
