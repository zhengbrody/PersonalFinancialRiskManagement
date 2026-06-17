"use client";

/**
 * Zero-dep marketing motion: scroll-reveal + count-up. Both guard for
 * SSR/jsdom (no IntersectionObserver / matchMedia / rAF) and
 * prefers-reduced-motion by rendering the FINAL state — so server-rendered
 * HTML is complete (crawlable) and the page is testable without a browser.
 */

import { useEffect, useRef, useState, type ReactNode } from "react";

export const reducedMotion = () =>
  typeof window === "undefined" ||
  !window.matchMedia ||
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function useReveal<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined" || reducedMotion()) {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      (es) =>
        es.forEach((e) => {
          if (e.isIntersecting) {
            setSeen(true);
            io.disconnect();
          }
        }),
      { threshold: 0.16 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return { ref, seen };
}

export function Reveal({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  const { ref, seen } = useReveal<HTMLDivElement>();
  return (
    <div
      ref={ref}
      style={{
        opacity: seen ? 1 : 0,
        transform: seen ? "none" : "translateY(24px)",
        transition: `opacity .9s cubic-bezier(.16,1,.3,1) ${delay}s, transform .9s cubic-bezier(.16,1,.3,1) ${delay}s`,
      }}
    >
      {children}
    </div>
  );
}

/** Count a number up to `to` once `start` flips true. */
export function useCountUp(to: number, start: boolean, dur = 1500) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!start) return;
    if (reducedMotion() || typeof requestAnimationFrame === "undefined") {
      setV(to);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / dur);
      setV(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, start, dur]);
  return v;
}
