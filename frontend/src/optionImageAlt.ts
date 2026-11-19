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

/** Like `optionImageAlt`, but an image-only option without any description
 *  falls back to `numbered` (e.g. "Answer 3") so it always has a name. */
export function optionImageName(
  option: { text: LocalizedText; image_alt?: LocalizedText },
  numbered: string,
): string {
  if (localizedText(option.text).trim()) return "";
  return localizedText(option.image_alt ?? "").trim() || numbered;
}

/** Visible-label variant for views that show no image (ordering, priorities,
 *  editor summary): the option text, else its description, else `numbered`. */
export function optionLabel(
  option: { text: LocalizedText; image_alt?: LocalizedText },
  numbered: string,
): string {
  return (
    localizedText(option.text).trim() ||
    localizedText(option.image_alt ?? "").trim() ||
    numbered
  );
}
