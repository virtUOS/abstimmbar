// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Renders server-sanitized rich HTML (common.html_sanitize allowlist).
 * The backend is the security boundary: every rich field is cleaned on
 * save/import, so the stored HTML is safe to inject here. Replaces <Markdown>
 * for authored content (#49). */

export default function RichText({
  html,
  className,
}: {
  html: string;
  className?: string;
}) {
  // A caller-supplied className fully REPLACES the default styling (it is not
  // appended), so a migrated call site can render byte-identically to its
  // previous markup — the presenter uses large-display classes (text-3xl,
  // [&_img]:max-h-64, [&_ul]:pl-8) that would clash with the prose default.
  // Sites that pass nothing (MR-B descriptions) get a sane prose default.
  const cls =
    className ??
    "text-slate-700 dark:text-slate-300 [&_img]:max-w-full [&_img]:h-auto [&_p]:my-2 " +
    "[&_ul]:list-disc [&_ul]:pl-6 [&_ol]:list-decimal [&_ol]:pl-6 [&_li]:my-0.5 " +
    "[&_h2]:mt-4 [&_h2]:mb-1 [&_h2]:text-xl [&_h2]:font-bold [&_h2]:text-slate-900 dark:[&_h2]:text-slate-100 " +
    "[&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:text-slate-900 dark:[&_h3]:text-slate-100 " +
    "[&_a]:font-medium [&_a]:text-brand-700 [&_a]:underline dark:[&_a]:text-brand-300 " +
    "[&_strong]:font-semibold [&_em]:italic";
  return <div className={cls} dangerouslySetInnerHTML={{ __html: html }} />;
}
