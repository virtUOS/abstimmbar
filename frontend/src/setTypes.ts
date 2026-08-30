// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Frontend mirror of backend rooms/set_types.py (#75): per set type, its
 *  labels, the question kinds it allows, and which run action the set offers.
 *  Keep in sync with the backend registry. */
import { GraduationCap, Presentation, type LucideIcon } from "lucide-react";
import type { QuestionKind } from "./api";

export type SetType = "live_poll" | "self_paced" | "self_check";

const ALL_KINDS: QuestionKind[] = [
  "single_choice", "multiple_choice", "likert", "word_cloud",
  "open_text", "priorities", "ordering",
];

export interface SetTypeInfo {
  /** English source strings (translated via t()). */
  label: string;
  description: string;
  allowedKinds: QuestionKind[];
  /** The single run action the set offers; null = standing link (Phase 3). */
  runAction: "present" | "self_paced" | "self_check" | null;
  icon: LucideIcon;
  /** Tailwind classes for the type's accent — badge pill + room-card icon box. */
  accent: { badge: string; iconBox: string };
}

export const SET_TYPES: Record<SetType, SetTypeInfo> = {
  live_poll: {
    label: "Live poll",
    description: "Live, presenter-driven on the beamer. All question types.",
    allowedKinds: ALL_KINDS,
    runAction: "present",
    icon: Presentation,
    accent: {
      badge: "bg-brand-100 text-brand-700 dark:bg-brand-900 dark:text-brand-300",
      iconBox: "bg-brand-100 text-brand-700 dark:bg-brand-900 dark:text-brand-300",
    },
  },
  self_paced: {
    label: "Self-paced quiz",
    description: "Participants answer at their own pace in class; you start it and see the results. All question types.",
    allowedKinds: ALL_KINDS,
    runAction: "self_paced",
    icon: GraduationCap,
    accent: {
      badge: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
      iconBox: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
    },
  },
  self_check: {
    label: "Self-check",
    description: "Learners practice on their own via a link, with instant feedback.",
    allowedKinds: ["single_choice", "multiple_choice", "ordering", "open_text"],
    runAction: "self_check",
    icon: GraduationCap,
    accent: {
      badge: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
      iconBox: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    },
  },
};

/** Types a user can pick when creating a set (self_check comes in Phase 3). */
export const CREATABLE_SET_TYPES: SetType[] = ["live_poll", "self_paced"];

export function allowedKindsFor(type: SetType): QuestionKind[] {
  return SET_TYPES[type].allowedKinds;
}
