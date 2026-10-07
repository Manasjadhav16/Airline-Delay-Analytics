import { useEffect, useRef, useState } from "react";
import "./SplitFlap.css";

// Order the drum spins through. Each tile only moves forward, like a real
// Solari board, so a change from "B" to "A" goes all the way round.
const CHARSET = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:.%-";
const STEP_MS = 38;

function prefersReducedMotion() {
  return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
}

function normalize(ch) {
  const upper = ch.toUpperCase();
  return CHARSET.includes(upper) ? upper : " ";
}

function display(ch) {
  return ch === " " ? " " : ch;
}

function FlapTile({ target, delay, start }) {
  const [shown, setShown] = useState(start);
  const [prev, setPrev] = useState(start);
  const [flipCount, setFlipCount] = useState(0);
  const shownRef = useRef(start);

  useEffect(() => {
    if (prefersReducedMotion()) {
      shownRef.current = target;
      setPrev(target);
      setShown(target);
      return undefined;
    }

    let timer;
    const step = () => {
      const current = shownRef.current;
      if (current === target) return;
      const next = CHARSET[(CHARSET.indexOf(current) + 1) % CHARSET.length];
      shownRef.current = next;
      setPrev(current);
      setShown(next);
      setFlipCount((n) => n + 1);
      timer = setTimeout(step, STEP_MS);
    };
    timer = setTimeout(step, delay);
    return () => clearTimeout(timer);
  }, [target, delay]);

  return (
    <span className="flap-tile">
      <span className="flap-half flap-top">
        <span>{display(shown)}</span>
      </span>
      <span className="flap-half flap-bottom">
        <span>{display(prev)}</span>
      </span>
      {flipCount > 0 && (
        <>
          <span key={`fold-${flipCount}`} className="flap-half flap-top flap-fold">
            <span>{display(prev)}</span>
          </span>
          <span key={`unfold-${flipCount}`} className="flap-half flap-bottom flap-unfold">
            <span>{display(shown)}</span>
          </span>
        </>
      )}
    </span>
  );
}

/**
 * A word on the board: `length` tiles, padded with blanks. Tiles start
 * flipping left to right, `stagger` ms apart. Screen readers get the plain
 * text instead of the individual tiles. With `animateIn`, tiles start blank
 * and spin up to their value on mount instead of appearing already set.
 */
export default function SplitFlap({
  value,
  length,
  align = "left",
  stagger = 45,
  animateIn = false,
  className = "",
}) {
  const raw = String(value ?? "").slice(0, length);
  const padded = align === "right" ? raw.padStart(length) : raw.padEnd(length);
  const chars = [...padded].map(normalize);

  return (
    <span className={`flap-word ${className}`}>
      <span className="visually-hidden">{raw.trim() || "blank"}</span>
      <span className="flap-tiles" aria-hidden="true">
        {chars.map((ch, i) => (
          <FlapTile key={i} target={ch} delay={i * stagger} start={animateIn ? " " : ch} />
        ))}
      </span>
    </span>
  );
}
