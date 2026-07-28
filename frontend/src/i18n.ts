// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Wires the tool's own catalogs (`src/locales/<lang>/translation.json`) into
 *  the shared i18n setup from @basicbar/ui (English-as-key, plural handling,
 *  localStorage+navigator detection, <html lang> sync). */
import { initI18n } from "@basicbar/ui";
import de from "./locales/de/translation.json";
import en from "./locales/en/translation.json";

initI18n({ resources: { en, de } });

export { SUPPORTED_LANGUAGES, i18n as default } from "@basicbar/ui";
