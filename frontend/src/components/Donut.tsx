// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Small inline-SVG donut chart with a legend — for all-time breakdowns
 * (by type/kind/mode). No chart library. Colours are literal Tailwind
 * stroke-/bg- classes so the JIT emits them. */
export interface DonutSegment {
  label: string;
  value: number;
  /** Literal Tailwind ring stroke, e.g. "stroke-brand-500". */
  strokeClass: string;
  /** Literal Tailwind legend-dot background, e.g. "bg-brand-500". */
  dotClass: string;
}

const R = 42;
const C = 2 * Math.PI * R;

export default function Donut({ title, segments }: { title: string; segments: DonutSegment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  let offset = 0;
  return (
    <div>
      <div className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">{title}</div>
      <div className="flex items-center gap-4">
        <svg viewBox="0 0 100 100" className="h-24 w-24 shrink-0 -rotate-90" role="img" aria-label={title}>
          <circle
            cx={50}
            cy={50}
            r={R}
            fill="none"
            strokeWidth={13}
            className="stroke-slate-100 dark:stroke-slate-800"
          />
          {total > 0 &&
            segments.map((seg, i) => {
              const len = (seg.value / total) * C;
              const el = (
                <circle
                  key={i}
                  cx={50}
                  cy={50}
                  r={R}
                  fill="none"
                  strokeWidth={13}
                  className={seg.strokeClass}
                  strokeDasharray={`${len} ${C - len}`}
                  strokeDashoffset={-offset}
                />
              );
              offset += len;
              return el;
            })}
        </svg>
        <div className="min-w-0 flex-1 space-y-1 text-sm">
          {segments.map((seg) => (
            <div key={seg.label} className="flex items-center gap-2">
              <span className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${seg.dotClass}`} />
              <span className="flex-1 truncate text-slate-600 dark:text-slate-300">{seg.label}</span>
              <span className="shrink-0 tabular-nums text-slate-500">
                {seg.value}
                {total > 0 ? ` · ${Math.round((seg.value / total) * 100)}%` : ""}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
