import MetricCard from "../MetricCard";
import RadarChart, { type RadarAxis } from "../RadarChart";
import TimelineChart from "../TimelineChart";
import { useHoverCard } from "../HoverCard";
import type { DeficiencyRow, Phase3Result } from "../../types";

interface Phase3AdequacyPaneProps {
  result: Phase3Result;
  /** Audit period, so the timeline axis spans the period under test rather
   *  than only the dates evidence happens to cover. */
  periodStart?: string | null;
  periodEnd?: string | null;
}

/** The dimensions the adequacy engine scores, in the order they are plotted.
 *  Labels are the phase-3 vocabulary — this is a DESIGN assessment, so the
 *  axes are named for what makes a design adequate, not for RCM columns. */
const DIMENSIONS: { key: string; label: string }[] = [
  { key: "evidence_design", label: "documentation" },
  { key: "ownership", label: "authority" },
  { key: "frequency", label: "frequency" },
  { key: "automation", label: "automation" },
  { key: "exception_management", label: "exception" },
];

/** The engine scores 0-100; the profile is presented out of 5 because a
 *  five-point design rating is what an auditor reads a radar against. */
const SCALE_MAX = 5;

function toFivePoint(score: number): number {
  return Math.round((score / 100) * SCALE_MAX * 10) / 10;
}

/** Portfolio average per dimension, plus how many controls are weak on it.
 *  Falls back to the weak_dimensions name list when a stored result predates
 *  dimension_scores, so an older project still renders a truthful chart. */
function buildProfile(deficiencies: DeficiencyRow[]) {
  const total = deficiencies.length || 1;
  return DIMENSIONS.map(({ key, label }) => {
    const scored = deficiencies.filter((d) => d.dimension_scores?.[key] !== undefined);
    const weakCount = deficiencies.filter((d) => d.weak_dimensions.includes(key)).length;

    const avg100 = scored.length
      ? scored.reduce((sum, d) => sum + (d.dimension_scores![key] ?? 0), 0) / scored.length
      : // No per-dimension scores stored: approximate from the weak share,
        // which is the only signal available. Stated as such in the hover card.
        (1 - weakCount / total) * 100;

    return {
      key,
      label,
      avg: toFivePoint(avg100),
      weakCount,
      estimated: scored.length === 0,
    };
  });
}

export default function Phase3AdequacyPane({ result, periodStart, periodEnd }: Phase3AdequacyPaneProps) {
  const stats = result.stats;
  const deficiencies = result.deficiencies ?? [];
  const alignment = result.control_alignment ?? [];
  const mix = result.control_type_mix;
  const timeline = result.timeline_sufficiency ?? [];
  const { show, move, hide, card } = useHoverCard();

  const profile = buildProfile(deficiencies);
  const totalControls = deficiencies.length;

  // Weakest-first, so the bar list reads as a remediation order.
  const breaks = [...profile].sort((a, b) => b.weakCount - a.weakCount || a.label.localeCompare(b.label));
  const maxWeak = Math.max(...breaks.map((b) => b.weakCount), 1);

  const axes: RadarAxis[] = profile.map((p) => ({
    key: p.key,
    label: p.label,
    value: p.avg / SCALE_MAX,
    display: p.avg.toFixed(1),
    weak: p.weakCount > totalControls / 2,
    detail: [
      `${p.weakCount} of ${totalControls} control${totalControls === 1 ? "" : "s"} flagged weak here`,
      p.estimated
        ? "Estimated from the weak-dimension list — this result predates per-dimension scoring."
        : `Portfolio average ${p.avg.toFixed(1)} out of ${SCALE_MAX}.`,
    ],
  }));

  // The funnel: described in the RCM → survives SOP alignment → clears the
  // design bar. Each tier is counted from the engine's own output.
  const describedCount = alignment.length || totalControls;
  const alignedCount = alignment.filter((a) => a.alignment !== "misaligned").length;
  const adequateCount = stats?.adequate_count ?? deficiencies.filter((d) => d.verdict === "Adequate").length;

  const typeTotal = mix ? mix.preventive + mix.detective + mix.corrective : 0;
  const blindSpot = mix && typeTotal > 0 && (mix.detective === 0 || mix.corrective === 0);

  return (
    <div className="pane-section">
      {stats && (
        <div className="metric-card-row stagger">
          <MetricCard label="Adequate" value={stats.adequate_count} tone="green" />
          <MetricCard label="Partially Adequate" value={stats.partially_adequate_count} tone="amber" />
          <MetricCard label="Inadequate" value={stats.inadequate_count} tone="red" />
          <MetricCard label="Timeline Issues" value={stats.timeline_issues_count} tone="amber" />
        </div>
      )}

      {totalControls > 0 && (
        <div className="design-grid">
          {/* ── Design profile: the shape of the portfolio ── */}
          <div className="design-profile-card">
            <h4 className="design-card-title">Design profile</h4>
            <p className="design-card-sub">Portfolio average per dimension, out of {SCALE_MAX}.</p>
            <RadarChart axes={axes} max={String(SCALE_MAX)} />
            <div className="design-chip-row">
              {profile.map((p) => (
                <span
                  key={p.key}
                  className={`design-chip${p.weakCount > totalControls / 2 ? " weak" : ""}`}
                >
                  {p.label} <strong>{p.avg.toFixed(1)}</strong>
                </span>
              ))}
            </div>
          </div>

          {/* ── Where the design breaks ── */}
          <div className="design-side-card">
            <h4 className="design-card-title">Where the design breaks</h4>
            <p className="design-card-sub">
              Controls flagged weak on each dimension, out of {totalControls}.
            </p>
            <div className="design-break-list">
              {breaks.map((b) => (
                <div
                  key={b.key}
                  className="design-break-row"
                  onMouseEnter={(e) =>
                    show(e, {
                      title: b.label,
                      value: `${b.weakCount} / ${totalControls}`,
                      sub: `Portfolio average ${b.avg.toFixed(1)} / ${SCALE_MAX}`,
                      items: [
                        b.weakCount === 0
                          ? "No control is flagged weak on this dimension."
                          : `${Math.round((b.weakCount / totalControls) * 100)}% of the portfolio is weak here.`,
                        b.weakCount === totalControls
                          ? "Every control fails this dimension — a framework-level gap, not a control-level one."
                          : "Fixing the highest-count dimension first clears the most controls per change.",
                      ],
                      color: b.weakCount > totalControls / 2 ? "var(--pastel-red-ink)" : "var(--pastel-amber-ink)",
                    })
                  }
                  onMouseMove={move}
                  onMouseLeave={hide}
                >
                  <div className="design-break-head">
                    <code className="design-break-label">{b.key}</code>
                    <span
                      className={`design-break-count${b.weakCount > totalControls / 2 ? " hot" : ""}`}
                    >
                      {b.weakCount}
                    </span>
                  </div>
                  <div className="design-break-track">
                    <div
                      className={`design-break-fill${b.weakCount > totalControls / 2 ? " hot" : ""}`}
                      style={{ width: `${Math.max((b.weakCount / maxWeak) * 100, 2)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* ── RCM → SOP → verdict ── */}
          <div className="design-side-card design-funnel-card">
            <h4 className="design-card-title">RCM → SOP → verdict</h4>
            <p className="design-card-sub">
              Where controls fall away between being written down and being adequately designed.
            </p>
            <div className="design-funnel">
              <div className="design-funnel-step tone-blue">
                <span className="design-funnel-count">{describedCount}</span>
                <span className="design-funnel-label">Described in RCM</span>
                <p className="design-funnel-note">Every control has a narrative to test against.</p>
              </div>
              <span className="design-funnel-arrow" aria-hidden="true">→</span>
              <div className="design-funnel-step tone-amber">
                <span className="design-funnel-count">{alignedCount}</span>
                <span className="design-funnel-label">Aligned to SOP</span>
                <p className="design-funnel-note">
                  {alignedCount === describedCount
                    ? "Wording matches in intent, not always in specifics."
                    : `${describedCount - alignedCount} contradict the documented process.`}
                </p>
              </div>
              <span className="design-funnel-arrow" aria-hidden="true">→</span>
              <div className="design-funnel-step tone-red">
                <span className="design-funnel-count">{adequateCount}</span>
                <span className="design-funnel-label">Fully adequate design</span>
                <p className="design-funnel-note">
                  {adequateCount === 0
                    ? "None clears the design bar on paper."
                    : `${adequateCount} clear the design bar on paper.`}
                </p>
              </div>
            </div>

            {blindSpot && (
              <div className="design-blindspot">
                <span className="design-blindspot-mark" aria-hidden="true">!</span>
                <div>
                  <strong>
                    Blind spot: the portfolio is {mix!.preventive} preventive, {mix!.detective} detective,{" "}
                    {mix!.corrective} corrective.
                  </strong>
                  <p>
                    {mix!.detective === 0
                      ? "Nothing in this framework is designed to catch a failure after it happens — which is exactly what effectiveness testing is about to expose."
                      : "No corrective control is designed to put a detected failure right, so detection has nowhere to hand off to."}
                  </p>
                </div>
              </div>
            )}

            {typeTotal > 0 && (
              <>
                <div className="design-mix-bar" aria-hidden="true">
                  {(["preventive", "detective", "corrective"] as const).map((k) =>
                    mix![k] > 0 ? (
                      <div
                        key={k}
                        className={`design-mix-seg ${k}`}
                        style={{ width: `${(mix![k] / typeTotal) * 100}%` }}
                      />
                    ) : null,
                  )}
                </div>
                <div className="design-mix-legend">
                  {(["preventive", "detective", "corrective"] as const).map((k) => (
                    <span key={k} className="design-mix-legend-item">
                      <span className={`design-mix-dot ${k}`} />
                      {k[0].toUpperCase() + k.slice(1)} {mix![k]}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {timeline.length > 0 && (
        <div className="pane-subsection">
          <h4>Timeline Sufficiency</h4>
          <p className="pane-subsection-note">
            Is the evidence collected in Phase 2 spread across the audit period as the control's frequency
            requires? Each bar is that control's evidence span; hover for flags and instance counts.
          </p>
          <TimelineChart rows={timeline} periodStart={periodStart} periodEnd={periodEnd} />
        </div>
      )}
      {card}
    </div>
  );
}
