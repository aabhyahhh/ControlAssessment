import { useEffect, useState } from "react";

/**
 * Counts a numeric value up on mount (and whenever it changes); passes text
 * values straight through. Shared by every chart/card that shows a number
 * arriving with a bit of motion, so they animate identically and respect
 * reduced-motion the same way.
 *
 * `value` may be `undefined` — real project state can genuinely be missing a
 * figure (a step not yet run, an engine field that only appears once
 * assessed), and that can change across renders as a phase result arrives.
 * Rendering `undefined` would leave a blank card with no indication
 * anything is wrong, which reads as broken rather than intentional — so
 * this shows the literal placeholder instead, never a silent blank and
 * never a fabricated zero. Hooks below always run unconditionally (no early
 * return before them) so `value` flipping to/from `undefined` between
 * renders never changes how many hooks this component calls.
 */
export function useCountUp(value: string | number | undefined, placeholder = "—"): string | number {
  const target =
    value === undefined
      ? NaN
      : typeof value === "number"
        ? value
        : Number(String(value).replace(/[^0-9.]/g, ""));
  const isNumeric = value !== undefined && (typeof value === "number" || (!Number.isNaN(target) && /\d/.test(String(value))));
  const suffix = typeof value === "string" ? String(value).replace(/[0-9.,\s]/g, "") : "";
  const initial: string | number | undefined = isNumeric ? 0 : value;
  const [shown, setShown] = useState<string | number | undefined>(initial);

  useEffect(() => {
    if (value === undefined) {
      setShown(undefined);
      return;
    }
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      return;
    }
    if (!isNumeric) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const duration = 700;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = target * eased;
      setShown(Number.isInteger(target) ? Math.round(current) : Number(current.toFixed(1)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, target, isNumeric]);

  if (value === undefined) return placeholder;
  return isNumeric ? `${shown}${suffix}` : (shown ?? value);
}
