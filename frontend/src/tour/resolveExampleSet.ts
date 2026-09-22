// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { api } from "../api";

/** Pick the user's richest set (most questions) — the #78 example set has one
 *  question of every kind; a just-created set has ~1. Returns its id, or null
 *  if the user has no sets with questions. No backend change: reuses
 *  `listRooms` + `listQuestionSets` (both paginated → `.results`) and the
 *  `QuestionSet.question_count` field. */
export async function resolveExampleSetId(): Promise<number | null> {
  const rooms = (await api.listRooms(true)).results;
  let best: { id: number; count: number } | null = null;
  for (const room of rooms) {
    // `listQuestionSets` returns Paginated<QuestionSet> (api.ts); guard anyway
    // in case the shape is ever loosened to a bare array.
    const res = await api.listQuestionSets(room.id);
    const sets = Array.isArray(res) ? res : res.results;
    for (const s of sets) {
      const count = s.question_count ?? 0;
      if (!best || count > best.count) best = { id: s.id, count };
    }
  }
  return best && best.count > 0 ? best.id : null;
}
