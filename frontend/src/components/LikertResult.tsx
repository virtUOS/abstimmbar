// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Diverging Likert result bar (#86): the ordered scale as a single stacked
 * bar — the low (negative) pole in reds to the left, the high (positive) pole
 * in the brand green to the right, an optional neutral step in grey. The two
 * endpoint labels caption the ends. A centre line marks the intensity-weighted
 * mean (mean_pct) — it weights each vote by how extreme its step is, so it
 * leans toward the heavier / more extreme side rather than the plain count
 * split. Percentages are over the scale responses; abstentions sit apart.
 * Shared by the presentation (beamer) and the results page. */
import { useTranslation } from "react-i18next";
import type { LikertStep, LikertSummary } from "../api";
import { localizedText } from "@basicbar/ui";

/** Data-driven fills as OKLCH so shades scale to any number of steps —
 * Tailwind's JIT can't see class names built at runtime. `rank` is the
 * distance from the centre (0 = innermost, extremes darkest/most saturated).
 * Agreement reuses the brand hue (≈149); disagreement a warm red (≈27). */
function stepFill(step: LikertStep, groupSize: number, rank: number): string {
  if (step.polarity === "neutral") return "oklch(0.8 0.012 220)";
  const t = groupSize <= 1 ? 1 : rank / (groupSize - 1);
  return step.polarity === "low"
    ? `oklch(${0.8 - 0.26 * t} ${0.08 + 0.13 * t} 27)`
    : `oklch(${0.84 - 0.3 * t} ${0.09 + 0.05 * t} 149)`;
}

/** Dark ink on the light inner segments, light ink on the dark extremes. */
function inkFor(step: LikertStep, groupSize: number, rank: number): string {
  if (step.polarity === "neutral") return "oklch(0.28 0.011 220)";
  const t = groupSize <= 1 ? 1 : rank / (groupSize - 1);
  const lightness = step.polarity === "low" ? 0.8 - 0.26 * t : 0.84 - 0.3 * t;
  return lightness > 0.62 ? "oklch(0.25 0.02 27)" : "oklch(0.98 0.01 149)";
}

interface Colored extends LikertStep {
  fill: string;
  ink: string;
}

function colorize(steps: LikertStep[]): Colored[] {
  const low = steps.filter((s) => s.polarity === "low").length;
  const high = steps.filter((s) => s.polarity === "high").length;
  let lSeen = 0;
  let hSeen = 0;
  return steps.map((step) => {
    let group = 1;
    let rank = 0;
    if (step.polarity === "low") {
      group = low;
      rank = low - 1 - lSeen; // innermost low step ranks 0
      lSeen += 1;
    } else if (step.polarity === "high") {
      group = high;
      rank = hSeen; // innermost high step ranks 0
      hSeen += 1;
    }
    return { ...step, fill: stepFill(step, group, rank), ink: inkFor(step, group, rank) };
  });
}

export default function LikertResult({
  summary,
  variant = "present",
}: {
  summary: LikertSummary;
  variant?: "present" | "compact";
}) {
  const { t } = useTranslation();
  const present = variant === "present";
  const steps = colorize(summary.steps);
  const labelThreshold = present ? 7 : Infinity; // %-width needed to show a % inside

  if (summary.scale_total === 0) {
    return (
      <p className={present ? "mt-8 text-slate-400" : "text-sm text-slate-400"}>
        {t("No answers yet …")}
      </p>
    );
  }

  return (
    <div className={present ? "mt-8" : ""}>
      <div className="relative">
        <div
          className={`relative flex overflow-hidden ${present ? "h-11 rounded-xl text-base" : "h-6 rounded-md text-[11px]"}`}
        >
          {steps.map((step) => (
            <div
              key={step.id}
              className="flex items-center justify-center tabular-nums"
              style={{ flex: `0 0 ${step.pct}%`, background: step.fill, color: step.ink }}
              title={`${localizedText(step.text)}: ${step.count} · ${step.pct} %`}
            >
              {step.pct >= labelThreshold && `${Math.round(step.pct)} %`}
            </div>
          ))}
        </div>
        {/* Mean marker: the intensity-weighted central tendency (mean_pct), not
            the plain 50:50 count split — so it leans toward the heavier / more
            extreme side. Lives in this un-clipped wrapper (the bar itself is
            overflow-hidden to clip its rounded segments) so it can stick out a
            little above and below the bar. */}
        <div
          className={`pointer-events-none absolute w-0.5 -translate-x-1/2 rounded-full bg-slate-900 dark:bg-slate-100 ${present ? "-top-2 -bottom-2" : "-top-1.5 -bottom-1.5"}`}
          style={{ left: `${summary.mean_pct}%`, opacity: 0.8 }}
        >
          <span
            className={`absolute left-1/2 -translate-x-1/2 font-semibold text-slate-700 dark:text-slate-200 ${present ? "-top-6 text-sm" : "-top-4 text-[10px]"}`}
          >
            ⌀
          </span>
        </div>
      </div>

      {present && (
        <div className="mt-1.5 flex justify-between text-xs text-slate-400">
          <span>{localizedText(summary.low_label) ? `← ${localizedText(summary.low_label)}` : "←"}</span>
          <span>{localizedText(summary.high_label) ? `${localizedText(summary.high_label)} →` : "→"}</span>
        </div>
      )}

      {present && (
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1.5 text-sm text-slate-600 dark:text-slate-300">
          {steps.map((step) => (
            <span key={step.id} className="flex items-center gap-2">
              <span
                className="inline-block h-3 w-3 rounded"
                style={{ background: step.fill }}
              />
              {localizedText(step.text)} · {step.count}
            </span>
          ))}
        </div>
      )}

      <div
        className={`flex flex-wrap items-center gap-x-4 gap-y-1 ${present ? "mt-4 border-t border-slate-200 pt-3 text-lg dark:border-slate-700" : "mt-2 text-xs"}`}
      >
        {/* Left→right to match the bar: low (red) first, then neutral, then
            high (green) — so "Stimme nicht zu" reads on the left. */}
        <span className="text-rose-700 dark:text-rose-300">
          <span className="font-semibold">{summary.low_pct} %</span>{" "}
          {localizedText(summary.low_label) || t("low")}
        </span>
        {summary.neutral > 0 && (
          <span className="text-slate-500 dark:text-slate-400">
            <span className="font-semibold">{summary.neutral_pct} %</span> {t("neutral")}
          </span>
        )}
        <span className="text-brand-700 dark:text-brand-300">
          <span className="font-semibold">{summary.high_pct} %</span>{" "}
          {localizedText(summary.high_label) || t("high")}
        </span>
        {summary.abstentions > 0 && (
          <span className="ml-auto text-slate-400">
            {summary.abstentions}{" "}
            {t("abstention", { count: summary.abstentions })}
          </span>
        )}
      </div>
    </div>
  );
}
