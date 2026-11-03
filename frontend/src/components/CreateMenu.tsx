// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** "+ New …" button that lets the user pick a kind up front (#75): a menu of
 *  options with icon, label and one-line description. With fewer than two
 *  options there is nothing to pick, so it collapses to a plain button. Used
 *  for new question sets and new rooms. */
import { ChevronDown, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "./ui";

export interface CreateMenuOption<T extends string> {
  value: T;
  /** Already translated. */
  label: string;
  /** Already translated. */
  description: string;
  icon: LucideIcon;
}

export function CreateMenu<T extends string>({
  label,
  options,
  onPick,
}: {
  /** Already translated, without the leading "+". */
  label: string;
  options: CreateMenuOption<T>[];
  onPick: (value: T) => void;
}) {
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

  if (options.length < 2) {
    const only = options[0];
    return (
      <Button variant="primary" onClick={() => only && onPick(only.value)}>
        + {label}
      </Button>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="primary"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2"
      >
        <span className="text-base leading-none">+</span>
        {label}
        <ChevronDown
          aria-hidden
          className={`h-4 w-4 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-80 max-sm:fixed max-sm:inset-x-4 max-sm:w-auto overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900"
        >
          {options.map((option) => {
            const Icon = option.icon;
            return (
              <button
                key={option.value}
                type="button"
                role="menuitem"
                onClick={() => {
                  setOpen(false);
                  onPick(option.value);
                }}
                className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800"
              >
                <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {option.label}
                  </span>
                  <span className="block text-xs text-slate-500 dark:text-slate-400">
                    {option.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
