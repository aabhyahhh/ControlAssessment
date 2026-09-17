import { CheckCircle2, FileText, MessageSquareText, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import BrandLogo from "../components/BrandLogo";
import { ApiError } from "../services/api";
import {
  getJustificationResponseByToken,
  submitJustificationResponseByToken,
} from "../services/justificationService";
import type { JustificationResponseTokenInfo } from "../types";

const FIELD_LABELS: Record<string, string> = {
  control_description: "description",
  control_owner: "owner",
  control_frequency: "frequency",
  control_type: "type",
  control_nature: "nature",
  risk_description: "risk",
  process: "process",
};

/**
 * Public, unauthenticated page a control owner lands on from the link
 * embedded in a justification email — no login, scoped to exactly one
 * reconciliation mismatch via an opaque token. Visually matches the app's
 * own design language (same tokens/spacing as Login.tsx) rather than
 * looking like a bare unstyled form, since this is often a stranger's first
 * impression of the tool.
 */
export default function RespondToJustification() {
  const { token } = useParams<{ token: string }>();
  const [info, setInfo] = useState<JustificationResponseTokenInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [responseText, setResponseText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!token) return;
    getJustificationResponseByToken(token)
      .then((res) => {
        setInfo(res);
        setSubmitted(res.already_responded);
      })
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : "This link is invalid or has expired."))
      .finally(() => setLoading(false));
  }, [token]);

  const handleSubmit = async () => {
    if (!token) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const res = await submitJustificationResponseByToken(token, responseText, file);
      setInfo(res);
      setSubmitted(true);
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Failed to submit your response. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="respond-page">
      <div className="respond-card">
        <div className="respond-brand">
          <BrandLogo height={26} />
        </div>

        <div className="respond-icon-badge">
          <ShieldCheck size={26} />
        </div>

        {loading ? (
          <p className="respond-loading">Loading…</p>
        ) : loadError || !info ? (
          <>
            <h1>Link not found</h1>
            <p className="respond-subtitle">{loadError ?? "This link is invalid or has expired."}</p>
          </>
        ) : (
          <>
            <h1>Justification Requested</h1>
            <p className="respond-subtitle">
              A control reconciliation mismatch needs your input before this assessment can be concluded.
            </p>

            <div className="respond-mismatch">
              <span className="respond-mismatch-control">{info.control_id}</span>
              {info.field && <span className="respond-mismatch-field">{FIELD_LABELS[info.field] ?? info.field}</span>}
              <p className="respond-mismatch-desc">{info.mismatch_description}</p>
            </div>

            {submitted ? (
              <div className="respond-success">
                <CheckCircle2 size={40} />
                <h2>Thank you — your response was received</h2>
                <p>The audit team has been notified and will review it shortly.</p>
                {info.response_text && (
                  <div className="respond-success-detail">
                    <MessageSquareText size={15} />
                    <span>{info.response_text}</span>
                  </div>
                )}
                {info.response_attachment_name && (
                  <div className="respond-success-detail">
                    <FileText size={15} />
                    <span>{info.response_attachment_name}</span>
                  </div>
                )}
              </div>
            ) : (
              <form
                className="respond-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void handleSubmit();
                }}
              >
                <label>
                  Your justification
                  <textarea
                    rows={5}
                    placeholder="Explain the discrepancy, confirm the correct value, or note any corrective action…"
                    value={responseText}
                    onChange={(e) => setResponseText(e.target.value)}
                    autoFocus
                  />
                </label>
                <label>
                  Attach supporting evidence (optional)
                  <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </label>
                {submitError && <span className="form-error">{submitError}</span>}
                <button
                  type="submit"
                  className="kpmg-btn primary block"
                  disabled={submitting || (!responseText.trim() && !file)}
                >
                  {submitting ? "Submitting…" : "Submit Response"}
                </button>
              </form>
            )}
          </>
        )}
      </div>
    </div>
  );
}
