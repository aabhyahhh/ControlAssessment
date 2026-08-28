import {
  Crosshair, FileText, Flag, FolderOpen, Monitor, PenLine, Receipt, Scale, ScrollText, Table2,
} from "lucide-react";
import CollapsibleRow from "../CollapsibleRow";
import EscalationFunnel from "../EscalationFunnel";
import EvidenceCoverageGrid from "../EvidenceCoverageGrid";
import MetricCard from "../MetricCard";
import StatusBadge from "../StatusBadge";
import { useHoverCard } from "../HoverCard";
import type { Phase2Result } from "../../types";

interface Phase2EvidencePaneProps {
  result: Phase2Result;
}

/** Soft pastel fills, matching the rest of the palette. The saturated `-ink`
 *  values were far too heavy for a full-width bar — they're for text and
 *  borders, not large areas. */
function barTone(score: number): { fill: string; ink: string; label: string } {
  if (score < 30) return { fill: "var(--pastel-red)", ink: "var(--pastel-red-ink)", label: "Poor" };
  if (score < 70) return { fill: "var(--pastel-amber)", ink: "var(--pastel-amber-ink)", label: "Fair" };
  return { fill: "var(--pastel-green)", ink: "var(--pastel-green-ink)", label: "Good" };
}

/** A line icon per document kind, so the list scans as a set of artefacts
 *  rather than a paragraph of prose. Line icons, not emoji: emoji render in
 *  each platform's own cartoon style, which is wrong for an audit workpaper. */
function DocIcon({ name }: { name: string }) {
  const n = name.toLowerCase();
  const Icon = /reconcil|tie-?out/.test(n)
    ? Scale
    : /screenshot|system|export|report|listing/.test(n)
      ? Monitor
      : /sign-?off|approv|authoriz/.test(n)
        ? PenLine
        : /invoice|statement|remittance|bank/.test(n)
          ? Receipt
          : /spreadsheet|worksheet|workpaper|calculat/.test(n)
            ? Table2
            : /log|tracker|exception|variance/.test(n)
              ? Flag
              : /agreement|contract|schedule|policy/.test(n)
                ? ScrollText
                : /sampl/.test(n)
                  ? Crosshair
                  : FileText;
  return <Icon size={15} strokeWidth={1.9} aria-hidden="true" />;
}

/** States the band the control actually landed in. Mirrors
 *  evidence_gap_engine._severity — keep the two in step. */
function severityRationale(riskRating: string, score: number | undefined): string {
  if (score === undefined) return "Severity assigned from the control's risk rating.";
  if (riskRating === "High") {
    return score < 30
      ? "High-risk and below 30% → High/Serious."
      : "High-risk, between 30% and 50% → Medium/Moderate.";
  }
  if (riskRating === "Medium") return "Medium-risk below the threshold → Medium/Moderate.";
  return "Low-risk below the threshold → Low/Minor.";
}

export default function Phase2EvidencePane({ result }: Phase2EvidencePaneProps) {
  const stats = result.stats;
  const missingDocs = result.missing_documents ?? [];
  const scores = result.evidence_scores ?? [];
  const gaps = result.escalated_gaps ?? [];
  const formatFlags = result.format_flags ?? [];
  const requiredDocs = result.required_documents ?? {};
  const missingByControl = new Map(missingDocs.map((m) => [m.control_id, m]));
  const scoreByControl = new Map(scores.map((s) => [s.control_id, s.score]));
  const { show, move, hide, card } = useHoverCard();

  // Funnel tiers, all counted from the engine's own output. The 50% figure is
  // evidence_gap_engine._ESCALATION_THRESHOLD — a control below it escalates,
  // which is exactly what `escalated_gaps` contains.
  const escalatedIds = new Set(gaps.map((g) => g.control_id));
  const belowThreshold = scores.filter((sc) => sc.score < 50).length;
  const highSeverity = gaps.filter((g) => /high/i.test(g.severity)).length;
  const totalControls = scores.length;

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Avg Evidence Score" value={`${stats.avg_evidence_score}%`} />
          <MetricCard label="Controls Without Evidence" value={stats.controls_without_evidence} tone="red" />
          <MetricCard label="Evidence Gaps" value={stats.evidence_gaps_count} tone="amber" />
          <MetricCard label="Test-Ready Controls" value={stats.test_ready_controls} tone="green" />
        </div>
      )}

      {totalControls > 0 && (
        <div className="pane-subsection evidence-dashboard">
          <div className="coverage-panel">
            <h4>Evidence coverage grid</h4>
            <p className="pane-subsection-note">
              Every expected document, per control. Hollow means it never arrived.
            </p>
            <EvidenceCoverageGrid
              requiredDocuments={requiredDocs}
              missingByControl={new Map(missingDocs.map((m) => [m.control_id, m.missing]))}
              scoreByControl={scoreByControl}
              escalatedControls={escalatedIds}
            />
          </div>

          <EscalationFunnel
            total={totalControls}
            caption={`How ${totalControls} control${totalControls === 1 ? "" : "s"} narrow to the ones that block sign-off.`}
            stages={[
              { label: "Controls in scope", count: totalControls, tone: "blue" },
              { label: "Below the 50% evidence threshold", count: belowThreshold, tone: "amber" },
              { label: "High / Serious severity", count: highSeverity, tone: "red" },
            ]}
          />
        </div>
      )}

      {formatFlags.length > 0 && (
        <div className="pane-subsection">
          <h4>Evidence Format Warnings</h4>
          <p style={{ color: "var(--muted)", fontSize: 12.5, margin: "0 0 10px" }}>
            These controls have evidence files but aren't organized into samples yet. They'll be excluded from
            effectiveness testing in Phase 4 until reorganized into <code>sample1/</code>, <code>sample2/</code>...
            subfolders or <code>sample_N</code>-named files.
          </p>
          <div className="data-table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Control ID</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {formatFlags.map((f) => (
                  <tr key={f.control_id}>
                    <td>{f.control_id}</td>
                    <td>
                      <StatusBadge label="Invalid Format" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {scores.length > 0 && (
        <div className="pane-subsection">
          <h4>Evidence Completeness by Control</h4>
          <div className="evidence-bar-list">
            {scores.map((row) => {
              const tone = barTone(row.score);
              const miss = missingByControl.get(row.control_id);
              const required = requiredDocs[row.control_id]?.length ?? 0;
              const missingCount = miss?.missing.length ?? 0;
              return (
                <div
                  key={row.control_id}
                  className="evidence-bar-row"
                  onMouseEnter={(e) =>
                    show(e, {
                      title: row.control_id,
                      value: `${row.score}%`,
                      sub: `${tone.label} · ${row.band}`,
                      items: [
                        `${required - missingCount} of ${required} expected documents matched`,
                        missingCount > 0
                          ? `${missingCount} still missing`
                          : "Nothing outstanding",
                      ],
                      color: tone.ink,
                    })
                  }
                  onMouseMove={move}
                  onMouseLeave={hide}
                >
                  <span className="evidence-bar-label">{row.control_id}</span>
                  <div className="evidence-bar-track">
                    <div
                      className="evidence-bar-fill"
                      style={{
                        // A true 0% renders nothing at all, which reads as
                        // "no data" rather than "scored zero". A minimum
                        // sliver keeps the row present and coloured.
                        width: row.score === 0 ? "3px" : `${row.score}%`,
                        background: tone.fill,
                        borderRight: `2px solid ${tone.ink}`,
                      }}
                    />
                  </div>
                  <span className="evidence-bar-value" style={{ color: tone.ink }}>
                    {row.score}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {missingDocs.length > 0 && (
        <div className="pane-subsection">
          <h4>Missing Documents by Control</h4>
          <div className="collapsible-list">
            {missingDocs.map((m) => (
              <CollapsibleRow
                key={m.control_id}
                id={m.control_id}
                icon={<FolderOpen size={15} strokeWidth={1.9} />}
                tone="red"
                summary={`${m.missing.length} document${m.missing.length === 1 ? "" : "s"} missing`}
              >
                <ul className="doc-list">
                  {m.missing.map((doc, i) => (
                    <li key={i}>
                      <span className="doc-list-icon" aria-hidden="true"><DocIcon name={doc} /></span>
                      <span className="doc-list-text">{doc}</span>
                    </li>
                  ))}
                </ul>
              </CollapsibleRow>
            ))}
          </div>
        </div>
      )}

      {gaps.length > 0 && (
        <div className="pane-subsection">
          <h4>Escalated Gaps</h4>
          <p className="pane-subsection-note">
            A control escalates when its evidence score falls below 50%. Severity is then weighted by the
            control's risk rating — hover a card for the reasoning behind its rating.
          </p>
          <div className="gap-card-list">
            {gaps.map((g) => {
              const score = scoreByControl.get(g.control_id);
              const required = requiredDocs[g.control_id]?.length ?? 0;
              const missingCount = missingByControl.get(g.control_id)?.missing.length ?? 0;
              return (
                <div
                  key={g.control_id}
                  className="gap-card"
                  onMouseEnter={(e) =>
                    show(e, {
                      title: `${g.control_id} — why this escalated`,
                      value: g.severity,
                      sub: `${g.risk_rating}-risk control, ${score ?? "?"}% evidence score`,
                      items: [
                        `Scored ${score ?? "?"}%, below the 50% escalation threshold`,
                        required
                          ? `${required - missingCount} of ${required} expected documents matched`
                          : "No expected-document checklist was generated",
                        severityRationale(g.risk_rating, score),
                      ],
                      // The documents themselves, not a count of them: the
                      // reader's next action is to go and ask for these
                      // specific artefacts, so name them.
                      rowsHeading:
                        missingCount > 0
                          ? `Missing document${missingCount === 1 ? "" : "s"} (${missingCount})`
                          : undefined,
                      rows: (missingByControl.get(g.control_id)?.missing ?? []).map((doc) => ({
                        icon: <DocIcon name={doc} />,
                        text: doc,
                      })),
                      color: "var(--pastel-red-ink)",
                    })
                  }
                  onMouseMove={move}
                  onMouseLeave={hide}
                >
                  <span className="gap-card-control-id">{g.control_id}</span>
                  <div className="gap-card-body">
                    {/* The bar restates the shortfall as a shape: how little
                        of the expected file actually arrived. */}
                    <div className="gap-card-bar">
                      <div
                        className="gap-card-bar-fill"
                        style={{
                          width: `${Math.max(score ?? 0, 3)}%`,
                          background: /high/i.test(g.severity)
                            ? "var(--pastel-red-ink)"
                            : "var(--pastel-amber-ink)",
                        }}
                      />
                    </div>
                    <p className="gap-card-explanation">{g.explanation}</p>
                  </div>
                  <StatusBadge label={g.severity} />
                </div>
              );
            })}
          </div>
        </div>
      )}
      {/* Exactly one render of the hover portal for this component's single
          useHoverCard() hook, at the root so every section can use it. Two
          renders mounted two identical cards on top of each other. */}
      {card}
    </div>
  );
}
