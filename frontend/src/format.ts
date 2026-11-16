// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Locale-aware number display for results (#293): "66,7" / "5,3" in the
 *  German UI, "66.7" / "5.3" in the English one. Values used for widths or
 *  positions stay raw numbers — only displayed text goes through here. */
import { i18n } from "@basicbar/ui";

const cache = new Map<string, Intl.NumberFormat>();

function formatter(maxFractionDigits: number, percent = false): Intl.NumberFormat {
  const lang = i18n.language || "de";
  const key = `${lang}|${maxFractionDigits}|${percent}`;
  let f = cache.get(key);
  if (!f) {
    f = new Intl.NumberFormat(lang, {
      maximumFractionDigits: maxFractionDigits,
      ...(percent ? { style: "percent" } : {}),
    });
    cache.set(key, f);
  }
  return f;
}

/** A number in the UI language, at most `maxFractionDigits` decimals. */
export function fmtNum(n: number, maxFractionDigits = 1): string {
  return formatter(maxFractionDigits).format(n);
}

/** A percentage (0–100) in the UI language's style: "66,7 %" / "66.7%". */
export function fmtPct(n: number, maxFractionDigits = 1): string {
  return formatter(maxFractionDigits, true).format(n / 100);
}
