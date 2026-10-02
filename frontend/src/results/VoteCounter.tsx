// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Live feedback while a vote is open: results stay hidden (no bias), the
 * beamer shows the number of answers, bumping on each new one, and a ring
 * filling with answers relative to the connected participants. */
import { useTranslation } from "react-i18next";
import { categoryColor } from "./palette";
import { EASE } from "./motion";

const R = 42;
const C = 2 * Math.PI * R;

export default function VoteCounter({ votes, participants }: { votes: number; participants: number }) {
  const { t } = useTranslation();
  // Several answers per person (word clouds) or answers from tabs that have
  // since disconnected can outnumber the connected count — never overflow.
  const share = votes > 0 ? votes / Math.max(participants, votes) : 0;
  return (
    <div className="inline-flex items-center gap-5">
      <svg viewBox="0 0 100 100" className="h-24 w-24 -rotate-90" aria-hidden>
        <circle cx="50" cy="50" r={R} fill="none" strokeWidth="10" className="stroke-slate-100" />
        <circle
          cx="50"
          cy="50"
          r={R}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          stroke={categoryColor(0)}
          strokeDasharray={C}
          strokeDashoffset={C * (1 - share)}
          style={{ transition: `stroke-dashoffset 600ms ${EASE}` }}
        />
      </svg>
      <div className="text-left">
        <span key={votes} className="ab-bump inline-block text-6xl font-extrabold tabular-nums text-slate-900">
          {votes}
        </span>
        <p className="text-xl text-slate-600">{t("answer", { count: votes })}</p>
        {participants > 0 && (
          <p className="text-sm text-slate-400">{t("of {{count}} connected", { count: participants })}</p>
        )}
      </div>
    </div>
  );
}
