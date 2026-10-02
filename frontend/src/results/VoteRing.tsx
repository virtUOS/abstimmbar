// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Small progress ring for the beamer's live counter: answers relative to the
 * connected participants, coloured by share (pastel red < 50 %, yellow ≤ 80 %,
 * light green ≤ 95 %, dark green above) and flashing once when everyone has
 * answered. Results stay hidden while voting; this is the only live cue. */
import { useEffect, useRef, useState } from "react";
import { EASE } from "./motion";

const R = 40;
const C = 2 * Math.PI * R;

export function shareColor(share: number): string {
  if (share < 0.5) return "oklch(0.76 0.12 22)";
  if (share <= 0.8) return "oklch(0.86 0.13 95)";
  if (share <= 0.95) return "oklch(0.84 0.12 150)";
  return "oklch(0.60 0.14 150)";
}

export default function VoteRing({ votes, participants }: { votes: number; participants: number }) {
  // Several answers per person (word clouds) or answers from tabs that have
  // since disconnected can outnumber the connected count — never overflow.
  const share = votes > 0 ? votes / Math.max(participants, votes) : 0;
  const complete = votes > 0 && share >= 1;
  // Flash once on the transition to 100 % (not on every re-render at 100 %).
  const wasComplete = useRef(complete);
  const [flash, setFlash] = useState(0);
  useEffect(() => {
    if (complete && !wasComplete.current) setFlash((n) => n + 1);
    wasComplete.current = complete;
  }, [complete]);
  const color = shareColor(share);
  return (
    <svg
      key={flash}
      viewBox="0 0 100 100"
      className={`h-5 w-5 -rotate-90 ${flash ? "ab-ring-flash" : ""}`}
      style={{ color, transition: "color 500ms" }}
      aria-hidden
    >
      <circle cx="50" cy="50" r={R} fill="none" strokeWidth="16" className="stroke-slate-200" />
      <circle
        cx="50"
        cy="50"
        r={R}
        fill="none"
        strokeWidth="16"
        strokeLinecap="round"
        stroke="currentColor"
        strokeDasharray={C}
        strokeDashoffset={C * (1 - share)}
        style={{ transition: `stroke-dashoffset 600ms ${EASE}` }}
      />
    </svg>
  );
}
