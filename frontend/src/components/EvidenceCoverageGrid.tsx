import { useMemo } from "react";
import { useHoverCard } from "./HoverCard";

/**
 * Every expected document for every control, as a matrix. A filled cell means
 * the document was matched in the uploaded evidence; a hollow one means it was
 * expected and never arrived.
 *
 * The columns are DERIVED, not fixed. Required documents are free text
 * generated per control and their count varies (3 for one control, 6 for
 * another), so a hardcoded column list would either drop real documents or
 * invent empty ones. Instead each document is classified into a stable
 * category from its own wording, and only the categories actually present in
 * this engagement become columns.
 */

interface EvidenceCoverageGridProps {
  /** control_id -> the documents the engine expected for it. */
  requiredDocuments: Record<string, string[]>;
  /** control_id -> the subset that never arrived. */
  missingByControl: Map<string, string[]>;
  /** control_id -> matched percentage, as scored by the engine. */
  scoreByControl: Map<string, number>;
  /** Controls that escalated, so their row label can carry the signal. */
  escalatedControls: Set<string>;
}

/** Ordered so the columns read in the sequence an auditor would collect them.
 *  Each entry's `test` runs against the document's own text. */
const CATEGORIES: { key: string; label: string; test: RegExp }[] = [
  { key: "policy", label: "SOP", test: /polic|procedure|sop\b|manual|guideline|matrix|authority/i },
  { key: "exec", label: "Exec log", test: /log\b|listing|report|export|extract|screenshot|system-generated|ticket/i },
  { key: "signoff", label: "Sign-off", test: /sign-?off|approv|authoriz|review|initial|signature|email/i },
  { key: "source", label: "Source", test: /invoice|statement|contract|agreement|voucher|receipt|purchase order|\bpo\b|grn/i },
  { key: "recon", label: "Recon", test: /reconcil|tie-?out|worksheet|workpaper|calculat|schedule|spreadsheet/i },
  { key: "exception", label: "Exception", test: /exception|variance|discrepan|deviation|error|escalat|resolution/i },
];
const OTHER = { key: "other", label: "Other", test: /.^/ };

function categorise(doc: string): string {
  for (const c of CATEGORIES) if (c.test.test(doc)) return c.key;
  return OTHER.key;
}

type CellState = "received" | "partial" | "missing" | "na";

export default function EvidenceCoverageGrid({
  requiredDocuments,
  missingByControl,
  scoreByControl,
  escalatedControls,
}: EvidenceCoverageGridProps) {
  const { show, move, hide, card } = useHoverCard();

  const { columns, rows } = useMemo(() => {
    const controlIds = Object.keys(requiredDocuments).sort();

    // Bucket each control's documents by category, splitting matched from
    // missing using the engine's own missing list.
    const perControl = new Map<string, Map<string, { received: string[]; missing: string[] }>>();
    const usedCategories = new Set<string>();

    for (const cid of controlIds) {
      const missing = new Set(missingByControl.get(cid) ?? []);
      const buckets = new Map<string, { received: string[]; missing: string[] }>();
      for (const doc of requiredDocuments[cid] ?? []) {
        const key = categorise(doc);
        usedCategories.add(key);
        const bucket = buckets.get(key) ?? { received: [], missing: [] };
        (missing.has(doc) ? bucket.missing : bucket.received).push(doc);
        buckets.set(key, bucket);
      }
      perControl.set(cid, buckets);
    }

    const cols = [...CATEGORIES, OTHER].filter((c) => usedCategories.has(c.key));

    const builtRows = controlIds.map((cid) => {
      const buckets = perControl.get(cid) ?? new Map();
      const expected = (requiredDocuments[cid] ?? []).length;
      const missingCount = (missingByControl.get(cid) ?? []).length;
      return {
        controlId: cid,
        score: scoreByControl.get(cid),
        escalated: escalatedControls.has(cid),
        expected,
        receivedCount: expected - missingCount,
        // A control that received NOTHING must not read as a row of neutral
        // "n/a" cells — an empty cell looks like "not required", which is the
        // opposite of the finding.
        noneReceived: expected > 0 && missingCount === expected,
        cells: cols.map((col) => {
          const bucket = buckets.get(col.key);
          if (!bucket) {
            // The engine expected no document of this kind for this control.
            // Genuinely different from "expected and absent" — but see
            // `partial` below for why an empty cell alone is not enough.
            return { col, state: "na" as CellState, received: [], missing: [] };
          }
          // Three states, because two lose information an auditor needs:
          //   received — every expected document of this kind arrived
          //   partial  — some arrived, some did not
          //   missing  — none arrived
          // Collapsing partial into missing made a control that supplied 3 of
          // 4 documents look identical to one that supplied none.
          const state: CellState =
            bucket.missing.length === 0
              ? "received"
              : bucket.received.length === 0
                ? "missing"
                : "partial";
          return { col, state, received: bucket.received, missing: bucket.missing };
        }),
      };
    });

    return { columns: cols, rows: builtRows };
  }, [requiredDocuments, missingByControl, scoreByControl, escalatedControls]);

  if (rows.length === 0 || columns.length === 0) return null;

  const scoreTone = (score: number | undefined) =>
    score === undefined
      ? "var(--muted)"
      : score >= 70
        ? "var(--pastel-green-ink)"
        : score >= 50
          ? "var(--pastel-amber-ink)"
          : "var(--pastel-red-ink)";

  return (
    <div className="coverage-grid">
      <div className="coverage-grid-legend">
        <span className="coverage-legend-item">
          <span className="coverage-swatch received" /> received
        </span>
        <span className="coverage-legend-item">
          <span className="coverage-swatch partial" /> partial
        </span>
        <span className="coverage-legend-item">
          <span className="coverage-swatch missing" /> missing
        </span>
        <span className="coverage-legend-item">
          <span className="coverage-swatch na" /> n/a
        </span>
      </div>

      <div
        className="coverage-grid-table"
        style={{ gridTemplateColumns: `74px repeat(${columns.length}, minmax(52px, 1fr)) 52px` }}
      >
        <span />
        {columns.map((c) => (
          <span key={c.key} className="coverage-col-head">
            {c.label}
          </span>
        ))}
        <span />

        {rows.map((row) => (
          <RowCells
            key={row.controlId}
            row={row}
            scoreTone={scoreTone}
            show={show}
            move={move}
            hide={hide}
          />
        ))}
      </div>
      {card}
    </div>
  );
}

type Row = {
  controlId: string;
  score: number | undefined;
  escalated: boolean;
  expected: number;
  receivedCount: number;
  noneReceived: boolean;
  cells: { col: { key: string; label: string }; state: CellState; received: string[]; missing: string[] }[];
};

function RowCells({
  row,
  scoreTone,
  show,
  move,
  hide,
}: {
  row: Row;
  scoreTone: (s: number | undefined) => string;
  show: ReturnType<typeof useHoverCard>["show"];
  move: ReturnType<typeof useHoverCard>["move"];
  hide: ReturnType<typeof useHoverCard>["hide"];
}) {
  return (
    <>
      <span
        className={`coverage-row-id${row.escalated ? " escalated" : ""}`}
        title={`${row.receivedCount} of ${row.expected} expected documents received`}
      >
        {row.controlId}
        {/* Says outright that nothing arrived, so the empty cells beside it
            cannot be read as "not required". */}
        {row.noneReceived && <span className="coverage-row-flag">no evidence</span>}
      </span>
      {row.cells.map((cell) => (
        <span
          key={cell.col.key}
          className={`coverage-cell ${cell.state}`}
          onMouseEnter={(e) =>
            show(e, {
              title: `${row.controlId} · ${cell.col.label}`,
              value:
                cell.state === "na"
                  ? "Not expected"
                  : cell.state === "received"
                    ? `${cell.received.length} of ${cell.received.length} received`
                    : `${cell.received.length} of ${cell.received.length + cell.missing.length} received`,
              sub:
                cell.state === "na"
                  ? "No document of this kind was expected for this control."
                  : `${row.receivedCount} of ${row.expected} documents received for ${row.controlId} overall.`,
              items: [
                ...cell.missing.map((d) => `Missing: ${d}`),
                ...cell.received.map((d) => `Received: ${d}`),
              ].slice(0, 6),
              color:
                cell.state === "missing" ? "var(--pastel-red-ink)" : "var(--pastel-blue-ink)",
            })
          }
          onMouseMove={move}
          onMouseLeave={hide}
        />
      ))}
      <span className="coverage-row-score" style={{ color: scoreTone(row.score) }}>
        {row.score === undefined ? "—" : `${row.score}%`}
      </span>
    </>
  );
}
