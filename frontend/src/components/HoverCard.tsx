import { useCallback, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** A list row that carries its own icon, so a hover card can present a set
 *  of artefacts rather than a paragraph of bullets. */
export interface HoverCardRow {
  icon?: ReactNode;
  text: string;
  /** Optional trailing note, right-aligned (e.g. "missing"). */
  note?: string;
}

export interface HoverCardContent {
  title: string;
  value: string;
  sub?: string;
  items?: string[];
  /** Richer alternative to `items` — rendered with icons and an optional
   *  section heading. When both are present, `rows` is shown after `items`. */
  rows?: HoverCardRow[];
  rowsHeading?: string;
  color?: string;
}

interface HoverState extends HoverCardContent {
  x: number;
  y: number;
}

/**
 * Shared hover-card for charts.
 *
 * Rendered in a portal with `position: fixed` so it escapes the data pane's
 * `overflow: auto` — a card anchored inside the scroll container gets
 * clipped at the pane edge, which is exactly where chart elements sit.
 */
export function useHoverCard() {
  const [state, setState] = useState<HoverState | null>(null);

  const show = useCallback((e: { clientX: number; clientY: number }, content: HoverCardContent) => {
    setState({ ...content, x: e.clientX, y: e.clientY });
  }, []);

  const move = useCallback((e: { clientX: number; clientY: number }) => {
    setState((prev) => (prev ? { ...prev, x: e.clientX, y: e.clientY } : prev));
  }, []);

  const hide = useCallback(() => setState(null), []);

  const card: ReactNode = state
    ? createPortal(
        <div
          className="hover-card"
          style={{
            // Flip to the other side near a viewport edge so the card is
            // never cut off.
            left: Math.min(state.x + 14, window.innerWidth - 300),
            top: Math.max(12, Math.min(state.y - 12, window.innerHeight - 260)),
          }}
        >
          <div className="hover-card-title">
            {state.color && <span className="hover-card-swatch" style={{ background: state.color }} />}
            {state.title}
          </div>
          <div className="hover-card-value">{state.value}</div>
          {state.sub && <div className="hover-card-sub">{state.sub}</div>}
          {state.items && state.items.length > 0 && (
            <ul className="hover-card-list">
              {state.items.slice(0, 6).map((it, i) => (
                <li key={i}>{it}</li>
              ))}
              {state.items.length > 6 && <li>+{state.items.length - 6} more…</li>}
            </ul>
          )}
          {state.rows && state.rows.length > 0 && (
            <div className="hover-card-rows">
              {state.rowsHeading && <div className="hover-card-rows-heading">{state.rowsHeading}</div>}
              <ul className="hover-card-doc-list">
                {state.rows.slice(0, 7).map((r, i) => (
                  <li key={i}>
                    {r.icon && <span className="hover-card-doc-icon" aria-hidden="true">{r.icon}</span>}
                    <span className="hover-card-doc-text">{r.text}</span>
                    {r.note && <span className="hover-card-doc-note">{r.note}</span>}
                  </li>
                ))}
                {state.rows.length > 7 && (
                  <li className="hover-card-doc-more">+{state.rows.length - 7} more…</li>
                )}
              </ul>
            </div>
          )}
        </div>,
        document.body,
      )
    : null;

  return { show, move, hide, card };
}
