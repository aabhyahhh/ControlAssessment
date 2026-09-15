import { useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import {
  analyzeJustificationItem,
  sendJustificationEmail,
  uploadJustificationResponse,
} from "../services/justificationService";
import type { JustificationEmail, ReconciliationRow } from "../types";

export interface JustificationMismatch {
  control_id: string;
  field: string;
  rcm_value: string;
  doc_value: string;
}

interface JustificationEmailPanelProps {
  projectId: string;
  reconciliation: ReconciliationRow[];
  emails: JustificationEmail[];
  onEmailsChange: (emails: JustificationEmail[]) => void;
}

const RECON_FIELD_LABELS: Record<string, string> = {
  control_description: "description",
  control_owner: "owner",
  control_frequency: "frequency",
  control_type: "type",
  control_nature: "nature",
  risk_description: "risk",
  process: "process",
};

function allMismatches(reconciliation: ReconciliationRow[]): JustificationMismatch[] {
  const out: JustificationMismatch[] = [];
  for (const r of reconciliation) {
    for (const [field, cell] of Object.entries(r.fields || {})) {
      if (cell.status === "contradicted") {
        out.push({ control_id: r.control_id, field, rcm_value: cell.rcm_value, doc_value: cell.doc_value });
      }
    }
  }
  return out;
}

function defaultSubject(items: JustificationMismatch[]): string {
  const ids = Array.from(new Set(items.map((i) => i.control_id)));
  return `Justification requested — ${ids.join(", ")}`;
}

function defaultBody(items: JustificationMismatch[]): string {
  const lines = items.map(
    (i) =>
      `- ${i.control_id} · ${RECON_FIELD_LABELS[i.field] ?? i.field}: our records show "${i.rcm_value || "(blank)"}", ` +
      `but the SOP/workpapers indicate "${i.doc_value || "(not stated)"}". Could you confirm which is correct, or explain the discrepancy?`,
  );
  return (
    `Hello,\n\nWhile reconciling our control documentation, we found the following discrepancies that need your ` +
    `input:\n\n${lines.join("\n")}\n\nPlease reply with your explanation at your earliest convenience.\n\nThank you.`
  );
}

function ComposeModal({
  projectId,
  items,
  onClose,
  onSent,
}: {
  projectId: string;
  items: JustificationMismatch[];
  onClose: () => void;
  onSent: (email: JustificationEmail) => void;
}) {
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState(() => defaultSubject(items));
  const [body, setBody] = useState(() => defaultBody(items));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSend = async () => {
    setBusy(true);
    setError(null);
    try {
      const email = await sendJustificationEmail(projectId, {
        recipient_email: recipient,
        subject,
        body,
        items: items.map((i) => ({
          control_id: i.control_id,
          field: i.field,
          mismatch_description: `${RECON_FIELD_LABELS[i.field] ?? i.field}: RCM says "${i.rcm_value || "(blank)"}", docs say "${i.doc_value || "(not stated)"}"`,
        })),
      });
      onSent(email);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send email.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card wide" onClick={(e) => e.stopPropagation()}>
        <h4 style={{ marginTop: 0 }}>Send Justification Email</h4>
        <p className="pane-subsection-note">
          Covers {items.length} mismatch{items.length === 1 ? "" : "es"} across{" "}
          {new Set(items.map((i) => i.control_id)).size} control{new Set(items.map((i) => i.control_id)).size === 1 ? "" : "s"}.
        </p>
        <label className="modal-field">
          <span>Control owner email</span>
          <input
            type="email"
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
            placeholder="owner@company.com"
            required
          />
        </label>
        <label className="modal-field">
          <span>Subject</span>
          <input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="modal-field">
          <span>Body</span>
          <textarea rows={8} value={body} onChange={(e) => setBody(e.target.value)} />
        </label>
        {error && <p style={{ color: "var(--pastel-red-ink)" }}>{error}</p>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
          <button type="button" className="kpmg-btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className="kpmg-btn primary"
            onClick={handleSend}
            disabled={busy || !recipient.trim()}
          >
            {busy ? "Sending…" : "Send"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ResponseRow({
  projectId,
  email,
  onUpdated,
}: {
  projectId: string;
  email: JustificationEmail;
  onUpdated: (email: JustificationEmail) => void;
}) {
  return (
    <div className="justification-email-card">
      <div className="justification-email-head">
        <span>{email.recipient_email}</span>
        <StatusBadge label={email.send_status === "failed" ? "failed" : "sent"} />
        <span style={{ color: "var(--muted)", fontSize: 11.5 }}>{new Date(email.sent_at).toLocaleString()}</span>
      </div>
      {email.error_message && <p style={{ color: "var(--pastel-red-ink)", fontSize: 12 }}>{email.error_message}</p>}
      <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
        {email.items.map((item) => (
          <JustificationItemRow
            key={item.id}
            projectId={projectId}
            item={item}
            onUpdated={(updated) =>
              onUpdated({
                ...email,
                items: email.items.map((i) => (i.id === updated.id ? updated : i)),
              })
            }
          />
        ))}
      </div>
    </div>
  );
}

function JustificationItemRow({
  projectId,
  item,
  onUpdated,
}: {
  projectId: string;
  item: JustificationEmail["items"][number];
  onUpdated: (item: JustificationEmail["items"][number]) => void;
}) {
  const [responseText, setResponseText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await uploadJustificationResponse(projectId, item.id, responseText, file);
      onUpdated(updated);
      setResponseText("");
      setFile(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to upload response.");
    } finally {
      setBusy(false);
    }
  };

  const handleAnalyze = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await analyzeJustificationItem(projectId, item.id);
      onUpdated(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to analyze response.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="justification-item-row">
      <div className="justification-item-head">
        <strong>{item.control_id}</strong>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>{item.mismatch_description}</span>
      </div>
      {item.analysis_verdict && (
        <div style={{ marginTop: 6 }}>
          <StatusBadge label={item.analysis_verdict.replace(/_/g, " ")} />
          {item.analysis_reasoning && (
            <p style={{ fontSize: 12, color: "var(--muted)", margin: "4px 0 0" }}>{item.analysis_reasoning}</p>
          )}
        </div>
      )}
      {!item.response_uploaded_at ? (
        <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
          <textarea
            rows={2}
            placeholder="Paste the owner's reply here…"
            value={responseText}
            onChange={(e) => setResponseText(e.target.value)}
          />
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button
              type="button"
              className="kpmg-btn"
              disabled={busy || (!responseText.trim() && !file)}
              onClick={handleUpload}
            >
              {busy ? "Uploading…" : "Upload response"}
            </button>
          </div>
        </div>
      ) : (
        !item.analysis_verdict && (
          <button type="button" className="kpmg-btn" disabled={busy} onClick={handleAnalyze} style={{ marginTop: 8 }}>
            {busy ? "Analyzing…" : "Analyze response"}
          </button>
        )
      )}
      {error && <p style={{ color: "var(--pastel-red-ink)", fontSize: 12 }}>{error}</p>}
    </div>
  );
}

/**
 * Send-and-track UI for Step 2's justification-email workflow: a control
 * owner is asked to justify an RCM<->documentation contradiction, and their
 * reply (manually uploaded — no inbox integration) is judged by the LLM
 * against that specific mismatch.
 */
export default function JustificationEmailPanel({
  projectId,
  reconciliation,
  emails,
  onEmailsChange,
}: JustificationEmailPanelProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [composeItems, setComposeItems] = useState<JustificationMismatch[] | null>(null);

  const mismatches = useMemo(() => allMismatches(reconciliation), [reconciliation]);
  const key = (m: JustificationMismatch) => `${m.control_id}::${m.field}`;

  if (!mismatches.length) return null;

  const toggle = (k: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const selectedMismatches = mismatches.filter((m) => selected.has(key(m)));

  return (
    <div className="pane-subsection">
      <h4>Request Justification From Control Owners</h4>
      <p className="pane-subsection-note">
        Select one or more contradicted fields and send an email asking the control owner to justify the
        discrepancy — either one at a time, or batched across several controls at once.
      </p>
      <div style={{ display: "grid", gap: 6 }}>
        {mismatches.map((m) => (
          <label key={key(m)} className="justification-mismatch-row">
            <input type="checkbox" checked={selected.has(key(m))} onChange={() => toggle(key(m))} />
            <span>
              <strong>{m.control_id}</strong> · {RECON_FIELD_LABELS[m.field] ?? m.field}: RCM says "
              {m.rcm_value || "(blank)"}", docs say "{m.doc_value || "(not stated)"}"
            </span>
            <button type="button" className="kpmg-btn" onClick={() => setComposeItems([m])}>
              Send
            </button>
          </label>
        ))}
      </div>
      {selectedMismatches.length > 0 && (
        <button
          type="button"
          className="kpmg-btn primary"
          style={{ marginTop: 10 }}
          onClick={() => setComposeItems(selectedMismatches)}
        >
          Send batch email for {selectedMismatches.length} selected
        </button>
      )}

      {composeItems && (
        <ComposeModal
          projectId={projectId}
          items={composeItems}
          onClose={() => setComposeItems(null)}
          onSent={(email) => {
            onEmailsChange([email, ...emails]);
            setSelected(new Set());
          }}
        />
      )}

      {emails.length > 0 && (
        <details className="pane-disclosure" style={{ marginTop: 14 }}>
          <summary>View sent justification emails and responses ({emails.length})</summary>
          <div className="pane-subsection" style={{ marginTop: 12, display: "grid", gap: 10 }}>
            {emails.map((email) => (
              <ResponseRow
                key={email.id}
                projectId={projectId}
                email={email}
                onUpdated={(updated) => onEmailsChange(emails.map((e) => (e.id === updated.id ? updated : e)))}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}
