import { useState, type ReactNode } from "react";

/**
 * One expandable row keyed by a Control ID. Long per-control detail (missing
 * fields, expected documents) reads as a wall of text when every row is open
 * at once, so rows start collapsed and show a count instead.
 */
interface CollapsibleRowProps {
  /** Control ID — the row's identity, always visible. */
  id: string;
  /** Emoji/glyph shown before the id. Purely decorative. */
  icon?: ReactNode;
  /** Short summary shown while collapsed, e.g. "3 documents". */
  summary: ReactNode;
  /** Accent colour for the left border and icon chip. */
  tone?: "red" | "amber" | "green" | "blue" | "violet";
  children: ReactNode;
  defaultOpen?: boolean;
}

export default function CollapsibleRow({
  id, icon, summary, tone = "blue", children, defaultOpen = false,
}: CollapsibleRowProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={`collapsible-row tone-${tone}${open ? " open" : ""}`}>
      <button
        type="button"
        className="collapsible-row-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {icon && <span className="collapsible-row-icon" aria-hidden="true">{icon}</span>}
        <span className="collapsible-row-id">{id}</span>
        <span className="collapsible-row-summary">{summary}</span>
        <svg
          className="collapsible-row-chevron"
          width="14" height="14" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" strokeWidth="2.5"
          strokeLinecap="round" strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && <div className="collapsible-row-body">{children}</div>}
    </div>
  );
}
