// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const badge =
  "inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-amber-800 dark:border-amber-700 dark:bg-amber-900/40 dark:text-amber-300";

/** Admin-switchable "Beta" badge for the management header. With a notice it
 *  is a button that opens a small popover (outside click / Esc close it,
 *  like InfoHint); without one it is a plain label. */
export default function BetaBadge({ notice }: { notice: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  if (!notice) return <span className={badge}>{t("Beta")}</span>;

  return (
    <div className="relative inline-flex" ref={ref}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t("About the beta")}
        onClick={() => setOpen((value) => !value)}
        className={`${badge} cursor-pointer hover:bg-amber-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 dark:hover:bg-amber-900/60`}
      >
        {t("Beta")}
      </button>
      {open && (
        <div
          role="note"
          className="absolute left-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] whitespace-pre-line rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        >
          {notice}
        </div>
      )}
    </div>
  );
}
