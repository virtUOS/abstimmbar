// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Thin Abstimmbar wrapper around @basicbar/ui's TranslatableField.
 *
 * Keeps the tool's own conventions on top of the shared component: the
 * map-based value contract (`LocalizedText` + `onChange(next)`), the
 * rich-text variant (TipTap editor — tool code, plugged in via
 * `renderInput`), easy mode (#52: non-staff simple users author in a single
 * canonical language; staff are always Pro) and the prominent form label. */
import type { ReactNode } from "react";
import {
  TranslatableField as BaseTranslatableField,
  localizedMap,
  setLocalizedLang,
  type LocalizedText,
} from "@basicbar/ui";
import { useEasyMode } from "../App";
import RichTextEditor from "./RichTextEditor";

export type TranslatableFieldVariant = "input" | "rich";

const INPUT_CLASS =
  "w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-4 focus:ring-brand-600 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-slate-950 dark:bg-slate-900 dark:text-slate-100";

interface TranslatableFieldProps {
  /** The field's current value — a legacy plain string or a `{de, en}` map. */
  value: LocalizedText;
  onChange: (next: LocalizedText) => void;
  label?: string;
  /** Accessible name when there is no visible `label` (e.g. a list row). */
  ariaLabel?: string;
  variant?: TranslatableFieldVariant;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  className?: string;
  labelAddon?: ReactNode;
  /** Extra classes appended to the input; ignored for the rich variant. */
  inputClassName?: string;
  onBlur?: () => void;
  onActiveLangChange?: (lang: "de" | "en") => void;
}

export default function TranslatableField({
  value,
  onChange,
  variant = "input",
  inputClassName = "",
  onActiveLangChange,
  ...rest
}: TranslatableFieldProps) {
  const easyMode = useEasyMode();
  return (
    <BaseTranslatableField
      {...rest}
      values={localizedMap(value)}
      onChange={(lang, text) => onChange(setLocalizedLang(value, lang, text))}
      singleLanguage={easyMode}
      format={variant === "rich" ? "html" : "text"}
      inputClass={`${INPUT_CLASS} ${inputClassName}`.trim()}
      labelClassName="text-sm font-medium text-slate-700 dark:text-slate-300"
      onActiveLangChange={
        onActiveLangChange
          ? (lang) => onActiveLangChange(lang as "de" | "en")
          : undefined
      }
      renderInput={
        variant === "rich"
          ? ({ value: html, onChange: set }) => (
              <RichTextEditor value={html} onChange={set} />
            )
          : undefined
      }
    />
  );
}
