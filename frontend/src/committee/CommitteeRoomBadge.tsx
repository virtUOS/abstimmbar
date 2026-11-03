// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Marks a committee room (Gremien-Raum) wherever a standard room shows its
 *  join code: committee members enter via personal links instead. */
import { Landmark } from "lucide-react";
import { useTranslation } from "react-i18next";

export function CommitteeRoomBadge({ className = "" }: { className?: string }) {
  const { t } = useTranslation();
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-lg bg-indigo-100 px-2 py-1 text-sm font-semibold text-indigo-800 dark:bg-indigo-900/50 dark:text-indigo-200 ${className}`}
    >
      <Landmark aria-hidden className="h-4 w-4 shrink-0 opacity-80" />
      {t("Committee room")}
    </span>
  );
}
