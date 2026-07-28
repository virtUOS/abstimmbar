// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Diverging Likert result bar (v2 review feedback): the ordered scale as a
 * single stacked bar — disagreement in reds to the left, agreement in the
 * brand green to the right, an optional neutral step in grey. A centre line
 * marks the split. Percentages are over the scale responses; abstentions sit
 * apart. Shared by the presentation (beamer) and the results page. */
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
  return step.polarity === "disagree"
    ? `oklch(${0.8 - 0.26 * t} ${0.08 + 0.13 * t} 27)`
    : `oklch(${0.84 - 0.3 * t} ${0.09 + 0.05 * t} 149)`;
}

/** Dark ink on the light inner segments, light ink on the dark extremes. */
function inkFor(step: LikertStep, groupSize: number, rank: number): string {
  if (step.polarity === "neutral") return "oklch(0.28 0.011 220)";
  const t = groupSize <= 1 ? 1 : rank / (groupSize - 1);
  const lightness = step.polarity === "disagree" ? 0.8 - 0.26 * t : 0.84 - 0.3 * t;
  return lightness > 0.62 ? "oklch(0.25 0.02 27)" : "oklch(0.98 0.01 149)";
}

interface Colored extends LikertStep {
  fill: string;
  ink: string;
}

function colorize(steps: LikertStep[]): Colored[] {
  const disagree = steps.filter((s) => s.polarity === "disagree").length;
  const agree = steps.filter((s) => s.polarity === "agree").length;
  let dSeen = 0;
  let aSeen = 0;
  return steps.map((step) => {
    let group = 1;
    let rank = 0;
    if (step.polarity === "disagree") {
      group = disagree;
      rank = disagree - 1 - dSeen; // innermost disagree step ranks 0
      dSeen += 1;
    } else if (step.polarity === "agree") {
      group = agree;
      rank = aSeen; // innermost agree step ranks 0
      aSeen += 1;
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
        <div
          className="absolute -top-1 -bottom-1 w-0.5 bg-slate-900 dark:bg-slate-100"
          style={{ left: `${summary.divider}%`, opacity: 0.55 }}
        />
      </div>

      {present && (
        <div className="mt-1.5 flex justify-between text-xs text-slate-400">
          <span>{t("← Disagreement")}</span>
          <span>{t("Agreement →")}</span>
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
        <span className="text-brand-700 dark:text-brand-300">
          <span className="font-semibold">{summary.agree_pct} %</span> {t("Agreement")}
        </span>
        {summary.neutral > 0 && (
          <span className="text-slate-500 dark:text-slate-400">
            <span className="font-semibold">{summary.neutral_pct} %</span> {t("neutral")}
          </span>
        )}
        <span className="text-rose-700 dark:text-rose-300">
          <span className="font-semibold">{summary.disagree_pct} %</span> {t("Disagreement")}
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
