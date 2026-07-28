// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Small UI primitives, following Ausleihbar's calm-surface idiom. */
import { EllipsisVertical, Info, type LucideIcon } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

export function Button({
  variant = "secondary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  const styles = {
    primary:
      "bg-brand-400 text-slate-900 hover:bg-brand-500 font-semibold",
    secondary:
      "border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-900/60 font-medium",
    danger: "text-red-700 hover:bg-red-50 font-medium",
    ghost: "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800",
  }[variant];
  return (
    <button
      className={`rounded-lg px-3 py-1.5 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
}

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:bg-slate-900 dark:text-slate-100 ${props.className ?? ""}`}
    />
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">{label}</span>
      {children}
    </label>
  );
}

/** A subtle info icon whose explanation opens as a small popover on click
 * (and shows as a native tooltip on hover) (#51). Closes on outside click and
 * on Escape, like MoreMenu. Dependency-free, no tooltip framework. */
export function InfoHint({ text }: { text: string }) {
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
    <div className="relative inline-flex" ref={ref}>
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={text}
        title={text}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex rounded text-slate-500 transition-colors hover:text-slate-700 focus:outline-none focus-visible:ring-1 focus-visible:ring-brand-600 dark:text-slate-400 dark:hover:text-slate-200"
      >
        <Info aria-hidden className="h-5 w-5" />
      </button>
      {open && (
        <div
          role="note"
          className="absolute right-0 top-full z-30 mt-2 w-64 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300"
        >
          {text}
        </div>
      )}
    </div>
  );
}

/** Inline confirm rendered in place of the triggering row action. */
export function ConfirmInline({
  message,
  onConfirm,
  onCancel,
  confirmLabel,
  confirmVariant = "danger",
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
  confirmLabel?: string;
  confirmVariant?: "primary" | "secondary" | "danger" | "ghost";
}) {
  const { t } = useTranslation();
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <span className="text-slate-700 dark:text-slate-300">{message}</span>
      <Button variant={confirmVariant} onClick={onConfirm}>
        {confirmLabel ?? t("Delete")}
      </Button>
      <Button variant="ghost" onClick={onCancel}>
        {t("Cancel")}
      </Button>
    </span>
  );
}

/** A "⋮" button opening a small dropdown of actions. Closes on outside
 * click, on Escape, and after any click inside (menu items act on click). */
export function MoreMenu({
  children,
  label,
}: {
  children: ReactNode;
  label?: string;
}) {
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
  return (
    <div className="relative" ref={ref}>
      {/* Accent-colored so the actions behind it are noticed (#22). */}
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label ?? t("More actions")}
        onClick={() => setOpen((value) => !value)}
        className="rounded-lg border border-brand-300 bg-brand-50 px-3 py-1.5 text-brand-700 transition-colors hover:bg-brand-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 dark:border-brand-800 dark:bg-brand-950/40 dark:text-brand-300 dark:hover:bg-brand-900/40"
      >
        <EllipsisVertical aria-hidden className="h-4 w-4" />
      </button>
      {open && (
        <div
          role="menu"
          onClick={() => setOpen(false)}
          className="absolute right-0 z-30 mt-2 w-64 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900"
        >
          {children}
        </div>
      )}
    </div>
  );
}

/** One row inside a MoreMenu. */
export function MenuItem({
  onClick,
  children,
  danger = false,
}: {
  onClick?: () => void;
  children: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className={`flex w-full items-center gap-2 px-4 py-2 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800 ${
        danger
          ? "text-red-700 dark:text-red-400"
          : "text-slate-700 dark:text-slate-200"
      }`}
    >
      {children}
    </button>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 dark:border-slate-700 px-6 py-12 text-center">
      <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 dark:bg-brand-950 text-brand-600 dark:text-brand-300">
        <Icon aria-hidden strokeWidth={1.75} className="h-7 w-7" />
      </div>
      <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
      <div className="mt-2 text-sm text-slate-500 dark:text-slate-400">{children}</div>
    </div>
  );
}
