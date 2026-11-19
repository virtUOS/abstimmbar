// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { localizedText, type LocalizedText } from "@basicbar/ui";

/** Alt text for an answer-option image (#342). An option with text is named
 *  by its text, so its image stays decorative (`alt=""`, read once); an
 *  image-only option is described by its resolved `image_alt` (same
 *  language fallback as the option text). Mirrors `optionImageAlt` on the
 *  participant page. */
export function optionImageAlt(option: { text: LocalizedText; image_alt?: LocalizedText }): string {
  if (localizedText(option.text).trim()) return "";
  return localizedText(option.image_alt ?? "").trim();
}
