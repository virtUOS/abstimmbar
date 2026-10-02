// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Priorities result (P3): the average as a bar in the answer's palette
 * colour, the min–max spread as a line in the deeper shade of that colour
 * with round end points. Animated: the bar grows, then the line draws out
 * from the average to both sides, then the end points fade in. Values are
 * points out of 100, used directly as track percentages. */
import { categoryColor, categoryDeep } from "./palette";
import { EASE, STAGGER_MS, useGrown, useReducedMotion } from "./motion";

export default function PriorityBar({
  index,
  label,
  avg,
  min,
  max,
  size = "present",
  animate = false,
}: {
  index: number;
  label: React.ReactNode;
  avg: number;
  min: number;
  max: number;
  size?: "present" | "compact";
  animate?: boolean;
}) {
  const reduced = useReducedMotion();
  const anim = animate && !reduced;
  const grown = useGrown(anim);
  const d = anim ? index * STAGGER_MS : 0;
  const present = size === "present";
  const trackH = present ? 30 : 20;
  const radius = present ? 9 : 6;
  const lineH = present ? 4 : 3;
  const cap = present ? 10 : 8;
  const spread = Math.max(max - min, 0);
  const origin = spread ? ((avg - min) / spread) * 100 : 50;
  const deep = categoryDeep(index);
  const capStyle = (left: number): React.CSSProperties => ({
    position: "absolute",
    top: "50%",
    left: `${left}%`,
    width: cap,
    height: cap,
    marginTop: -cap / 2,
    marginLeft: -cap / 2,
    borderRadius: "50%",
    background: deep,
    opacity: grown ? 1 : 0,
    transition: `opacity 300ms ${anim ? 1400 + d : 0}ms`,
  });

  return (
    <div>
      <div className={`mb-1 flex items-center justify-between gap-4 ${present ? "text-xl" : "text-sm"}`}>
        <span className="min-w-0">{label}</span>
        <span className="shrink-0 tabular-nums text-slate-500">
          Ø {avg} · {min}–{max}
        </span>
      </div>
      <div className="relative bg-slate-100" style={{ height: trackH, borderRadius: radius }}>
        <div
          className="absolute inset-y-0 left-0"
          style={{
            borderRadius: radius,
            width: `${grown ? avg : 0}%`,
            background: categoryColor(index),
            transition: `width 900ms ${EASE} ${d}ms`,
          }}
        />
        <div
          className="absolute"
          style={{
            top: "50%",
            height: lineH,
            marginTop: -lineH / 2,
            left: `${min}%`,
            width: `${spread}%`,
            borderRadius: lineH,
            background: deep,
            transform: `scaleX(${grown ? 1 : 0})`,
            transformOrigin: `${origin}% 50%`,
            transition: `transform 600ms ${EASE} ${anim ? 900 + d : 0}ms`,
          }}
        />
        <div style={capStyle(min)} />
        <div style={capStyle(max)} />
      </div>
    </div>
  );
}
