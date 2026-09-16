// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Tiny inline-SVG chart (bars or lines) for the admin statistics — no chart
 * library. Series carry literal Tailwind fill-/stroke- classes so the JIT
 * picks them up and they stay theme-aware. */
export interface ChartSeries {
  label: string;
  /** Literal Tailwind classes, e.g. "fill-brand-500" (bar) or "stroke-brand-500" (line). */
  className: string;
  points: { date: string; value: number }[];
}

const VIEW_W = 300;

export default function MiniChart({
  title,
  series,
  type,
  height = 110,
}: {
  title: string;
  series: ChartSeries[];
  type: "bar" | "line";
  height?: number;
}) {
  const n = Math.max(1, series[0]?.points.length ?? 0);
  const max = Math.max(1, ...series.flatMap((s) => s.points.map((p) => p.value)));
  const pad = 3;
  const innerW = VIEW_W - pad * 2;
  const innerH = height - pad * 2;
  const xAt = (i: number) => pad + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yAt = (v: number) => pad + innerH - (v / max) * innerH;
  const first = series[0]?.points[0]?.date ?? "";
  const last = series[0]?.points[n - 1]?.date ?? "";
  const latestTotal = series.reduce((sum, s) => sum + (s.points[n - 1]?.value ?? 0), 0);

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{title}</span>
        <span className="text-xs text-slate-400">max {max}</span>
      </div>
      <svg
        viewBox={`0 0 ${VIEW_W} ${height}`}
        preserveAspectRatio="none"
        className="h-[110px] w-full"
        style={{ height }}
        role="img"
        aria-label={title}
      >
        {type === "bar"
          ? series[0]?.points.map((p, i) => {
              const bw = (innerW / n) * 0.7;
              const bx = pad + (i / n) * innerW + (innerW / n - bw) / 2;
              const by = yAt(p.value);
              return (
                <rect
                  key={i}
                  x={bx}
                  y={by}
                  width={bw}
                  height={height - pad - by}
                  className={series[0].className}
                  rx={1}
                />
              );
            })
          : series.map((s, si) => (
              <polyline
                key={si}
                points={s.points.map((p, i) => `${xAt(i)},${yAt(p.value)}`).join(" ")}
                className={`${s.className} fill-none`}
                strokeWidth={2}
                vectorEffect="non-scaling-stroke"
              />
            ))}
      </svg>
      <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
        <span>{first?.slice(5)}</span>
        {type === "line" && series.length > 1 ? (
          <span className="flex gap-3">
            {series.map((s) => (
              <span key={s.label} className="flex items-center gap-1">
                <span className={`inline-block h-2 w-2 rounded-full ${s.className.replace("stroke-", "bg-")}`} />
                {s.label}
              </span>
            ))}
          </span>
        ) : (
          <span>Σ heute {latestTotal}</span>
        )}
        <span>{last?.slice(5)}</span>
      </div>
    </div>
  );
}
