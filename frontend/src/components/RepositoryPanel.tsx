import { Download, FileSpreadsheet } from "lucide-react";
import type { Artifact } from "../types";

interface RepositoryPanelProps {
  artifacts: Artifact[];
  busy?: boolean;
  canExportFinalReport: boolean;
  onExportFinalReport: () => void;
  onDownload: (artifact: Artifact) => void;
}

const TYPE_LABELS: Record<string, string> = {
  final_report: "Gap assessment report",
  rcm: "Working RCM",
  phase1: "Step 1 — RCM intake",
  phase2: "Step 2 — Adequacy",
  phase3: "Step 3 — Evidence",
  phase4: "Step 4 — Gap assessment",
};

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString();
}

export default function RepositoryPanel({
  artifacts, busy, canExportFinalReport, onExportFinalReport, onDownload,
}: RepositoryPanelProps) {
  return (
    <div className="pane-section">
      <div className="pane-section-header">
        <h3>Reports &amp; Exports</h3>
        <p>
          Generate the gap-assessment Excel from this engagement. Every export is kept here, so earlier versions
          stay downloadable.
        </p>
      </div>

      <div className="attr-pane-actions" style={{ marginTop: 0 }}>
        <button
          className="kpmg-btn primary"
          disabled={busy || !canExportFinalReport}
          title={
            canExportFinalReport
              ? "Multi-sheet gap-assessment summary covering all four steps"
              : "Load an RCM first — the report is built from the control universe"
          }
          onClick={onExportFinalReport}
        >
          {busy ? "Working…" : "Export Gap Assessment"}
        </button>
      </div>

      <div className="pane-subsection">
        <h4>Generated Files</h4>
        {artifacts.length === 0 ? (
          <p style={{ color: "var(--muted)", fontSize: 12.5, margin: 0 }}>
            Nothing exported yet.
          </p>
        ) : (
          <div className="artifact-list">
            {artifacts.map((a) => (
              <div key={a.id} className="artifact-row">
                <FileSpreadsheet size={16} className="artifact-icon" />
                <div className="artifact-meta">
                  <span className="artifact-name">{a.filename}</span>
                  <span className="artifact-sub">
                    {TYPE_LABELS[a.artifact_type ?? ""] ?? a.artifact_type ?? "Export"} · {formatWhen(a.created_at)}
                  </span>
                </div>
                <button
                  className="kpmg-btn ghost attr-btn-sm"
                  onClick={() => onDownload(a)}
                  title={`Download ${a.filename}`}
                >
                  <Download size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
