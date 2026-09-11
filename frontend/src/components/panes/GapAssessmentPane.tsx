import { useMemo, useState } from "react";
import MetricCard from "../MetricCard";
import StatusBadge from "../StatusBadge";
import DistributionBar, { type DistributionSegment } from "../DistributionBar";
import EscalationFunnel from "../EscalationFunnel";
import TypedSummary from "../TypedSummary";
import type { GapAssessmentRow, GapAreaConcentration, Phase4Result, Severity } from "../../types";

interface GapAssessmentPaneProps {
  result: Phase4Result;
}

const SEVERITY_ORDER: (Severity | "none")[] = ["critical", "high", "medium", "low", "none"];
const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--pastel-red-ink)",
  high: "var(--pastel-red-ink)",
  medium: "var(--pastel-amber-ink)",
  low: "var(--pastel-blue-ink)",
  none: "var(--pastel-green-ink)",
};
const SEVERITY_FILL: Record<string, string> = {
  critical: "#9f1239",
  high: "var(--pastel-red-ink)",
  medium: "var(--pastel-amber-ink)",
  low: "var(--pastel-blue-ink)",
  none: "var(--pastel-green-ink)",
};

function GapCard({ row }: { row: GapAssessmentRow }) {
  const [open, setOpen] = useState(false);
  const sev = row.severity ?? "none";
  return (
    <div
      className={`ledger-card tone-${sev === "none" ? "effective" : sev === "medium" || sev === "low" ? "exceptions" : "ineffective"}${open ? " active" : ""}`}
      style={{ display: "block", cursor: "pointer" }}
      onClick={() => setOpen((v) => !v)}
    >
      <div className="ledger-card-head">
        <span className="ledger-card-id">{row.control_id}</span>
        <StatusBadge label={sev === "none" ? "no gap" : sev} />
      </div>
      {row.control_description && <span className="ledger-card-title">{row.control_description}</span>}
      <p style={{ fontSize: 12.5, margin: "8px 0 0", color: "var(--muted)" }}>{row.summary}</p>
      {open && (
        <div style={{ marginTop: 12, fontSize: 12.5 }}>
          {row.expected_documents.length > 0 && (
            <p style={{ margin: "6px 0" }}>
              <strong>Expected:</strong> {row.expected_documents.join(", ")}
            </p>
          )}
          {row.received_documents.length > 0 && (
            <p style={{ margin: "6px 0", color: "var(--pastel-green-ink)" }}>
              <strong>Received:</strong> {row.received_documents.join(", ")}
            </p>
          )}
          {row.missing_documents.length > 0 && (
            <p style={{ margin: "6px 0", color: "var(--pastel-red-ink)" }}>
              <strong>Missing:</strong> {row.missing_documents.join(", ")}
            </p>
          )}
          {row.rcm_field_gaps.length > 0 && (
            <p style={{ margin: "6px 0" }}>
              <strong>RCM fields blank:</strong> {row.rcm_field_gaps.join(", ")}
            </p>
          )}
          {row.sop_alignment && (
            <p style={{ margin: "6px 0" }}>
              <strong>SOP alignment:</strong> {row.sop_alignment}
              {row.reconciliation_pct != null && ` · ${Math.round(row.reconciliation_pct * 100)}% reconciled`}
            </p>
          )}
          {row.workpaper_months_missing.length > 0 && (
            <p style={{ margin: "6px 0", color: "var(--pastel-amber-ink)" }}>
              <strong>Workpaper months missing:</strong> {row.workpaper_months_missing.join(", ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function GapAreaBar({
  concentration,
  activeArea,
  onSelectArea,
}: {
  concentration: GapAreaConcentration[];
  activeArea: string | null;
  onSelectArea: (area: string | null) => void;
}) {
  if (!concentration.length) return null;
  const max = Math.max(...concentration.map((c) => c.control_count));
  return (
    <div className="gap-area-bars">
      {concentration.map((c) => {
        const isActive = activeArea === c.area;
        const isDimmed = activeArea != null && !isActive;
        return (
          <button
            type="button"
            key={c.area}
            className={`gap-area-row${isActive ? " active" : ""}${isDimmed ? " dimmed" : ""}`}
            aria-pressed={isActive}
            onClick={() => onSelectArea(isActive ? null : c.area)}
          >
            <span className="gap-area-label">{c.area}</span>
            <span className="gap-area-track">
              <span className="gap-area-fill" style={{ width: `${(c.control_count / max) * 100}%` }} />
            </span>
            <span className="gap-area-count">{c.control_count}</span>
          </button>
        );
      })}
    </div>
  );
}

function gapSummary(result: Phase4Result): string[] {
  const stats = result.stats;
  const analytics = result.analytics;
  if (!stats || !stats.controls_assessed) {
    return ["No controls have been assessed yet."];
  }
  const paras: string[] = [];
  if (stats.serious === 0 && stats.partial === 0) {
    paras.push(
      `All ${stats.controls_assessed} assessed controls are fully covered — no documentation or evidence gaps were identified.`,
    );
    return paras;
  }

  paras.push(
    `Of ${stats.controls_assessed} controls assessed, ${stats.fully_covered} ${stats.fully_covered === 1 ? "is" : "are"} fully covered, ` +
      `${stats.partial} ${stats.partial === 1 ? "has" : "have"} a low/medium gap, and ${stats.serious} ${stats.serious === 1 ? "has" : "have"} ` +
      `a critical or high gap requiring attention before the assessment can be concluded.`,
  );

  const topArea = analytics?.gap_area_concentration?.[0];
  if (topArea) {
    paras.push(
      `The most common gap is "${topArea.area.toLowerCase()}", affecting ${topArea.control_count} control${topArea.control_count === 1 ? "" : "s"}.`,
    );
  }

  const funnel = analytics?.coverage_funnel;
  if (funnel && funnel.length) {
    const last = funnel[funnel.length - 1];
    const first = funnel[0];
    if (first.count > 0) {
      paras.push(
        `${last.count} of ${first.count} controls in scope pass every documentation and evidence gate end to end.`,
      );
    }
  }
  return paras;
}

export default function GapAssessmentPane({ result }: GapAssessmentPaneProps) {
  const rows = result.rows ?? [];
  const stats = result.stats;
  const rollup = stats?.severity_rollup;
  const analytics = result.analytics;

  const [activeSeverity, setActiveSeverity] = useState<Severity | "none" | null>(null);
  const [activeArea, setActiveArea] = useState<string | null>(null);

  const grouped = useMemo(() => {
    const map = new Map<Severity | "none", GapAssessmentRow[]>();
    for (const r of rows) {
      const k = (r.severity ?? "none") as Severity | "none";
      if (!map.has(k)) map.set(k, []);
      map.get(k)!.push(r);
    }
    return map;
  }, [rows]);

  const areaControlIds = useMemo(() => {
    if (!activeArea || !analytics) return null;
    const entry = analytics.gap_area_concentration.find((c) => c.area === activeArea);
    return entry ? new Set(entry.control_ids) : new Set<string>();
  }, [activeArea, analytics]);

  const severitySegments: DistributionSegment[] = useMemo(
    () =>
      SEVERITY_ORDER.map((s) => ({
        key: s,
        label: s === "none" ? "No gap" : `${s[0].toUpperCase()}${s.slice(1)}`,
        count: rollup?.[s] ?? 0,
        color: SEVERITY_FILL[s],
        detail: (grouped.get(s) ?? []).slice(0, 6).map((r) => r.control_id),
      })),
    [rollup, grouped],
  );

  const visibleSeverities = activeSeverity ? [activeSeverity] : SEVERITY_ORDER;

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Controls Assessed" value={stats.controls_assessed} tone="blue" />
          <MetricCard label="Fully Covered" value={stats.fully_covered} tone="green" />
          <MetricCard label="Critical / High" value={stats.serious} tone="red" />
        </div>
      )}

      <div className="pane-subsection">
        <h4>Control Population Outcome</h4>
        <TypedSummary paragraphs={gapSummary(result)} />
      </div>

      {rollup && (
        <div className="pane-subsection">
          <h4>Gap Severity Distribution</h4>
          <p className="pane-subsection-note">
            The resulting assessment population by severity. Click a segment to filter the controls below.
          </p>
          <DistributionBar
            segments={severitySegments}
            activeKey={activeSeverity}
            onSelect={(k) => setActiveSeverity(k as Severity | "none" | null)}
          />
        </div>
      )}

      {analytics && analytics.coverage_funnel.length > 0 && (
        <div className="pane-subsection">
          <EscalationFunnel
            title="Control Population Coverage"
            total={analytics.coverage_funnel[0]?.count ?? 0}
            caption="Each stage is the count of controls that pass this gate AND every gate before it — a genuine narrowing of the same population, not independent totals."
            stages={analytics.coverage_funnel.map((s) => ({
              label: s.stage,
              count: s.count,
              unassessed: s.unassessed,
            }))}
          />
        </div>
      )}

      {analytics && analytics.gap_area_concentration.length > 0 && (
        <div className="pane-subsection">
          <h4>Where The Gaps Are</h4>
          <p className="pane-subsection-note">
            How many controls carry each kind of gap. Click a row to filter the controls below to that gap area.
          </p>
          <GapAreaBar
            concentration={analytics.gap_area_concentration}
            activeArea={activeArea}
            onSelectArea={setActiveArea}
          />
        </div>
      )}

      {(activeSeverity || activeArea) && (
        <p className="pane-subsection-note" style={{ marginBottom: 8 }}>
          Showing controls
          {activeSeverity && ` at ${activeSeverity === "none" ? "no gap" : `${activeSeverity} severity`}`}
          {activeSeverity && activeArea && " and"}
          {activeArea && ` with "${activeArea.toLowerCase()}"`} —{" "}
          <button
            type="button"
            className="pane-filter-clear"
            style={{ margin: 0 }}
            onClick={() => {
              setActiveSeverity(null);
              setActiveArea(null);
            }}
          >
            clear filters ×
          </button>
        </p>
      )}

      {visibleSeverities.map((s) => {
        const list = (grouped.get(s as Severity | "none") ?? []).filter(
          (r) => !areaControlIds || areaControlIds.has(r.control_id),
        );
        if (!list.length) return null;
        return (
          <div className="pane-subsection" key={s}>
            <h4 style={{ color: SEVERITY_COLOR[s] }}>
              {s === "none" ? "No gap" : `${s[0].toUpperCase()}${s.slice(1)} severity`} ({list.length})
            </h4>
            <div className="ledger-grid" style={{ display: "grid", gap: 12 }}>
              {list.map((row) => (
                <GapCard key={row.control_id} row={row} />
              ))}
            </div>
          </div>
        );
      })}

      <p className="pane-subsection-note" style={{ marginTop: 12 }}>
        Download the Excel summary above for the full gap assessment against the RCM, SOPs and evidence.
      </p>
    </div>
  );
}
