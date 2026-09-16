// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Inline-SVG bar chart for the admin statistics — no chart library. One
 * series draws plain daily bars; several series draw stacked bars (with a
 * legend). Colours come from literal Tailwind fill-/bg- classes so the JIT
 * emits them and they stay theme-aware. */
import { useTranslation } from "react-i18next";

export interface ChartSeries {
  label: string;
  /** Literal Tailwind bar fill, e.g. "fill-brand-500". */
  fillClass: string;
  /** Literal Tailwind legend-dot background, e.g. "bg-brand-500". */
  dotClass: string;
  points: { date: string; value: number }[];
}

export default function MiniChart({
  title,
  series,
  height = 130,
}: {
  title: string;
  series: ChartSeries[];
  height?: number;
}) {
  const { t } = useTranslation();
  const n = Math.max(1, series[0]?.points.length ?? 0);
  const dayTotals = Array.from({ length: n }, (_, i) =>
    series.reduce((sum, s) => sum + (s.points[i]?.value ?? 0), 0),
  );
  const max = Math.max(1, ...dayTotals);
  const VIEW_W = 600;
  const pad = 3;
  const innerW = VIEW_W - pad * 2;
  const innerH = height - pad * 2;
  const slot = innerW / n;
  const bw = slot * 0.72;
  const first = series[0]?.points[0]?.date ?? "";
  const last = series[0]?.points[n - 1]?.date ?? "";
  const grandTotal = dayTotals.reduce((a, b) => a + b, 0);

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</span>
        <span className="text-xs text-slate-400">
          {t("total {{n}}", { n: grandTotal })} · max {max}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${VIEW_W} ${height}`}
        preserveAspectRatio="none"
        className="w-full"
        style={{ height }}
        role="img"
        aria-label={title}
      >
        {Array.from({ length: n }).map((_, i) => {
          const bx = pad + i * slot + (slot - bw) / 2;
          let yBottom = height - pad;
          return series.map((s, si) => {
            const v = s.points[i]?.value ?? 0;
            const h = (v / max) * innerH;
            yBottom -= h;
            return h > 0 ? (
              <rect key={`${i}-${si}`} x={bx} y={yBottom} width={bw} height={h} className={s.fillClass} rx={0.5} />
            ) : null;
          });
        })}
      </svg>
      <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
        <span>{first?.slice(5)}</span>
        {series.length > 1 && (
          <span className="flex flex-wrap justify-center gap-x-3 gap-y-0.5">
            {series.map((s) => (
              <span key={s.label} className="flex items-center gap-1">
                <span className={`inline-block h-2 w-2 rounded-full ${s.dotClass}`} />
                {s.label}
              </span>
            ))}
          </span>
        )}
        <span>{last?.slice(5)}</span>
      </div>
    </div>
  );
}
