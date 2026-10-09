// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Result colours for the presenter, results page and (as CSS variables)
 * the participant page. The accent is green and reads as "positive", so the
 * category palette for polls avoids green and red entirely: six pastel hues
 * at equal lightness/chroma. Green marks the correct answer only, a soft
 * rosé the wrong ones. */
const HUES = [250, 60, 305, 220, 85, 335] as const; // blue, apricot, lilac, sky, sand, mauve

export function categoryHue(i: number): number {
  return HUES[((i % HUES.length) + HUES.length) % HUES.length];
}
/** Bar fill for answer `i`. */
export const categoryColor = (i: number) => `oklch(0.80 0.095 ${categoryHue(i)})`;
/** Light tint of the same hue (before-bars, chips' background). */
export const categoryTint = (i: number) => `oklch(0.92 0.04 ${categoryHue(i)})`;
/** Strong variant of the same hue (lines, small marks). */
export const categoryDeep = (i: number) => `oklch(0.62 0.11 ${categoryHue(i)})`;

/** A stable hue for a free-form term (word cloud), so a word keeps its
 * colour while the list re-sorts. */
export function hashHue(text: string): number {
  let h = 0;
  for (let k = 0; k < text.length; k++) h = (h * 31 + text.charCodeAt(k)) | 0;
  return categoryHue(Math.abs(h));
}

/** Pastel fill for a free-form term (free-text chips), stable per text. */
export const termColor = (text: string) => `oklch(0.80 0.095 ${hashHue(text)})`;

export const CORRECT = "oklch(0.70 0.14 150)";
export const CORRECT_STRONG = "oklch(0.55 0.14 150)";
export const CORRECT_TINT = "oklch(0.90 0.06 150)";
export const WRONG = "oklch(0.88 0.045 20)";
export const WRONG_TINT = "oklch(0.94 0.02 20)";
export const NEUTRAL_TILE = "oklch(0.93 0.006 220)";
export const INK = "oklch(0.28 0.02 220)";
/** Mind-map rating "minus" (rosé, a touch deeper than WRONG so it reads on
 *  white) and its text colour; "plus" uses CORRECT / CORRECT_STRONG. */
export const MINUS = "oklch(0.80 0.08 20)";
export const MINUS_INK = "oklch(0.52 0.13 20)";
export const MINUS_TINT = "oklch(0.90 0.05 20)";

/** Likert (L1): rosé ↔ green in pastel, neutral grey in the middle. `rank`
 * is the distance from the centre (0 = innermost); extremes are darkest. */
export function likertFill(
  polarity: "low" | "neutral" | "high",
  groupSize: number,
  rank: number,
): string {
  if (polarity === "neutral") return "oklch(0.88 0.01 240)";
  const t = groupSize <= 1 ? 1 : rank / (groupSize - 1);
  const mix = (a: number, b: number) => (a + (b - a) * t).toFixed(3);
  return polarity === "low"
    ? `oklch(${mix(0.86, 0.72)} ${mix(0.06, 0.11)} 20)`
    : `oklch(${mix(0.87, 0.74)} ${mix(0.07, 0.12)} 150)`;
}

/** AI verdict categories: the first three read correct / partly / wrong (or
 * positive / neutral / negative), so they keep that meaning in pastel —
 * green, sand, rosé; follow-up categories take palette colours. */
const EVAL_FILLS = [CORRECT, "oklch(0.86 0.09 85)", "oklch(0.80 0.08 20)", categoryColor(0), categoryColor(2)];
export const evalColor = (i: number) => EVAL_FILLS[((i % EVAL_FILLS.length) + EVAL_FILLS.length) % EVAL_FILLS.length];
