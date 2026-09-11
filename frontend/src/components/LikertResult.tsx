// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Likert result (#86): the distribution as a column per scale step (low pole
 * in reds on the left, high pole in the brand green on the right, neutral grey),
 * with a mean marker that weights each vote by how extreme its step is — so it
 * leans toward the heavier/more extreme side rather than sitting at the plain
 * count split. Endpoint labels caption the ends; abstentions sit apart. Shared
 * by the presentation (beamer) and the results page. */
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

  if (summary.scale_total === 0) {
    return (
      <p className={present ? "mt-8 text-slate-400" : "text-sm text-slate-400"}>
        {t("No answers yet …")}
      </p>
    );
  }

  const maxCount = Math.max(1, ...steps.map((step) => step.count));
  const barMax = present ? 88 : 52; // px, tallest bar
  const labelH = present ? 20 : 15;

  return (
    <div className={present ? "mt-8" : ""}>
      {/* Distribution along the scale (equal-width step columns) with a mean
          marker (#86): the mean weights each vote by how extreme its step is,
          so it leans toward the heavier / more extreme side rather than the
          plain count split. */}
      <div className="relative" style={{ height: barMax + labelH }}>
        <div className="flex h-full items-end">
          {steps.map((step) => (
            <div
              key={step.id}
              className="flex h-full flex-col items-center justify-end px-0.5"
              style={{ width: `${100 / steps.length}%` }}
              title={`${localizedText(step.text)}: ${step.count} · ${step.pct} %`}
            >
              <span
                className={`tabular-nums text-slate-500 dark:text-slate-400 ${present ? "text-sm" : "text-[10px]"}`}
                style={{ height: labelH, lineHeight: `${labelH}px` }}
              >
                {step.count || ""}
              </span>
              <div
                className="w-full rounded-t"
                style={{
                  height: `${(step.count / maxCount) * barMax}px`,
                  minHeight: step.count > 0 ? 4 : 0,
                  background: step.fill,
                }}
              />
            </div>
          ))}
        </div>
        {/* Mean marker line across the columns. */}
        <div
          className="pointer-events-none absolute -top-1 bottom-0 w-0.5 -translate-x-1/2 rounded-full bg-slate-900 dark:bg-slate-100"
          style={{ left: `${summary.mean_pct}%`, opacity: 0.85 }}
        >
          <span
            className={`absolute -translate-x-1/2 whitespace-nowrap font-semibold text-slate-700 dark:text-slate-200 ${present ? "-top-6 text-sm" : "-top-4 text-[10px]"}`}
            style={{ left: "50%" }}
          >
            ⌀
          </span>
        </div>
      </div>

      {/* Baseline + endpoint labels. */}
      <div className="mt-1 border-t border-slate-200 dark:border-slate-700" />
      <div
        className={`mt-1 flex justify-between text-slate-500 dark:text-slate-400 ${present ? "text-sm" : "text-[11px]"}`}
      >
        <span>{localizedText(summary.low_label) ? `← ${localizedText(summary.low_label)}` : "←"}</span>
        <span>{localizedText(summary.high_label) ? `${localizedText(summary.high_label)} →` : "→"}</span>
      </div>

      <div
        className={`flex flex-wrap items-center gap-x-4 gap-y-1 ${present ? "mt-4 border-t border-slate-200 pt-3 text-lg dark:border-slate-700" : "mt-2 text-xs"}`}
      >
        {/* Left→right to match the bar: low (red) first, then neutral, then high. */}
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
