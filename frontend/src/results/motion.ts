// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Small motion helpers for result animations — CSS does the animating, these
 * only decide start state and timing. `@basicbar/ui/base.css` already cuts CSS
 * durations under prefers-reduced-motion; the hooks also skip delays and
 * count-ups then, so everything lands in its end state at once. */
import { useEffect, useRef, useState } from "react";

export const EASE = "cubic-bezier(.2,.8,.2,1)";
export const STAGGER_MS = 110;

const QUERY = "(prefers-reduced-motion: reduce)";

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () => typeof window !== "undefined" && !!window.matchMedia?.(QUERY).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY);
    if (!mq) return;
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/** false on the first paint, true from the frame after — lets a bar mount at
 * 0 and transition to its target. Without animation it is true at once. */
export function useGrown(animate: boolean): boolean {
  const [grown, setGrown] = useState(!animate);
  useEffect(() => {
    if (!animate) {
      setGrown(true);
      return;
    }
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => setGrown(true));
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [animate]);
  return grown;
}

/** Counts from the previous value (0 on mount) to `target` with an
 * ease-out-cubic curve; returns the rounded current value. */
export function useCountUp(
  target: number,
  { animate = true, duration = 700, delay = 0 }: { animate?: boolean; duration?: number; delay?: number } = {},
): number {
  const [value, setValue] = useState(animate ? 0 : target);
  const from = useRef(animate ? 0 : target);
  useEffect(() => {
    if (!animate || from.current === target) {
      from.current = target;
      setValue(target);
      return;
    }
    const start = performance.now() + delay;
    const origin = from.current;
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, Math.max(0, (now - start) / duration));
      const eased = 1 - Math.pow(1 - t, 3);
      const v = origin + (target - origin) * eased;
      from.current = v;
      setValue(Math.round(v));
      if (t < 1) raf = requestAnimationFrame(tick);
      else from.current = target;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, animate, duration, delay]);
  return value;
}
