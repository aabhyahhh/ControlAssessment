import { useState } from "react";
import StatusBadge from "../StatusBadge";
import type { ControlAttributes } from "../../types";

interface AttributePreviewPaneProps {
  schemas: ControlAttributes[];
  busy?: boolean;
  onApprove: () => void;
  onModify: (controlId: string, attributeNo: number, body: { name?: string; description?: string }) => void;
  onRemove: (controlId: string, attributeNo: number) => void;
  onRegenerate?: () => void;
  /** Control IDs that already have test results — those are truly frozen,
   *  because the results are keyed to their attribute IDs. Approval alone
   *  does not freeze a schema (see routes/attributes._require_mutable_row). */
  testedControlIds?: string[];
}

export default function AttributePreviewPane({
  schemas, busy, onApprove, onModify, onRemove, onRegenerate, testedControlIds = [],
}: AttributePreviewPaneProps) {
  const tested = new Set(testedControlIds);
  const [expanded, setExpanded] = useState<string | null>(schemas[0]?.control_id ?? null);
  const [editing, setEditing] = useState<{ controlId: string; no: number } | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");

  const allApproved = schemas.length > 0 && schemas.every((s) => s.status === "approved");
  const totalIssues = schemas.reduce((n, s) => n + s.quality_issues.length, 0);

  return (
    <div className="pane-section">
      <div className="pane-section-header">
        <h3>Testing Attributes — Review Before Testing</h3>
        <p>
          These are the Yes/No conditions each sample will be tested against. Review and edit them now — once
          approved they're frozen, because test results are keyed to these attribute IDs.
        </p>
      </div>

      {totalIssues > 0 && (
        <div className="quality-warning-banner">
          {totalIssues} unresolved quality {totalIssues === 1 ? "finding" : "findings"} across{" "}
          {schemas.filter((s) => s.quality_issues.length > 0).length} control(s). You can still approve — just be
          aware of what's flagged.
        </div>
      )}

      {schemas.map((schema) => {
        const isOpen = expanded === schema.control_id;
        const frozen = tested.has(schema.control_id);
        return (
          <div key={schema.control_id} className="attr-control-card">
            <button
              type="button"
              className="attr-control-head"
              onClick={() => setExpanded(isOpen ? null : schema.control_id)}
            >
              <span className="attr-control-id">{schema.control_id}</span>
              <StatusBadge label={frozen ? "tested" : schema.status} />
              <span className="attr-control-count">{schema.attributes.length} attributes</span>
              {schema.quality_issues.length > 0 && (
                <StatusBadge label={`${schema.quality_issues.length} issue(s)`} variant="amber" />
              )}
              <span className="attr-control-chevron">{isOpen ? "−" : "+"}</span>
            </button>

            {isOpen && (
              <div className="attr-control-body">
                {schema.quality_issues.length > 0 && (
                  <ul className="attr-issue-list">
                    {schema.quality_issues.map((issue, i) => (
                      <li key={i}>{issue}</li>
                    ))}
                  </ul>
                )}

                {schema.worksteps.length > 0 && (
                  <>
                    <h5>Worksteps</h5>
                    <ol className="attr-workstep-list">
                      {schema.worksteps.map((w, i) => (
                        <li key={i}>{w.replace(/^\d+\.\s*/, "")}</li>
                      ))}
                    </ol>
                  </>
                )}

                <h5>Attributes</h5>
                <div className="data-table-scroll">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Name</th>
                        <th>Description</th>
                        {!frozen && <th />}
                      </tr>
                    </thead>
                    <tbody>
                      {schema.attributes.map((attr, idx) => {
                        const no = idx + 1;
                        const isEditing = editing?.controlId === schema.control_id && editing.no === no;
                        return (
                          <tr key={attr.id}>
                            <td>{attr.id}</td>
                            {isEditing ? (
                              <>
                                <td>
                                  <input
                                    className="field-input"
                                    value={draftName}
                                    onChange={(e) => setDraftName(e.target.value)}
                                  />
                                </td>
                                <td>
                                  <textarea
                                    className="field-input"
                                    rows={3}
                                    value={draftDescription}
                                    onChange={(e) => setDraftDescription(e.target.value)}
                                  />
                                </td>
                                <td>
                                  <button
                                    className="kpmg-btn primary attr-btn-sm"
                                    disabled={busy}
                                    onClick={() => {
                                      onModify(schema.control_id, no, {
                                        name: draftName,
                                        description: draftDescription,
                                      });
                                      setEditing(null);
                                    }}
                                  >
                                    Save
                                  </button>
                                  <button className="kpmg-btn ghost attr-btn-sm" onClick={() => setEditing(null)}>
                                    Cancel
                                  </button>
                                </td>
                              </>
                            ) : (
                              <>
                                <td>{attr.name}</td>
                                <td className="data-table-reasoning">{attr.description}</td>
                                {!frozen && (
                                  <td className="attr-actions">
                                    <button
                                      className="kpmg-btn ghost attr-btn-sm"
                                      disabled={busy}
                                      onClick={() => {
                                        setEditing({ controlId: schema.control_id, no });
                                        setDraftName(attr.name);
                                        setDraftDescription(attr.description);
                                      }}
                                    >
                                      Edit
                                    </button>
                                    <button
                                      className="kpmg-btn ghost attr-btn-sm"
                                      disabled={busy || schema.attributes.length <= 1}
                                      title={
                                        schema.attributes.length <= 1
                                          ? "A control needs at least one testable condition"
                                          : "Remove this attribute"
                                      }
                                      onClick={() => onRemove(schema.control_id, no)}
                                    >
                                      Remove
                                    </button>
                                  </td>
                                )}
                              </>
                            )}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {schema.sample_columns.length > 0 && (
                  <>
                    <h5>Sample Columns</h5>
                    <p className="attr-sample-cols">{schema.sample_columns.map((c) => c.header).join(" · ")}</p>
                  </>
                )}
              </div>
            )}
          </div>
        );
      })}

      <div className="attr-pane-actions">
        {!allApproved && (
          <button className="kpmg-btn primary" disabled={busy} onClick={onApprove}>
            {busy ? "Working…" : "Approve Attributes & Run Testing"}
          </button>
        )}
        {/* Always available: once every schema is approved the backend
            freezes them (409 on mutation), so without this the user would
            have no way forward if testing failed after approval. */}
        {onRegenerate && (
          <button className="kpmg-btn ghost" disabled={busy} onClick={onRegenerate}>
            {allApproved ? "Regenerate Attributes" : "Regenerate All"}
          </button>
        )}
      </div>
      {allApproved && (
        <p className="attr-frozen-note">
          These attributes are approved and frozen — test results are keyed to their IDs. Regenerating replaces
          the schemas for any control that hasn't been tested yet.
        </p>
      )}
    </div>
  );
}
