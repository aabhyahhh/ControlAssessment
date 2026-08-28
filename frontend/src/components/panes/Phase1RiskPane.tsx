import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import GaugeRing from "../GaugeRing";
import TypedSummary from "../TypedSummary";
import MetricCard from "../MetricCard";
import RiskHeatmap from "../RiskHeatmap";
import StatusBadge from "../StatusBadge";
import type { Phase1Result } from "../../types";

/** Human label for an RCM field key, so the summary reads as prose rather
 *  than as column names lifted out of a spreadsheet. */
function fieldLabel(field: string): string {
  const known: Record<string, string> = {
    control_type: "control type",
    control_nature: "control nature",
    control_frequency: "control frequency",
    control_owner: "control owner",
    control_description: "control description",
    risk_description: "risk description",
    risk_level: "risk level",
  };
  return known[field] ?? field.replace(/_/g, " ");
}

/** Groups the per-control gaps by FIELD, commonest first. The per-control
 *  view repeated "1 field missing" once per control; grouping by field is
 *  what turns twelve rows into one fact. */
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

/** Builds the typed summary. The text is generated from the actual counts,
 *  so it stays true when the shape of the gap changes — one field missing
 *  everywhere reads differently from a scatter across many fields. */
function missingFieldsSummary(
  missing: { control_id: string; missing_fields: string[] }[],
): string[] {
  const groups = groupMissingFields(missing);
  if (groups.length === 0) return ["Every control carries all required fields."];

  const controlCount = missing.length;
  const top = groups[0];
  const paras: string[] = [];

  if (groups.length === 1) {
    const universal = top.controlIds.length === controlCount;
    paras.push(
      `${controlCount} control${controlCount === 1 ? "" : "s"} ${controlCount === 1 ? "is" : "are"} incomplete, and ` +
        `${universal ? "every one of them is missing the same single field" : `the only field involved is`} — ` +
        `${fieldLabel(top.field)}. This is one systematic gap in how the RCM was authored, not ${controlCount} separate problems.`,
    );
    paras.push(
      `Populating ${fieldLabel(top.field)} across ${universal ? "these controls" : `the ${top.controlIds.length} affected controls`} ` +
        `clears the entire completeness shortfall in a single pass.`,
    );
    return paras;
  }

  const rest = groups.slice(1);
  paras.push(
    `${controlCount} control${controlCount === 1 ? "" : "s"} ${controlCount === 1 ? "has" : "have"} at least one required field ` +
      `unpopulated, spread across ${groups.length} distinct fields. The most common is ${fieldLabel(top.field)}, ` +
      `absent on ${top.controlIds.length} of them.`,
  );
  paras.push(
    `The remainder ${rest.length === 1 ? "is" : "are"} ` +
      rest
        .slice(0, 3)
        .map((g) => `${fieldLabel(g.field)} (${g.controlIds.length})`)
        .join(", ") +
      `${rest.length > 3 ? `, and ${rest.length - 3} more` : ""}. ` +
      `Fixing ${fieldLabel(top.field)} first moves completeness the furthest for the least effort.`,
  );
  return paras;
}

interface Phase1RiskPaneProps {
  result: Phase1Result;
  onApproveInferences?: () => void;
  approving?: boolean;
  onChooseWeighting?: (body: {
    use_default: boolean;
    score_map?: Record<string, number>;
    bands?: { threshold: number; label: string }[];
  }) => void;
}

export default function Phase1RiskPane({
  result, onApproveInferences, approving, onChooseWeighting,
}: Phase1RiskPaneProps) {
  const [heatmapFilter, setHeatmapFilter] = useState<string[] | null>(null);
  const [customMode, setCustomMode] = useState(false);
  const [weights, setWeights] = useState({ low: 1, medium: 3, high: 6 });
  const [bandInputs, setBandInputs] = useState({ low: 5, medium: 17, high: 35 });

  // ── Gate 1: the RCM has no Risk Levels, so ask how to weight P x I ──
  if (result.awaiting_weighting) {
    const missing = result.controls_missing_risk_level ?? [];
    const matrix = result.default_matrix ?? {};
    const levels = ["low", "medium", "high"] as const;

    const previewMatrix = customMode
      ? Object.fromEntries(
          levels.flatMap((p) =>
            levels.map((i) => {
              const score = weights[p] * weights[i];
              const label =
                score <= bandInputs.low ? "Low"
                  : score <= bandInputs.medium ? "Medium"
                    : score <= bandInputs.high ? "High"
                      : "Critical";
              return [`${p}|${i}`, label];
            }),
          ),
        )
      : matrix;

    return (
      <div className="pane-section">
        <div className="pane-section-header">
          <h3>How should I weight risk?</h3>
          <p>
            {missing.length} control{missing.length === 1 ? " has" : "s have"} no Risk Level in the RCM. I'll infer
            each one from Probability × Impact — but the weighting decides every rating, so it's your call, not mine.
          </p>
        </div>

        <div className="weighting-choice">
          <button
            type="button"
            className={`weighting-option${!customMode ? " selected" : ""}`}
            onClick={() => setCustomMode(false)}
          >
            <span className="weighting-option-title">Default weighting</span>
            <span className="weighting-option-sub">Low=1, Medium=3, High=6 · bands 5 / 17 / 35</span>
          </button>
          <button
            type="button"
            className={`weighting-option${customMode ? " selected" : ""}`}
            onClick={() => setCustomMode(true)}
          >
            <span className="weighting-option-title">Custom weighting</span>
            <span className="weighting-option-sub">Set your own weights and band thresholds</span>
          </button>
        </div>

        {customMode && (
          <div className="weighting-form">
            <h4>Weights</h4>
            <div className="weighting-inputs">
              {levels.map((k) => (
                <label key={k}>
                  <span className="field-label">{k[0].toUpperCase() + k.slice(1)}</span>
                  <input
                    className="field-input"
                    type="number"
                    min={1}
                    value={weights[k]}
                    onChange={(e) => setWeights((w) => ({ ...w, [k]: Number(e.target.value) }))}
                  />
                </label>
              ))}
            </div>
            <h4>Band upper bounds (score ≤ threshold)</h4>
            <div className="weighting-inputs">
              {levels.map((k) => (
                <label key={k}>
                  <span className="field-label">{k[0].toUpperCase() + k.slice(1)}</span>
                  <input
                    className="field-input"
                    type="number"
                    min={1}
                    value={bandInputs[k]}
                    onChange={(e) => setBandInputs((b) => ({ ...b, [k]: Number(e.target.value) }))}
                  />
                </label>
              ))}
            </div>
            <p className="weighting-note">
              Anything scoring above the High threshold becomes <strong>Critical</strong>. Weights must increase
              Low &lt; Medium &lt; High, and thresholds must ascend.
            </p>
          </div>
        )}

        <div className="pane-subsection">
          <h4>Resulting Risk Matrix</h4>
          <table className="data-table risk-matrix-table">
            <thead>
              <tr>
                <th>Probability \ Impact</th>
                {levels.map((i) => <th key={i}>{i[0].toUpperCase() + i.slice(1)}</th>)}
              </tr>
            </thead>
            <tbody>
              {levels.map((p) => (
                <tr key={p}>
                  <td><strong>{p[0].toUpperCase() + p.slice(1)}</strong></td>
                  {levels.map((i) => (
                    <td key={i}>
                      <StatusBadge label={previewMatrix[`${p}|${i}`] ?? "—"} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <button
          className="kpmg-btn primary"
          style={{ marginTop: 18 }}
          disabled={approving}
          onClick={() =>
            onChooseWeighting?.(
              customMode
                ? {
                    use_default: false,
                    score_map: { ...weights },
                    bands: [
                      { threshold: bandInputs.low, label: "Low" },
                      { threshold: bandInputs.medium, label: "Medium" },
                      { threshold: bandInputs.high, label: "High" },
                    ],
                  }
                : { use_default: true },
            )
          }
        >
          {approving ? "Inferring…" : customMode ? "Use Custom Weighting & Infer" : "Use Default Weighting & Infer"}
        </button>
      </div>
    );
  }

  if (result.pending_risk_inferences && Object.keys(result.pending_risk_inferences).length > 0) {
    const entries = Object.entries(result.pending_risk_inferences);
    return (
      <div className="pane-section">
        <div className="pane-section-header">
          <h3>Risk Level Inference — Review Required</h3>
          <p>
            {entries.length} control{entries.length === 1 ? "" : "s"} were missing a Risk Level. Here's what I
            inferred — review before I proceed to scoring.
          </p>
          {result.weighting_used && (
            <p className="weighting-summary">
              Using the <strong>{result.weighting_used.is_default ? "default" : "custom"}</strong> weighting — Low=
              {result.weighting_used.score_map.low}, Medium={result.weighting_used.score_map.medium}, High=
              {result.weighting_used.score_map.high} · bands{" "}
              {result.weighting_used.bands.map((b) => b.threshold).join(" / ")}.
            </p>
          )}
        </div>
        <div className="data-table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Control ID</th>
                <th>Probability</th>
                <th>Impact</th>
                <th>Score</th>
                <th>Risk Level</th>
                <th>Source</th>
                <th>Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([controlId, inf]) => (
                <tr key={controlId}>
                  <td>{controlId}</td>
                  <td>{inf.probability || "—"}</td>
                  <td>{inf.impact || "—"}</td>
                  <td>{inf.score ? inf.score : "—"}</td>
                  <td>
                    <StatusBadge label={inf.value} />
                  </td>
                  <td className="data-table-reasoning">
                    {inf.source}
                    <br />
                    <span style={{ color: "var(--muted)", fontSize: 11 }}>{inf.confidence} confidence</span>
                  </td>
                  <td className="data-table-reasoning">{inf.reasoning}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button className="kpmg-btn primary" disabled={approving} onClick={onApproveInferences}>
          {approving ? "Applying…" : "Approve & Continue"}
        </button>
      </div>
    );
  }

  const stats = result.stats;
  const heatmap = result.heatmap;
  const queue = result.priority_queue ?? [];
  const missing = result.missing_attributes ?? [];

  const filteredQueue = heatmapFilter ? queue.filter((r) => heatmapFilter.includes(r.control_id)) : queue;

  return (
    <div className="pane-section">
      {/* "Top Exposure" was removed: with no control_type in most RCMs it
          renders the literal word "other", which tells the user nothing. */}
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Controls in RACM" value={stats.controls_in_racm} tone="blue" />
          <MetricCard
            label="RACM Completeness"
            value={`${Math.round(stats.racm_completeness_pct * 100)}%`}
            tone="teal"
          />
          <MetricCard label="High Risk Controls" value={stats.high_risk_count} tone="red" />
        </div>
      )}

      {stats && (
        <div className="pane-gauge-row">
          <GaugeRing
            value={stats.racm_completeness_pct}
            label="RACM"
            sublabel="Completeness"
            /* Sweeps red -> amber -> green as it fills, so the rating reads
               at a glance without parsing the number. */
            colorByValue
            detail={[
              `${stats.controls_in_racm} controls in scope`,
              `${stats.high_risk_count} rated high risk`,
              missing.length > 0
                ? `${missing.length} control(s) missing required fields`
                : "All required fields populated",
            ]}
          />
        </div>
      )}

      {heatmap && (
        <div className="pane-subsection">
          <h4>Risk Heatmap</h4>
          <div className="pane-center">
            <RiskHeatmap
              axes={heatmap.axes}
              cells={heatmap.cells}
              onCellClick={(cell) => setHeatmapFilter(heatmapFilter ? null : cell.control_ids)}
            />
          </div>
          {heatmapFilter && (
            <div className="pane-center">
              <button className="kpmg-btn ghost" style={{ marginTop: 10 }} onClick={() => setHeatmapFilter(null)}>
                Clear filter
              </button>
            </div>
          )}
        </div>
      )}

      {missing.length > 0 && (
        <div className="pane-subsection">
          <h4>Controls With Missing Fields</h4>
          {/* Twelve identical "1 field missing" rows told the reader nothing
              they couldn't get from one sentence. The gap is summarised by
              FIELD instead — which field is absent, and across how many
              controls — with the per-control detail kept in the chips. */}
          <TypedSummary paragraphs={missingFieldsSummary(missing)} />
          <div className="missing-field-groups">
            {groupMissingFields(missing).map((g) => (
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
        <h4>Priority Queue</h4>
        <div className="data-table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Control ID</th>
                <th>Risk</th>
                <th>Completeness</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {filteredQueue.map((row) => (
                <tr key={row.control_id}>
                  <td>{row.rank}</td>
                  <td>{row.control_id}</td>
                  <td>
                    <StatusBadge label={row.risk_rating} />
                  </td>
                  <td>{Math.round(row.completeness_pct * 100)}%</td>
                  <td className="data-table-reasoning">{row.description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
