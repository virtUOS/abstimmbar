// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** What a question import (#323) left out: one line per (reason, detail)
 *  with a translated reason and the source-side detail. Shared by the review
 *  panel and the import dialog (a 400 can carry the list, too). */
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import type { ImportFormat, ImportSkip } from "../api";

// Labels are English source strings, translated with t() at the render site.
export const IMPORT_FORMAT_LABEL: Record<ImportFormat, string> = {
  simple: "Simple text format",
  gift: "GIFT (Moodle)",
  h5p: "H5P",
  ilias: "ILIAS",
};

/** Source question types with a readable name; anything else (H5P library
 *  names, ILIAS type ids) is shown as it comes. */
const SOURCE_TYPE_LABEL: Record<string, string> = {
  matching: "Matching",
  "matching question": "Matching",
  cloze: "Cloze",
  "cloze question": "Cloze",
  numerical: "Numerical",
  "numeric question": "Numerical",
  description: "Description",
};

const KIND_LABEL: Record<string, string> = {
  single_choice: "Single Choice",
  multiple_choice: "Multiple Choice",
  open_text: "Free text",
  ordering: "Ordering",
};

/** The simple-format reader reports positions as "Zeile 12". */
function detailText(detail: string, t: TFunction): string {
  const line = /^Zeile (\d+)$/.exec(detail);
  return line ? t("line {{n}}", { n: line[1] }) : detail;
}

export function importSkipText(skip: ImportSkip, t: TFunction): string {
  const detail = detailText(skip.detail, t);
  let reason: string;
  switch (skip.reason) {
    case "image_dropped":
      return t("{{count}}× image not taken over (question kept)", { count: skip.count });
    case "unsupported_type": {
      const label = SOURCE_TYPE_LABEL[skip.detail.toLowerCase()];
      reason = t("{{type}} (not supported)", { type: label ? t(label) : detail });
      break;
    }
    case "invalid":
      reason = detail ? t("not readable ({{detail}})", { detail }) : t("not readable");
      break;
    case "too_many_options":
      reason = t("more than 20 answer options");
      break;
    case "option_too_long":
      reason = t("answer option longer than 500 characters");
      break;
    case "text_too_long":
      reason = t("question text longer than 10,000 characters");
      break;
    case "not_allowed_in_set": {
      const label = KIND_LABEL[skip.detail];
      reason = t("{{type}} (not allowed in this set type)", {
        type: label ? t(label) : detail,
      });
      break;
    }
    case "over_limit":
      reason = t("more than 200 questions per import");
      break;
    default:
      reason = detail ? `${skip.reason} (${detail})` : skip.reason;
  }
  return t("{{count}} skipped: {{reason}}", { count: skip.count, reason });
}

export default function ImportSkipList({ skipped }: { skipped: ImportSkip[] }) {
  const { t } = useTranslation();
  if (skipped.length === 0) return null;
  return (
    <ul className="space-y-0.5 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200">
      {skipped.map((skip, index) => (
        <li key={index} className="break-words">
          {importSkipText(skip, t)}
        </li>
      ))}
    </ul>
  );
}
