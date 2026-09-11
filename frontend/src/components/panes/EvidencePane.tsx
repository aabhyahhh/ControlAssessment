import { useEffect, useMemo, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import MetricCard from "../MetricCard";
import StatusBadge from "../StatusBadge";
import CollapsibleRow from "../CollapsibleRow";
import EscalationFunnel from "../EscalationFunnel";
import TypedSummary from "../TypedSummary";
import { useHoverCard } from "../HoverCard";
import type {
  DeclaredEvidence,
  DeclaredEvidenceItem,
  EvidenceStatusMatrixRow,
  Phase3Analytics,
  Phase3Result,
  Severity,
} from "../../types";

interface EvidencePaneProps {
  result: Phase3Result | null;
  /** Control IDs from the RCM, so a list can be started for any control. */
  controlIds: string[];
  declared: DeclaredEvidence[];
  busy?: boolean;
  onSaveList: (controlId: string, items: DeclaredEvidenceItem[]) => void;
  onRun: () => void;
}

const SEVERITY_TONE: Record<Severity, "red" | "amber" | "blue"> = {
  critical: "red",
  high: "red",
  medium: "amber",
  low: "blue",
};

/** Editable per-control declared-evidence list. */
function ListEditor({
  controlId,
  items,
  busy,
  onSave,
}: {
  controlId: string;
  items: DeclaredEvidenceItem[];
  busy?: boolean;
  onSave: (items: DeclaredEvidenceItem[]) => void;
}) {
  const [draft, setDraft] = useState<DeclaredEvidenceItem[]>(items);
  const [newName, setNewName] = useState("");
  useEffect(() => setDraft(items), [items]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(items);

  return (
    <div className="evidence-list-editor">
      <ul className="doc-list">
        {draft.map((it, i) => (
          <li key={i}>
            <input
              className="field-input"
              value={it.name}
              onChange={(e) =>
                setDraft((d) => d.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))
              }
            />
            <button
              type="button"
              className="project-card-delete"
              aria-label="Remove"
              onClick={() => setDraft((d) => d.filter((_, j) => j !== i))}
            >
              <Trash2 size={14} />
            </button>
          </li>
        ))}
      </ul>
      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        <input
          className="field-input"
          placeholder="Add an evidence item…"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && newName.trim()) {
              setDraft((d) => [...d, { name: newName.trim() }]);
              setNewName("");
            }
          }}
        />
        <button
          type="button"
          className="kpmg-btn ghost attr-btn-sm"
          disabled={!newName.trim()}
          onClick={() => {
            setDraft((d) => [...d, { name: newName.trim() }]);
            setNewName("");
          }}
        >
          <Plus size={14} />
        </button>
      </div>
      <button
        type="button"
        className="kpmg-btn primary attr-btn-sm"
        style={{ marginTop: 10 }}
        disabled={!dirty || busy}
        onClick={() => onSave(draft.filter((x) => x.name.trim()))}
      >
        {busy ? "Saving…" : dirty ? `Save list for ${controlId}` : "Saved"}
      </button>
    </div>
  );
}

/** EXPECTED -> DECLARED -> UPLOADED -> COVERED, at the document level across
 *  the whole portfolio. Every stage is a strict subset of the one before it
 *  (enforced by the engine, not recomputed here), so the narrowing is a real
 *  population funnel, not four independent counts. */
function EvidenceFunnel({ analytics }: { analytics: Phase3Analytics }) {
  if (analytics.expected_total === 0) return null;
  return (
    <EscalationFunnel
      title="Evidence reconciliation"
      total={analytics.expected_total}
      caption="Every expected evidence document, tracked through to whether a file actually exists for it."
      stages={[
        { label: "Expected", count: analytics.expected_total },
        { label: "Declared by user", count: analytics.declared_total },
        { label: "Uploaded", count: analytics.uploaded_total },
        { label: "Covered (file matched)", count: analytics.covered_total },
      ]}
    />
  );
}

/** Fixed-column control x evidence-status table. Columns are the engine's
 *  own reconciliation outcome keys (expected / received / declared-not-
 *  uploaded / missing) — never a guessed document-category grid. */
function StatusMatrix({
  rows,
  onSelectControl,
}: {
  rows: EvidenceStatusMatrixRow[];
  onSelectControl: (controlId: string) => void;
}) {
  const { show, move, hide, card } = useHoverCard();
  if (!rows.length) return null;

  return (
    <div className="data-table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            <th>Control ID</th>
            <th>Expected</th>
            <th>Received</th>
            <th>Declared, Not Uploaded</th>
            <th>Missing</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.control_id} onClick={() => onSelectControl(r.control_id)} style={{ cursor: "pointer" }}>
              <td>{r.control_id}</td>
              <td>{r.expected}</td>
              <td style={{ color: r.received > 0 ? "var(--pastel-green-ink)" : undefined }}>{r.received}</td>
              <td
                style={{ color: r.declared_not_uploaded > 0 ? "var(--pastel-amber-ink)" : undefined, cursor: "help" }}
                onMouseEnter={(e) =>
                  r.declared_not_uploaded > 0 &&
                  show(e, {
                    title: r.control_id,
                    value: `${r.declared_not_uploaded} declared, not uploaded`,
                    sub: "The user says this evidence exists, but no matching file has been uploaded yet.",
                  })
                }
                onMouseMove={move}
                onMouseLeave={hide}
              >
                {r.declared_not_uploaded}
              </td>
              <td style={{ color: r.missing > 0 ? "var(--pastel-red-ink)" : undefined }}>{r.missing}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {card}
    </div>
  );
}

function evidenceSummary(analytics: Phase3Analytics | undefined, totalControls: number): string[] {
  if (!analytics || analytics.expected_total === 0) {
    return ["No expected-evidence checklist has been generated yet, so coverage cannot be assessed."];
  }
  const paras: string[] = [];
  const gapPct = Math.round((analytics.gap_total / analytics.expected_total) * 100);

  if (analytics.gap_total === 0) {
    paras.push(
      `Every expected evidence document across ${totalControls} control${totalControls === 1 ? "" : "s"} has a matching uploaded file. Evidence coverage is complete.`,
    );
    return paras;
  }

  paras.push(
    `${analytics.gap_total} of ${analytics.expected_total} expected evidence documents (${gapPct}%) have no matching uploaded file. ` +
      `${analytics.controls_fully_covered} control${analytics.controls_fully_covered === 1 ? " is" : "s are"} fully covered, ` +
      `${analytics.controls_partial} ${analytics.controls_partial === 1 ? "has" : "have"} partial coverage, and ` +
      `${analytics.controls_no_evidence} ${analytics.controls_no_evidence === 1 ? "has" : "have"} no evidence at all.`,
  );

  const declaredGap = analytics.declared_total - analytics.uploaded_total;
  if (declaredGap > 0) {
    paras.push(
      `${declaredGap} document${declaredGap === 1 ? " was" : "s were"} declared by the user but not yet uploaded — ` +
        `that portion of the gap is a collection/upload step, not a missing-evidence finding.`,
    );
  }
  const critical = analytics.gap_by_severity.critical ?? 0;
  const high = analytics.gap_by_severity.high ?? 0;
  if (critical + high > 0) {
    paras.push(
      `${critical + high} control${critical + high === 1 ? "" : "s"} carry a critical or high evidence gap and need ` +
        `additional documentation before the assessment can be concluded.`,
    );
  }
  return paras;
}

export default function EvidencePane({
  result,
  controlIds,
  declared,
  busy,
  onSaveList,
  onRun,
}: EvidencePaneProps) {
  const declaredByControl = useMemo(
    () => new Map(declared.map((d) => [d.control_id, d.items])),
    [declared],
  );
  const perControl = result?.per_control ?? [];
  const stats = result?.stats;
  const rollup = stats?.severity_rollup;
  const analytics = result?.analytics;
  const [openControl, setOpenControl] = useState<string | null>(null);

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Avg Evidence Coverage" value={`${stats.avg_evidence_score}%`} sublabel="Matched vs expected" />
          <MetricCard label="No Evidence" value={stats.controls_without_evidence} tone="red" />
          <MetricCard label="Controls With Gaps" value={stats.evidence_gaps_count} tone="amber" />
          {rollup && (
            <MetricCard
              label="Critical / High"
              value={(rollup.critical ?? 0) + (rollup.high ?? 0)}
              tone="red"
            />
          )}
        </div>
      )}

      {result && (
        <div className="pane-subsection">
          <h4>Evidence Coverage</h4>
          <p className="pane-subsection-note">
            Expected documents come from the engine's checklist for each control. Declared is what the user says
            they hold; covered means a file was actually matched to that document.
          </p>
          <TypedSummary paragraphs={evidenceSummary(analytics, controlIds.length)} />
          {analytics && <EvidenceFunnel analytics={analytics} />}
        </div>
      )}

      {analytics && analytics.status_matrix.length > 0 && (
        <div className="pane-subsection">
          <h4>Control × Evidence Status</h4>
          <p className="pane-subsection-note">Click a row to jump to that control's declared-evidence list below.</p>
          <StatusMatrix
            rows={analytics.status_matrix}
            onSelectControl={(cid) => setOpenControl(cid)}
          />
        </div>
      )}

      <div className="pane-subsection">
        <h4>Declared Evidence By Control</h4>
        <p className="pane-subsection-note">
          Enter the evidence you hold for each control. The engine generates the expected list and reconciles the
          three: expected, declared here, and files actually uploaded.
        </p>
        <div className="collapsible-list">
          {controlIds.map((cid) => {
            const row = perControl.find((r) => r.control_id === cid);
            const items = declaredByControl.get(cid) ?? [];
            return (
              <div
                key={cid}
                ref={(el) => {
                  if (el && openControl === cid) el.scrollIntoView({ behavior: "smooth", block: "center" });
                }}
              >
                <CollapsibleRow
                  // Remounts (via the key) when a status-matrix row asks
                  // this control to open — CollapsibleRow's `open` state is
                  // uncontrolled, so changing `defaultOpen` on an already-
                  // mounted instance would otherwise do nothing.
                  key={openControl === cid ? "open" : "closed"}
                  id={cid}
                  tone={row?.severity ? SEVERITY_TONE[row.severity] : "blue"}
                  summary={
                    row
                      ? `${row.matched.length}/${row.required.length} expected received` +
                        (row.severity ? ` · ${row.severity}` : "")
                      : `${items.length} item(s) declared`
                  }
                  defaultOpen={openControl === cid}
                >
                  <ListEditor
                    controlId={cid}
                    items={items}
                    busy={busy}
                    onSave={(next) => onSaveList(cid, next)}
                  />
                  {row && (
                    <div style={{ marginTop: 14 }}>
                      {row.required.length > 0 && (
                        <p style={{ fontSize: 12.5, margin: "6px 0" }}>
                          <strong>Expected:</strong> {row.required.join(", ")}
                        </p>
                      )}
                      {row.matched.length > 0 && (
                        <p style={{ fontSize: 12.5, margin: "6px 0", color: "var(--pastel-green-ink)" }}>
                          <strong>Received:</strong> {row.matched.join(", ")}
                        </p>
                      )}
                      {row.declared_not_uploaded.length > 0 && (
                        <p style={{ fontSize: 12.5, margin: "6px 0", color: "var(--pastel-amber-ink)" }}>
                          <strong>Declared but not uploaded:</strong> {row.declared_not_uploaded.join(", ")}
                        </p>
                      )}
                      {row.missing.length > 0 && (
                        <p style={{ fontSize: 12.5, margin: "6px 0", color: "var(--pastel-red-ink)" }}>
                          <strong>Missing:</strong> {row.missing.join(", ")}
                        </p>
                      )}
                    </div>
                  )}
                </CollapsibleRow>
              </div>
            );
          })}
        </div>
        <button
          type="button"
          className="kpmg-btn primary"
          style={{ marginTop: 16 }}
          disabled={busy}
          onClick={onRun}
        >
          {busy ? "Running…" : result ? "Re-run evidence assessment" : "Run evidence assessment"}
        </button>
      </div>

      {result?.escalated_gaps && result.escalated_gaps.length > 0 && (
        <div className="pane-subsection">
          <h4>Gaps</h4>
          <div className="gap-card-list">
            {result.escalated_gaps.map((g) => (
              <div key={g.control_id} className="gap-card">
                <span className="gap-card-control-id">{g.control_id}</span>
                <div className="gap-card-body">
                  <p className="gap-card-explanation">{g.explanation}</p>
                </div>
                <StatusBadge label={g.severity} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
