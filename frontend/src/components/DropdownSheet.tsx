// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Button with a menu of actions (icon, title, one-line explanation): a
 *  dropdown under the button from `sm` up, a full-screen sheet with its own
 *  title bar and ✕ on phones (a dropdown ran off the small screen). Closes on
 *  click outside and Esc. `open` is controlled so callers can open/close it
 *  from elsewhere (e.g. guided-tour signals). Used for "+ Neue Frage" and
 *  "Fragen hinzufügen" in the set editor. */
import { ChevronDown, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "./ui";

export function DropdownSheet({
  title,
  leading,
  variant = "secondary",
  open,
  onOpenChange,
  menuTour,
  children,
}: {
  /** Already translated; the button label and the phone sheet's title. */
  title: string;
  /** Shown before the label in the button (e.g. "+" or an icon). */
  leading?: ReactNode;
  variant?: "primary" | "secondary";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `data-tour` of the `role="menu"` element. */
  menuTour?: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) onOpenChange(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onOpenChange(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onOpenChange]);

  // Phones: the menu is a full-screen sheet — keep the page behind it from
  // scrolling and put the focus on its close button.
  useEffect(() => {
    if (!open || !window.matchMedia("(max-width: 639px)").matches) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <Button
        variant={variant}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="inline-flex items-center gap-2"
      >
        {leading}
        {title}
        <ChevronDown
          aria-hidden
          className={`h-4 w-4 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
      </Button>
      {open && (
        <div className="fixed inset-0 z-50 flex flex-col bg-white dark:bg-slate-950 sm:absolute sm:inset-auto sm:right-0 sm:z-30 sm:mt-2 sm:block sm:w-80 sm:overflow-hidden sm:rounded-xl sm:border sm:border-slate-200 sm:shadow-lg sm:shadow-slate-900/5 sm:dark:border-slate-700 sm:dark:bg-slate-900">
          <div className="flex shrink-0 items-center justify-between border-b border-slate-200 px-4 py-3 dark:border-slate-800 sm:hidden">
            <span className="text-base font-semibold text-slate-900 dark:text-slate-100">
              {title}
            </span>
            <button
              type="button"
              ref={closeRef}
              onClick={() => onOpenChange(false)}
              aria-label={t("Close")}
              className="-mr-2 rounded-full p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <X aria-hidden className="h-5 w-5" />
            </button>
          </div>
          <div
            role="menu"
            data-tour={menuTour}
            className="min-h-0 flex-1 overflow-y-auto py-1 sm:max-h-[75vh]"
          >
            {children}
          </div>
        </div>
      )}
    </div>
  );
}

/** One entry of a `DropdownSheet`: icon, title and a one-line explanation
 *  (both already translated). */
export function SheetMenuItem({
  icon: Icon,
  label,
  description,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800"
    >
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-brand-600 dark:text-brand-400" />
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-slate-900 dark:text-slate-100">
          {label}
        </span>
        <span className="block text-xs text-slate-500 dark:text-slate-400">{description}</span>
      </span>
    </button>
  );
}
