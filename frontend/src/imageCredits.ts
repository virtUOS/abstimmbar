import type { TFunction } from "i18next";
import type { ImageCredit } from "./api";

/** Credits to show for a displayed question: only credited images whose `src`
 *  occurs (exact attribute value) in the language-resolved question HTML or
 *  among the option images (visible-language rule, #336). */
export function visibleImageCredits(
  credits: ImageCredit[] | undefined,
  html: string,
  optionImages: (string | undefined)[],
): ImageCredit[] {
  if (!credits?.length) return [];
  const visible = new Set(optionImages.filter((s): s is string => !!s));
  if (html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll("img").forEach((img) => {
      const src = img.getAttribute("src");
      if (src) visible.add(src);
    });
  }
  return credits.filter((c) => c.has_credit !== false && visible.has(c.src));
}

const httpUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : "");

/** The displayable pieces of one credit; `title` is already quoted in the
 *  UI language, link targets are only set for http(s) URLs. */
export function formatCreditParts(
  c: ImageCredit,
  t: TFunction,
  lang: string,
): { title?: string; author?: string; license?: string; licenseUrl?: string; source?: string } {
  const [open, close] = lang.startsWith("en") ? ["“", "”"] : ["„", "“"];
  const license =
    c.license === "pd"
      ? t("Public domain")
      : c.license === "arr"
        ? [t("All rights reserved"), c.text].filter(Boolean).join("; ")
        : c.license === "other"
          ? c.text
          : c.license_label;
  return {
    title: c.title ? `${open}${c.title}${close}` : undefined,
    author: c.author || undefined,
    license: license || undefined,
    licenseUrl: httpUrl(c.license_url) || undefined,
    source: httpUrl(c.source) || undefined,
  };
}
