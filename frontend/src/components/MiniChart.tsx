// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Inline-SVG bar chart for the admin statistics — no chart library. One
 * series draws plain daily bars; several series draw stacked bars (with a
 * legend). Hovering a day column shows a tooltip with the date and each
 * series value. Colours come from literal Tailwind fill-/bg- classes so the
 * JIT emits them and they stay theme-aware. */
import { useState } from "react";
import { useTranslation } from "react-i18next";

export interface ChartSeries {
  label: string;
  /** Literal Tailwind bar fill, e.g. "fill-brand-500". */
  fillClass: string;
  /** Literal Tailwind legend-dot background, e.g. "bg-brand-500". */
  dotClass: string;
  points: { date: string; value: number }[];
}

function formatDate(iso: string): string {
  const [y, m, d] = iso.split("-");
  return y && m && d ? `${d}.${m}.${y}` : iso;
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
  const [hover, setHover] = useState<{ i: number; x: number; w: number } | null>(null);
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
  const multi = series.length > 1;

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</span>
        <span className="text-xs text-slate-400">
          {t("total {{n}}", { n: grandTotal })} · max {max}
        </span>
      </div>
      <div className="relative">
        <svg
          viewBox={`0 0 ${VIEW_W} ${height}`}
          preserveAspectRatio="none"
          className="w-full"
          style={{ height }}
          role="img"
          aria-label={title}
          onMouseMove={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const rel = (e.clientX - rect.left) / rect.width;
            const i = Math.min(n - 1, Math.max(0, Math.floor(rel * n)));
            setHover({ i, x: ((i + 0.5) / n) * rect.width, w: rect.width });
          }}
          onMouseLeave={() => setHover(null)}
        >
          {hover && (
            <rect
              x={pad + hover.i * slot}
              y={pad}
              width={slot}
              height={innerH}
              className="fill-slate-400/10"
            />
          )}
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
        {hover && (
          <div
            className={
              "pointer-events-none absolute -top-1 z-10 -translate-y-full whitespace-nowrap rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs shadow-md dark:border-slate-700 dark:bg-slate-800 " +
              (hover.x < 70 ? "translate-x-0" : hover.x > hover.w - 70 ? "-translate-x-full" : "-translate-x-1/2")
            }
            style={{ left: hover.x }}
          >
            <div className="mb-0.5 font-medium text-slate-700 dark:text-slate-200">
              {formatDate(series[0]?.points[hover.i]?.date ?? "")}
            </div>
            {series.map((s) => (
              <div key={s.label || "v"} className="flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
                {multi && <span className={`inline-block h-2 w-2 rounded-full ${s.dotClass}`} />}
                {s.label && <span>{s.label}:</span>}
                <span className="tabular-nums font-medium">{s.points[hover.i]?.value ?? 0}</span>
              </div>
            ))}
            {multi && (
              <div className="mt-0.5 border-t border-slate-100 pt-0.5 text-slate-500 dark:border-slate-700">
                {t("total {{n}}", { n: dayTotals[hover.i] })}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
        <span>{first?.slice(5)}</span>
        {multi && (
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
