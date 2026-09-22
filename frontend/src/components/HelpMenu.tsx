// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Header "?" menu: entry point into the guided tour. Mirrors UserMenu's
 *  open/close + outside-click pattern (App.tsx) and is styled like the
 *  neighboring Settings link. */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { HelpCircle } from "lucide-react";
import { useTour } from "../tour/TourController";

export default function HelpMenu({ easyMode }: { easyMode: boolean }) {
  const { t } = useTranslation();
  const { startTour } = useTour();
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

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        data-tour="header.help"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("Help")}
        title={t("Help")}
        className="rounded-full p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-200"
      >
        <HelpCircle aria-hidden className="h-5 w-5" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-56 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900"
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              startTour(easyMode ? "easy" : "pro");
              setOpen(false);
            }}
            className="block w-full px-3 py-2.5 text-left text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {t("Start tour")}
          </button>
          {/* TODO(guide-link): no in-app guide/info page exists yet —
              docs/anleitung-lehrende.md lives only in the repo, and the
              admin-managed pages/:slug route has no guaranteed lecturer-guide
              slug. Add a "Guide" menuitem here once an in-app target ships. */}
        </div>
      )}
    </div>
  );
}
