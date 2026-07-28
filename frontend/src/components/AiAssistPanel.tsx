// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Small framed container for optional AI assistance. Only render it when
 * the AI is enabled (whoami.ai_enabled); the wording makes clear it's
 * optional and the suggestions are drafts to review. */
import { Sparkles } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export default function AiAssistPanel({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-brand-200 bg-brand-50/40 p-3 dark:border-brand-900 dark:bg-brand-950/30">
      <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-brand-800 dark:text-brand-200">
        <Sparkles aria-hidden className="h-4 w-4 text-brand-600 dark:text-brand-400" />
        {title}
        <span className="ml-auto text-xs font-normal text-slate-400">
          {t("Optional AI help — you decide what to use.")}
        </span>
      </p>
      {children}
    </div>
  );
}
