import { useEffect, useMemo, useRef, useState } from "react";
import { Mail, Paperclip, Plus, Trash2 } from "lucide-react";
import MetricCard from "../MetricCard";
import StatusBadge from "../StatusBadge";
import CollapsibleRow from "../CollapsibleRow";
import AttritionFunnel from "../AttritionFunnel";
import ControlCoverageBars from "../ControlCoverageBars";
import StepFooterNote from "../StepFooterNote";
import TypedSummary from "../TypedSummary";
import type {
  ControlEvidenceCategories,
  DeclaredEvidence,
  DeclaredEvidenceItem,
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
  /** Attach a file (any format — a document, an exported email, etc.)
   *  directly to a control's evidence, outside the declared-list text
   *  entries. */
  onAttachFile: (controlId: string, file: File) => void | Promise<void>;
  onRun: () => void;
}

const SEVERITY_TONE: Record<Severity, "red" | "amber" | "blue"> = {
  critical: "red",
  high: "red",
  medium: "amber",
  low: "blue",
};

/** Editable per-control declared-evidence list, plus a shortcut to attach a
 *  file (any format — a document, an exported email, etc.) directly to this
 *  control's evidence without going through the full folder-upload flow. */
function ListEditor({
  controlId,
  items,
  busy,
  onSave,
  onAttachFile,
}: {
  controlId: string;
  items: DeclaredEvidenceItem[];
  busy?: boolean;
  onSave: (items: DeclaredEvidenceItem[]) => void;
  onAttachFile: (controlId: string, file: File) => void | Promise<void>;
}) {
  const [draft, setDraft] = useState<DeclaredEvidenceItem[]>(items);
  const [newName, setNewName] = useState("");
  const [attaching, setAttaching] = useState(false);
  const [attachedName, setAttachedName] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  useEffect(() => setDraft(items), [items]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(items);

  const handleFileChosen = async (file: File | undefined) => {
    if (!file) return;
    setAttaching(true);
    try {
      await onAttachFile(controlId, file);
      setAttachedName(file.name);
    } finally {
      setAttaching(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

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
          title="Add as a text item"
          onClick={() => {
            setDraft((d) => [...d, { name: newName.trim() }]);
            setNewName("");
          }}
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          className="kpmg-btn ghost attr-btn-sm"
          disabled={attaching}
          title="Attach a file or email export to this control's evidence"
          onClick={() => fileInputRef.current?.click()}
        >
          {attaching ? "…" : <Paperclip size={14} />}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          style={{ display: "none" }}
          onChange={(e) => void handleFileChosen(e.target.files?.[0])}
        />
      </div>
      {attachedName && (
        <p className="evidence-attach-confirm">
          <Mail size={12} /> Attached "{attachedName}" — re-run the evidence assessment to include it.
        </p>
      )}
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

/** EXPECTED -> DECLARED -> UPLOADED/MATCHED, at the document level across
 *  the whole portfolio. Every stage is a strict subset of the one before it
 *  (enforced by the engine, not recomputed here). Stops at 3 stages: the
 *  engine's own matching (`_fuzzy_covers`) can match one uploaded file to
 *  more than one expected document, so "files uploaded" and "documents
 *  matched" aren't reliably distinct counts — a 4th stage there would risk
 *  a negative or double-counted delta, so it isn't built. */
function EvidenceFunnel({ analytics }: { analytics: Phase3Analytics }) {
  if (analytics.expected_total === 0) return null;
  const declaredGap = analytics.expected_total - analytics.declared_total;
  const uploadedGap = analytics.declared_total - analytics.uploaded_total;
  return (
    <AttritionFunnel
      total={analytics.expected_total}
      stages={[
        { label: "Expected by the engine", count: analytics.expected_total },
        {
          label: "Declared by the client",
          count: analytics.declared_total,
          deltaNote: declaredGap > 0 ? `−${declaredGap} never named on the evidence list` : undefined,
        },
        {
          label: "Matched to an expected doc",
          count: analytics.uploaded_total,
          deltaNote: uploadedGap > 0 ? `−${uploadedGap} named but no file attached` : undefined,
        },
      ]}
    />
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

/**
 * Per-control reconciliation between step 3's evidence collection and step
 * 2's RCM<->documentation contradictions, as three enterprise action
 * pointers rather than raw expected/received/missing labels. A contradicted
 * field already resolved by a 'justified' email response doesn't appear
 * here at all — it's been folded back into "reconciled".
 */
function EvidenceCategoryDetail({ categories }: { categories: ControlEvidenceCategories | undefined }) {
  if (!categories) return null;
  const { reconciled_from_sop_and_workpaper, contradicted_in_sop_or_workpaper, missing_from_evidence_folder } =
    categories;
  return (
    <>
      {reconciled_from_sop_and_workpaper.length > 0 && (
        <p style={{ fontSize: 12.5, margin: "6px 0", color: "var(--pastel-green-ink)" }}>
          <strong>Reconciled from SOP and workpaper:</strong> {reconciled_from_sop_and_workpaper.join(", ")}
        </p>
      )}
      {contradicted_in_sop_or_workpaper.map((f) => (
        <p key={f.field} style={{ fontSize: 12.5, margin: "6px 0", color: "var(--pastel-red-ink)" }}>
          <strong>Contradicted in SOP/workpaper: {f.field.replace(/_/g, " ")}</strong> — RCM says "
          {f.rcm_value || "(blank)"}", docs say "{f.doc_value || "(not stated)"}".{" "}
          <span style={{ color: "var(--muted)" }}>Status: {f.justification_status}.</span>
        </p>
      ))}
      {missing_from_evidence_folder.length > 0 && (
        <p style={{ fontSize: 12.5, margin: "6px 0", color: "var(--pastel-amber-ink)" }}>
          <strong>Mentioned in workpaper/SOP but missing from evidence folder:</strong>{" "}
          {missing_from_evidence_folder.join(", ")}
        </p>
      )}
    </>
  );
}

export default function EvidencePane({
  result,
  controlIds,
  declared,
  busy,
  onSaveList,
  onAttachFile,
  onRun,
}: EvidencePaneProps) {
  const declaredByControl = useMemo(
    () => new Map(declared.map((d) => [d.control_id, d.items])),
    [declared],
  );
  const perControl = result?.per_control ?? [];
  const evidenceCategoriesByControl = useMemo(
    () => new Map((result?.control_evidence_categories ?? []).map((c) => [c.control_id, c])),
    [result?.control_evidence_categories],
  );
  const stats = result?.stats;
  const rollup = stats?.severity_rollup;
  const analytics = result?.analytics;
  const [openControl, setOpenControl] = useState<string | null>(null);

  const severityByControl = useMemo(
    () => new Map(perControl.map((r) => [r.control_id, r.severity])),
    [perControl],
  );
  const neverDeclared = analytics ? analytics.expected_total - analytics.declared_total : 0;

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard
            label="Evidence Matched"
            value={`${stats.avg_evidence_score}%`}
            sublabel={analytics ? `${analytics.uploaded_total} of ${analytics.expected_total} documents` : undefined}
          />
          <MetricCard
            label="No Evidence At All"
            value={stats.controls_without_evidence}
            tone="red"
            sublabel="Nothing declared or uploaded"
          />
          <MetricCard
            label="Never Declared"
            value={neverDeclared}
            tone="amber"
            sublabel="Expected, not on the list"
          />
        </div>
      )}

      {result && (
        <div className="pane-subsection">
          <h4>Evidence Attrition</h4>
          <p className="pane-subsection-note">
            Every expected document followed through the chain. Each drop is a different conversation with the
            client — the widest one is where to push first.
          </p>
          <TypedSummary paragraphs={evidenceSummary(analytics, controlIds.length)} />
          {analytics && <EvidenceFunnel analytics={analytics} />}
        </div>
      )}

      {analytics && analytics.status_matrix.length > 0 && (
        <div className="pane-subsection">
          <h4>Coverage By Control</h4>
          <p className="pane-subsection-note">
            Sorted by shortfall. Solid is matched to a real file; the pale extension is declared but still
            unattached. Click a row to jump to that control's declared-evidence list below.
          </p>
          <ControlCoverageBars
            rows={analytics.status_matrix}
            severityByControl={severityByControl}
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
            const categories = evidenceCategoriesByControl.get(cid);
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
                    onAttachFile={onAttachFile}
                  />
                  {row && (
                    <div style={{ marginTop: 14 }}>
                      <EvidenceCategoryDetail categories={categories} />
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

      <StepFooterNote text="Every figure derives from project state at render time — control count, period length and document counts drive the geometry. Nothing is fixed in the markup." />
    </div>
  );
}
