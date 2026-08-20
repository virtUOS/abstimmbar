// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Globe } from "lucide-react";
import { SUPPORTED_LANGUAGES, applyLangPref, getLangPref, type LangPref } from "../i18n";

/** Current language preference + a change handler. When the user is signed
 *  in, a non-"auto" choice is also persisted server-side (best-effort). */
export function useLanguage(authenticated = false) {
  const [pref, setPrefState] = useState<LangPref>(getLangPref);
  function setPref(next: LangPref) {
    applyLangPref(next, authenticated);
    setPrefState(next);
  }
  return { pref, setPref };
}

/** Language options as menu rows — used inside the account menu and the guest
 *  popover so both look identical. */
export function LanguageOptions({
  authenticated,
  onPicked,
}: {
  authenticated?: boolean;
  onPicked?: () => void;
}) {
  const { t } = useTranslation();
  const { pref, setPref } = useLanguage(authenticated);
  const rows: { code: LangPref; label: string; hint?: string }[] = [
    { code: "auto", label: t("Auto"), hint: t("(follows your system)") },
    ...SUPPORTED_LANGUAGES.map((l) => ({ code: l.code as LangPref, label: l.label })),
  ];
  return (
    <>
      {rows.map((row) => (
        <button
          key={row.code}
          type="button"
          role="menuitemradio"
          aria-checked={pref === row.code}
          onClick={() => {
            setPref(row.code);
            onPicked?.();
          }}
          className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
        >
          <span className="flex-1">
            {row.label}
            {row.hint && (
              <span className="block text-xs text-slate-400 dark:text-slate-500">
                {row.hint}
              </span>
            )}
          </span>
          {pref === row.code && <Check aria-hidden className="h-4 w-4 text-brand-600" />}
        </button>
      ))}
    </>
  );
}

/** Standalone globe picker — the single, consistent language switch for both
 *  signed-out and signed-in users. Pass ``authenticated`` so a signed-in
 *  user's choice is also persisted server-side. */
export function LanguageMenu({ authenticated }: { authenticated?: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onClick(event: MouseEvent) {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("Language")}
        className="flex h-10 w-10 items-center justify-center rounded-full text-slate-600 transition-colors duration-150 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100"
      >
        <Globe aria-hidden className="h-5 w-5" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-44 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-800"
        >
          <LanguageOptions
            authenticated={authenticated}
            onPicked={() => setOpen(false)}
          />
        </div>
      )}
    </div>
  );
}
