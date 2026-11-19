// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** The guide on the project website, in the UI language (German at the
 *  site root, English under /en/). Build-time overrides: VITE_GUIDE_URL
 *  (German UI) and VITE_GUIDE_URL_EN (English UI). */
export const GUIDE_URL = {
  de: import.meta.env.VITE_GUIDE_URL || "https://virtuos.github.io/abstimmbar/anleitung/",
  en: import.meta.env.VITE_GUIDE_URL_EN || "https://virtuos.github.io/abstimmbar/en/guide/",
};

/** Guide root, or one of its pages (`{de, en}` page paths, e.g.
 *  `{ de: "fragen/", en: "questions/" }`) plus an optional `#anchor`. */
export function guideUrl(
  language: string | undefined,
  page?: { de: string; en: string },
  anchor?: string,
): string {
  const de = !!language?.startsWith("de");
  const base = de ? GUIDE_URL.de : GUIDE_URL.en;
  const path = page ? (de ? page.de : page.en) : "";
  return base + path + (anchor ? `#${anchor}` : "");
}
