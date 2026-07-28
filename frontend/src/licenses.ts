// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** License choices for shared question sets (backend: QuestionSet.License). */
export const LICENSE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Keine Angabe" },
  { value: "cc0", label: "CC0 (gemeinfrei)" },
  { value: "cc-by", label: "CC BY 4.0 (Namensnennung)" },
  { value: "cc-by-sa", label: "CC BY-SA 4.0 (Namensnennung, Weitergabe gleich)" },
  { value: "cc-by-nc", label: "CC BY-NC 4.0 (Namensnennung, nicht kommerziell)" },
  {
    value: "cc-by-nc-sa",
    label: "CC BY-NC-SA 4.0 (Namensnennung, nicht kommerziell, Weitergabe gleich)",
  },
  { value: "copyright", label: "© Alle Rechte vorbehalten" },
];

/** Whether a license shows a rights-holder / author name (© and CC BY*). */
export function licenseNeedsHolder(value: string): boolean {
  return value === "copyright" || value.startsWith("cc-by");
}

export function licenseLabel(value: string): string {
  return (
    LICENSE_OPTIONS.find((option) => option.value === value)?.label ??
    "Keine Angabe"
  );
}
