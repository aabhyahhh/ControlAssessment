import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";

interface TypedSummaryProps {
  /** Paragraphs to type out, in order. */
  paragraphs: string[];
  /** Characters per second. */
  speed?: number;
  title?: string;
}

/**
 * An AI-style summary that types itself out the first time it scrolls into
 * view, then stays put.
 *
 * Typing is driven by a character count against a rAF clock rather than a
 * per-character interval: an interval drifts under load and, at 12 chars a
 * tick, produced visibly uneven output. Reduced-motion users get the full
 * text immediately — a paragraph that withholds its content is a hostile
 * thing to put in front of someone who asked for less motion.
 */
export default function TypedSummary({ paragraphs, speed = 55, title = "AI summary" }: TypedSummaryProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [started, setStarted] = useState(false);
  const [typed, setTyped] = useState(0);

  const full = paragraphs.join("\n\n");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setStarted(true);
      setTyped(full.length);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setStarted(true);
          io.disconnect();
        }
      },
      { threshold: 0.25 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [full.length]);

  useEffect(() => {
    if (!started) return;
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const chars = Math.floor(((now - start) / 1000) * speed);
      setTyped(Math.min(chars, full.length));
      if (chars < full.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [started, full, speed]);

  const visible = full.slice(0, typed);
  const done = typed >= full.length;

  return (
    <div className="ai-summary" ref={ref}>
      <div className="ai-summary-head">
        <span className="ai-summary-icon" aria-hidden="true">
          <Sparkles size={13} strokeWidth={2} />
        </span>
        <span className="ai-summary-title">{title}</span>
      </div>
      {/* The finished text is always in the DOM for assistive tech; the
          visually-typed copy is aria-hidden so a screen reader is not fed a
          stream of half-words as it fills in. */}
      <div className="ai-summary-body" aria-hidden="true">
        {visible.split("\n\n").map((para, i) => (
          <p key={i}>
            {para}
            {!done && i === visible.split("\n\n").length - 1 && <span className="ai-summary-caret" />}
          </p>
        ))}
      </div>
      <div className="sr-only">
        {paragraphs.map((para, i) => (
          <p key={i}>{para}</p>
        ))}
      </div>
    </div>
  );
}
