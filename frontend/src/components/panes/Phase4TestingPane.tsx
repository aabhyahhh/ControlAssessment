import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import StatusBadge from "../StatusBadge";
import { useHoverCard } from "../HoverCard";
import type {
  ControlAttributes,
  ControlTestResult,
  Phase4Result,
  RemediationPriority,
  SampleResult,
} from "../../types";

interface Phase4TestingPaneProps {
  result: Phase4Result;
  /** Approved attribute schemas, so the detail table can show each
   *  attribute's name and description rather than its bare id. */
  attributeSchemas?: ControlAttributes[] | null;
}

type Verdict = "effective" | "exceptions" | "ineffective" | "untested";

function verdictKey(status: string): Verdict {
  if (status === "Effective") return "effective";
  if (status === "Effective with Exceptions") return "exceptions";
  if (status === "Not Tested") return "untested";
  return "ineffective";
}

/** Health drives the whole panel's colour. Green for a healthy portfolio,
 *  amber where exceptions dominate, red when effectiveness collapses — the
 *  same three-colour language used for individual verdicts, so the summary
 *  and the details agree. */
function healthTone(pct: number): { key: Verdict; label: string } {
  if (pct >= 0.9) return { key: "effective", label: "Healthy" };
  if (pct >= 0.5) return { key: "exceptions", label: "Exceptions present" };
  return { key: "ineffective", label: "Material concern" };
}

/** Rolls the per-sample failures up into themes. One remediation theme
 *  usually fixes many controls, which is invisible while the failures are
 *  only listed control by control. */
function failureThemes(
  results: ControlTestResult[],
  nameForAttribute: (controlId: string, attrId: string) => string,
): { theme: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of results) {
    for (const s of r.sample_results ?? []) {
      for (const [attrId, verdict] of Object.entries(s.attribute_results ?? {})) {
        if (String(verdict).toLowerCase() !== "no") continue;
        const theme = nameForAttribute(r.control_id, attrId);
        counts.set(theme, (counts.get(theme) ?? 0) + 1);
      }
    }
  }
  return [...counts.entries()]
    .map(([theme, count]) => ({ theme, count }))
    .sort((a, b) => b.count - a.count || a.theme.localeCompare(b.theme));
}

/** Animated count-up for the health figure, so the number arrives with the
 *  ring rather than snapping to its final value. */
function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setValue(target * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);
  return value;
}

/** The health ring. Colour tracks the ANIMATING value so the ring sweeps
 *  through red and amber on its way up — the rating reads from the motion,
 *  not only from the final number. */
function HealthRing({ pct }: { pct: number }) {
  const animated = useCountUp(pct);
  const tone = healthTone(animated);
  // Sized for the horizontal health band — a full-width row rather than a
  // tall column, so the ring stays compact enough not to push the ledger
  // below the fold.
  const size = 152;
  const thickness = 11;
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <div className={`health-ring tone-${tone.key}`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="health-ring-track"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="health-ring-arc"
          strokeWidth={thickness}
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - animated)}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className="health-ring-center">
        <span className="health-ring-value">{Math.round(animated * 100)}%</span>
        <span className="health-ring-caption">effective</span>
      </div>
    </div>
  );
}

/** One control in the ledger. Each dot is a tested sample. */
function LedgerCard({
  row,
  active,
  onClick,
}: {
  row: ControlTestResult;
  active: boolean;
  onClick: () => void;
}) {
  const key = verdictKey(row.effectiveness_status);
  const samples = row.sample_results ?? [];
  const rate = Math.round((row.deviation_rate ?? 0) * 100);

  return (
    <button
      type="button"
      className={`ledger-card tone-${key}${active ? " active" : ""}`}
      onClick={onClick}
      aria-expanded={active}
    >
      <div className="ledger-card-head">
        <span className="ledger-card-id">{row.control_id}</span>
        <span className="ledger-card-dots" aria-hidden="true">
          {samples.length === 0 ? (
            <span className="ledger-dot untested" />
          ) : (
            samples.map((s) => (
              <span
                key={s.sample_id}
                className={`ledger-dot ${s.result === "PASS" ? "pass" : "fail"}`}
              />
            ))
          )}
        </span>
      </div>
      {row.control_title && <span className="ledger-card-title">{row.control_title}</span>}
      <span className="ledger-card-rate">
        {row.effectiveness_status === "Not Tested" ? "NOT TESTED" : `${rate}% DEVIATION`}
      </span>
    </button>
  );
}

/** Attribute-level detail for one control, faded in on click. */
function ControlDetail({
  row,
  attributes,
  onClose,
}: {
  row: ControlTestResult;
  attributes: ControlAttributes | undefined;
  onClose: () => void;
}) {
  const samples = row.sample_results ?? [];
  const key = verdictKey(row.effectiveness_status);

  // Every attribute id seen across the samples, in schema order where a
  // schema exists so the table matches the approved attribute set.
  const attrIds = useMemo(() => {
    const seen = new Set<string>();
    for (const s of samples) for (const id of Object.keys(s.attribute_results ?? {})) seen.add(id);
    const ordered = (attributes?.attributes ?? []).map((a) => a.id).filter((id) => seen.has(id));
    const extras = [...seen].filter((id) => !ordered.includes(id)).sort();
    return [...ordered, ...extras];
  }, [samples, attributes]);

  const metaFor = (id: string) => attributes?.attributes.find((a) => a.id === id);
  const failedCount = attrIds.filter((id) =>
    samples.some((s) => String(s.attribute_results?.[id] ?? "").toLowerCase() === "no"),
  ).length;

  return (
    <div className="control-detail" role="region" aria-label={`${row.control_id} testing detail`}>
      <div className="control-detail-head">
        <span className="control-detail-id">{row.control_id}</span>
        {row.control_title && <span className="control-detail-title">{row.control_title}</span>}
        <StatusBadge label={row.effectiveness_status} />
        {row.deficiency_type && <StatusBadge label={row.deficiency_type} />}
        <button type="button" className="control-detail-close" onClick={onClose} aria-label="Close detail">
          <X size={15} />
        </button>
      </div>

      <div className="control-detail-stats">
        <div>
          <span className="control-detail-stat-label">Attributes tested</span>
          <span className="control-detail-stat-value">{attrIds.length}</span>
        </div>
        <div>
          <span className="control-detail-stat-label">Attributes failed</span>
          <span className={`control-detail-stat-value tone-${key}`}>{failedCount}</span>
        </div>
        <div>
          <span className="control-detail-stat-label">Inherent risk</span>
          <span className="control-detail-stat-value">{row.risk_level || "—"}</span>
        </div>
      </div>

      {attrIds.length === 0 ? (
        <p className="control-detail-empty">
          No attribute-level results were recorded — the evidence could not be evaluated.
        </p>
      ) : (
        <div className="attr-matrix-scroll">
          <table className="attr-matrix">
            <thead>
              <tr>
                <th>Testing attribute</th>
                {samples.map((s) => (
                  <th key={s.sample_id} className="attr-matrix-sample">
                    {s.sample_id}
                  </th>
                ))}
                <th className="attr-matrix-result">Result</th>
              </tr>
            </thead>
            <tbody>
              {attrIds.map((id) => {
                const meta = metaFor(id);
                const fails = samples.filter(
                  (s) => String(s.attribute_results?.[id] ?? "").toLowerCase() === "no",
                ).length;
                return (
                  <tr key={id}>
                    <td className="attr-matrix-name">
                      <span className="attr-matrix-id">{id}</span>
                      <span className="attr-matrix-label">{meta?.name ?? id}</span>
                      {meta?.description && (
                        <span className="attr-matrix-desc">{meta.description}</span>
                      )}
                    </td>
                    {samples.map((s) => {
                      const v = String(s.attribute_results?.[id] ?? "").toLowerCase();
                      const state = v === "no" ? "fail" : v === "yes" ? "pass" : "na";
                      return (
                        <td key={s.sample_id} className="attr-matrix-cell">
                          <span
                            className={`attr-mark ${state}`}
                            title={s.attribute_reasoning?.[id] || undefined}
                          >
                            {state === "fail" ? "✕" : state === "pass" ? "✓" : "–"}
                          </span>
                        </td>
                      );
                    })}
                    <td className={`attr-matrix-result${fails > 0 ? " hot" : ""}`}>
                      {fails} / {samples.length} failed
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <div className="control-detail-notes">
        <div className="control-detail-note why">
          <span className="control-detail-note-title">Why it failed</span>
          <p>
            {row.overall_remarks ||
              (row.effectiveness_status === "Effective"
                ? "Every sample passed every attribute."
                : "The engine recorded no narrative for this verdict.")}
          </p>
        </div>
        <div className="control-detail-note remediate">
          <span className="control-detail-note-title">To remediate</span>
          <p>
            {failedCount === 0
              ? "Nothing outstanding — retain the current evidence discipline."
              : `Address the ${failedCount} failing attribute${failedCount === 1 ? "" : "s"} above, then re-perform testing on a fresh sample selection once one full period has run under the corrected process.`}
          </p>
        </div>
      </div>
    </div>
  );
}

function RemediationQueue({ items }: { items: RemediationPriority[] }) {
  const { show, move, hide, card } = useHoverCard();
  const maxScore = Math.max(...items.map((i) => i.score), 1);

  return (
    <div className="remediation-list">
      {items.map((item) => (
        <div
          key={`${item.control_id}-${item.sample_id}`}
          className={`remediation-item p-${item.priority.toLowerCase()}`}
          onMouseEnter={(e) =>
            show(e, {
              title: `${item.control_id} · ${item.sample_id}`,
              value: item.priority,
              sub: `Remediation score ${item.score}`,
              items: [
                `Control risk level: ${item.risk_level}`,
                item.in_sop
                  ? `SOP coverage: ${item.sop_alignment ?? "covered"}`
                  : "Not described in the SOP",
                `Testing verdict: ${item.verdict}`,
                item.failed_attributes.length
                  ? `Failed attribute(s): ${item.failed_attributes.join(", ")}`
                  : "No attribute-level detail recorded",
              ],
              color: "var(--pastel-red-ink)",
            })
          }
          onMouseMove={move}
          onMouseLeave={hide}
        >
          <span className="remediation-rank">{item.rank}</span>
          <span className={`remediation-priority p-${item.priority.toLowerCase()}`}>{item.priority}</span>
          <div className="remediation-body">
            <div className="remediation-title">
              <strong>{item.control_id}</strong>
              <span className="remediation-sample">{item.sample_id}</span>
              <StatusBadge label={item.risk_level} />
              {item.in_sop && item.sop_alignment && <StatusBadge label={item.sop_alignment} />}
            </div>
            <p className="remediation-why">{item.why}</p>
            {item.remarks && <p className="remediation-remarks">{item.remarks}</p>}
          </div>
          {/* Relative-weight bar: makes the ordering legible as a shape, not
              just a number the reader has to compare row by row. */}
          <div className="remediation-score" aria-hidden="true">
            <div className="remediation-score-fill" style={{ width: `${(item.score / maxScore) * 100}%` }} />
          </div>
        </div>
      ))}
      {card}
    </div>
  );
}

export default function Phase4TestingPane({ result, attributeSchemas }: Phase4TestingPaneProps) {
  const controlResults = result.control_results ?? [];
  const remediation = result.remediation_priorities ?? [];
  const formatIssues = result.format_issues ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  const schemaByControl = useMemo(
    () => new Map((attributeSchemas ?? []).map((s) => [s.control_id, s])),
    [attributeSchemas],
  );

  const nameForAttribute = (controlId: string, attrId: string) =>
    schemaByControl.get(controlId)?.attributes.find((a) => a.id === attrId)?.name ?? attrId;

  const allSamples: SampleResult[] = controlResults.flatMap((r) => r.sample_results ?? []);
  const failedSamples = allSamples.filter((s) => s.result === "FAIL").length;
  const tested = controlResults.filter((r) => r.effectiveness_status !== "Not Tested");
  const effectiveCount = controlResults.filter((r) => r.effectiveness_status === "Effective").length;
  const health = result.overall_health_pct ?? 0;
  const tone = healthTone(health);
  const materialWeaknesses = result.material_weakness_indicators ?? [];

  const deviationRate = allSamples.length ? failedSamples / allSamples.length : 0;
  const themes = failureThemes(controlResults, nameForAttribute);
  const maxTheme = Math.max(...themes.map((t) => t.count), 1);
  const topTwo = themes.slice(0, 2).reduce((sum, t) => sum + t.count, 0);

  const selectedRow = controlResults.find((r) => r.control_id === selected) ?? null;

  return (
    <div className="pane-section">
      {controlResults.length > 0 && (
        <div className="testing-grid">
          {/* ── Control health ── */}
          <div className={`health-card tone-${tone.key}`}>
            <span className="health-card-eyebrow">Control health</span>
            <HealthRing pct={health} />
            <dl className="health-stats">
              <div>
                <dt>Controls tested</dt>
                <dd>{tested.length}</dd>
              </div>
              <div>
                <dt>Samples tested</dt>
                <dd>{allSamples.length}</dd>
              </div>
              <div>
                <dt>Deviation rate</dt>
                <dd>{Math.round(deviationRate * 100)}%</dd>
              </div>
              <div>
                <dt>Effective controls</dt>
                <dd>{effectiveCount}</dd>
              </div>
            </dl>
            {materialWeaknesses.length > 0 && (
              <span className="health-card-flag">
                <span className="health-card-flag-dot" aria-hidden="true" />
                Material weakness ×{materialWeaknesses.length}
              </span>
            )}
          </div>

          {/* ── Sample ledger ── */}
          <div className="ledger-card-panel">
            <div className="ledger-panel-head">
              <div>
                <h4 className="design-card-title">Sample ledger</h4>
                <p className="design-card-sub">
                  Every dot is a tested sample. Click a control for the attribute-level result.
                </p>
              </div>
              <span className={`ledger-panel-tally tone-${tone.key}`}>
                {failedSamples} / {allSamples.length} failed
              </span>
            </div>

            <div className="ledger-grid">
              {controlResults.map((row) => (
                <LedgerCard
                  key={row.control_id}
                  row={row}
                  active={selected === row.control_id}
                  onClick={() => setSelected(selected === row.control_id ? null : row.control_id)}
                />
              ))}
            </div>

            {selectedRow && (
              // Keyed on the control id so switching selection re-mounts the
              // panel and replays the fade — without the key React reuses the
              // node and the new control appears with no transition at all.
              <ControlDetail
                key={selectedRow.control_id}
                row={selectedRow}
                attributes={schemaByControl.get(selectedRow.control_id)}
                onClose={() => setSelected(null)}
              />
            )}
          </div>

          {/* ── Why samples failed ── */}
          {themes.length > 0 && (
            <div className="failure-theme-card">
              <h4 className="design-card-title">Why samples failed</h4>
              <p className="design-card-sub">
                One remediation theme fixes many controls — start at the top.
              </p>
              <div className="failure-theme-list">
                {themes.slice(0, 6).map((t) => (
                  <div key={t.theme} className="failure-theme-row">
                    <span className="failure-theme-label">{t.theme}</span>
                    <div className="failure-theme-track">
                      <div
                        className="failure-theme-fill"
                        style={{ width: `${Math.max((t.count / maxTheme) * 100, 2)}%` }}
                      />
                    </div>
                    <span className="failure-theme-count">{t.count}</span>
                  </div>
                ))}
              </div>
              {themes.length >= 2 && failedSamples > 0 && (
                <div className="failure-theme-callout">
                  <span className="failure-theme-callout-mark" aria-hidden="true">▲</span>
                  <div>
                    <strong>
                      Two fixes clear {topTwo} of {allSamples.length} sample deviations.
                    </strong>
                    <p>
                      {themes[0].theme} and {themes[1].theme} account for most failures. Neither necessarily
                      requires redesigning a control — often only the evidence discipline around it.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {formatIssues.length > 0 && (
        <div className="pane-subsection">
          <h4>Excluded From Testing</h4>
          <p className="pane-subsection-note">
            These controls could not be tested — their evidence isn't organized into samples. They are excluded
            from the verdicts above rather than counted as failures.
          </p>
          <div className="data-table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Control ID</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {formatIssues.map((f) => (
                  <tr key={f.control_id}>
                    <td>{f.control_id}</td>
                    <td className="data-table-reasoning">{f.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {remediation.length > 0 && (
        <div className="pane-subsection">
          <h4>Remediation Priorities</h4>
          <p className="pane-subsection-note">
            Every failed sample, ranked by the control's risk level and whether the SOP documents it — a
            breakdown in a documented, high-risk control outranks the same failure elsewhere. Hover for the
            factors behind each score.
          </p>
          <RemediationQueue items={remediation} />
        </div>
      )}
    </div>
  );
}
