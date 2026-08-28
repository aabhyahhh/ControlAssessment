import { Download, Upload } from "lucide-react";
import { useRef } from "react";

interface PhaseActionsBarProps {
  /** Label for what gets downloaded, e.g. "Phase 2 results". */
  downloadLabel: string;
  onDownload: () => void;
  /** Omit to offer download only (phases whose output isn't re-uploadable). */
  onOverride?: (file: File) => void;
  overrideLabel?: string;
  overrideHint?: string;
  busy?: boolean;
}

/**
 * Download / re-upload pair shown at the top of each phase pane, so every
 * step's output can be taken offline, edited, and pushed back without
 * restarting the engagement.
 */
export default function PhaseActionsBar({
  downloadLabel, onDownload, onOverride, overrideLabel, overrideHint, busy,
}: PhaseActionsBarProps) {
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="phase-actions-bar">
      <button className="kpmg-btn ghost attr-btn-sm" disabled={busy} onClick={onDownload}>
        <Download size={14} /> {downloadLabel}
      </button>

      {onOverride && (
        <>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onOverride(file);
              e.target.value = "";
            }}
          />
          <button
            className="kpmg-btn ghost attr-btn-sm"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
            title={overrideHint}
          >
            <Upload size={14} /> {overrideLabel ?? "Upload edits"}
          </button>
        </>
      )}

      {overrideHint && <span className="phase-actions-hint">{overrideHint}</span>}
    </div>
  );
}
