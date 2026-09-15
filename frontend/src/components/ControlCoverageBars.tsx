import { useEffect, useState } from "react";
import { useHoverCard } from "./HoverCard";
import type { EvidenceStatusMatrixRow, Severity } from "../types";

interface ControlCoverageBarsProps {
  rows: EvidenceStatusMatrixRow[];
  severityByControl: Map<string, Severity | null>;
  onSelectControl?: (controlId: string) => void;
}

/**
 * One two-tone bar per control: solid segment is matched (uploaded and
 * attributed to an expected document), pale extension is declared but not
 * yet uploaded. Sorted worst-first so the controls needing the most
 * follow-up lead. Every number comes straight from the engine's own
 * `status_matrix` — no re-derivation of expected/received/missing here.
 */
export default function ControlCoverageBars({ rows, severityByControl, onSelectControl }: ControlCoverageBarsProps) {
  const { show, move, hide, card } = useHoverCard();
  const [grow, setGrow] = useState(0);
  const [hovered, setHovered] = useState<EvidenceStatusMatrixRow | null>(null);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setGrow(1);
      return;
    }
    const id = requestAnimationFrame(() => setGrow(1));
    return () => cancelAnimationFrame(id);
  }, [rows]);

  if (!rows.length) return null;

  const sorted = [...rows].sort((a, b) => {
    const shortfallA = a.expected > 0 ? (a.expected - a.received) / a.expected : 0;
    const shortfallB = b.expected > 0 ? (b.expected - b.received) / b.expected : 0;
    return shortfallB - shortfallA;
  });

  const pinned = hovered ?? sorted[0];
  const severity = pinned ? severityByControl.get(pinned.control_id) : null;

  return (
    <div className="control-coverage-bars">
      {sorted.map((r) => {
        // `received + declared_not_uploaded + missing === expected` always —
        // the engine partitions every required document into exactly one of
        // those three buckets — so `expected` (guarded against 0) is the
        // correct, only-ever-needed denominator.
        const denom = r.expected || 1;
        const matchedPct = (r.received / denom) * grow * 100;
        const declaredPct = (r.declared_not_uploaded / denom) * grow * 100;
        return (
          <button
            type="button"
            key={r.control_id}
            className="control-coverage-row"
            onClick={() => onSelectControl?.(r.control_id)}
            onMouseEnter={(e) => {
              setHovered(r);
              show(e, {
                title: r.control_id,
                value: `${r.received} of ${r.expected} matched`,
                items: [
                  `${r.declared_not_uploaded} declared, not uploaded`,
                  `${r.missing} missing`,
                ],
              });
            }}
            onMouseMove={move}
            onMouseLeave={() => {
              setHovered(null);
              hide();
            }}
          >
            <span className="control-coverage-id">{r.control_id}</span>
            <span className="control-coverage-track">
              <span className="control-coverage-fill matched" style={{ width: `${matchedPct}%` }} />
              <span
                className="control-coverage-fill declared"
                style={{ width: `${declaredPct}%`, left: `${matchedPct}%` }}
              />
            </span>
            <span className="control-coverage-count">
              {r.received}/{r.expected}
            </span>
          </button>
        );
      })}
      {card}
      {pinned && (
        <p className="control-coverage-detail">
          {pinned.control_id} · {pinned.expected} expected, {pinned.received + pinned.declared_not_uploaded} declared,{" "}
          {pinned.received} matched
          {severity ? ` — ${severity}` : ""}
        </p>
      )}
    </div>
  );
}
