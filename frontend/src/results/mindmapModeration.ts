// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Presenter moderation of a live mind map with undo/redo (stage 2).
 *
 * Every action is sent to the server; its inverse is derived from the
 * response (merge/rename: an opaque undo blob for `unmerge`, move: the old
 * parent, add: delete the added term, hide: unhide). Actions run strictly one
 * after another (a promise queue) and the stacks are only touched inside the
 * queue, so quick Ctrl+Z presses can't race an action still in flight.
 * Redoing an add creates the term anew under a new id — later entries are
 * remapped to it. Stacks are kept per run + question. */
import { useRef, useState } from "react";
import { live } from "../api";

type Entry =
  | { kind: "add"; parent: number | null; text: string; description?: string; node: number }
  | { kind: "merge"; source: number; target: number; undo: string }
  | { kind: "move"; node: number; from: number | null; to: number | null }
  | { kind: "rename"; node: number; text: string; undo: string }
  | { kind: "hide"; node: number; hidden: boolean };

interface Stacks {
  undo: Entry[];
  redo: Entry[];
}

/** `detail` of a failed request (the API throws the JSON body as message). */
export function requestDetail(err: unknown): string {
  try {
    const parsed = JSON.parse((err as Error).message);
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* not JSON */
  }
  return String((err as Error)?.message ?? err);
}

function remap(entry: Entry, from: number, to: number): Entry {
  const r = (id: number) => (id === from ? to : id);
  const rp = (id: number | null) => (id === null ? null : r(id));
  switch (entry.kind) {
    case "add":
      return { ...entry, parent: rp(entry.parent), node: r(entry.node) };
    case "merge":
      return { ...entry, source: r(entry.source), target: r(entry.target) };
    case "move":
      return { ...entry, node: r(entry.node), from: rp(entry.from), to: rp(entry.to) };
    case "rename":
    case "hide":
      return { ...entry, node: r(entry.node) };
  }
}

export function useMindmapModeration(
  runId: number | null | undefined,
  questionId: number | null | undefined,
  {
    onError,
    onInfo,
    onAction,
  }: {
    /** A request failed (`detail` from the server, untranslated). */
    onError: (detail: string) => void;
    /** Something worth telling that isn't an error (untranslated key). */
    onInfo?: (message: string) => void;
    /** Any moderation action was taken (e.g. to dismiss the hint). */
    onAction?: () => void;
  },
) {
  const all = useRef(new Map<string, Stacks>());
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const [, setTick] = useState(0);
  const cbs = useRef({ onError, onInfo, onAction });
  cbs.current = { onError, onInfo, onAction };

  const key = runId != null && questionId != null ? `${runId}:${questionId}` : null;
  const stacksFor = (k: string) => {
    let s = all.current.get(k);
    if (!s) {
      s = { undo: [], redo: [] };
      all.current.set(k, s);
    }
    return s;
  };

  /** Runs `task` after everything queued before it. */
  const enqueue = (task: (rid: number, qid: number, stacks: Stacks) => Promise<void>) => {
    if (runId == null || questionId == null || key === null) return;
    const rid = runId;
    const qid = questionId;
    const stacks = stacksFor(key);
    queue.current = queue.current
      .then(() => task(rid, qid, stacks))
      .catch((err) => cbs.current.onError(requestDetail(err)))
      .finally(() => setTick((n) => n + 1));
  };

  /** Performs an entry (first time or redo); returns the entry as it now
   *  stands (new undo blob / new id), or null when nothing happened. */
  const perform = async (rid: number, qid: number, e: Entry, stacks: Stacks): Promise<Entry | null> => {
    switch (e.kind) {
      case "add": {
        const res = await live.mindmapAdd(rid, qid, {
          parent: e.parent,
          text: e.text,
          ...(e.description ? { description: e.description } : {}),
        });
        if (res.merged) {
          cbs.current.onInfo?.("This term already exists there.");
          return null;
        }
        if (res.node_id !== e.node && e.node > 0) {
          stacks.undo = stacks.undo.map((x) => remap(x, e.node, res.node_id));
          stacks.redo = stacks.redo.map((x) => remap(x, e.node, res.node_id));
        }
        return { ...e, node: res.node_id };
      }
      case "merge": {
        const res = await live.mindmapMerge(rid, qid, e.source, e.target);
        return { ...e, undo: res.undo };
      }
      case "move":
        await live.mindmapMove(rid, qid, e.node, e.to);
        return e;
      case "rename": {
        const res = await live.mindmapRename(rid, qid, e.node, e.text);
        return { ...e, undo: res.undo };
      }
      case "hide":
        await live.mindmapHide(rid, qid, e.node, e.hidden);
        return e;
    }
  };

  const revert = async (rid: number, qid: number, e: Entry) => {
    switch (e.kind) {
      case "add":
        await live.mindmapDelete(rid, qid, e.node);
        return;
      case "merge":
      case "rename":
        await live.mindmapUnmerge(rid, qid, e.undo);
        return;
      case "move":
        await live.mindmapMove(rid, qid, e.node, e.from);
        return;
      case "hide":
        await live.mindmapHide(rid, qid, e.node, !e.hidden);
        return;
    }
  };

  const act = (entry: Entry) => {
    cbs.current.onAction?.();
    enqueue(async (rid, qid, stacks) => {
      const done = await perform(rid, qid, entry, stacks);
      if (!done) return;
      stacks.undo.push(done);
      stacks.redo = [];
    });
  };

  const undo = () =>
    enqueue(async (rid, qid, stacks) => {
      const e = stacks.undo.pop();
      if (!e) return;
      // A failed undo (the map changed in between) is dropped: its detail
      // goes to the toast and the entry can't be redone either.
      await revert(rid, qid, e);
      stacks.redo.push(e);
    });

  const redo = () =>
    enqueue(async (rid, qid, stacks) => {
      const e = stacks.redo.pop();
      if (!e) return;
      const done = await perform(rid, qid, e, stacks);
      if (done) stacks.undo.push(done);
    });

  const current = key ? all.current.get(key) : undefined;
  return {
    add: (parent: number | null, text: string, description?: string) =>
      act({ kind: "add", parent, text, description, node: 0 }),
    merge: (source: number, target: number) => act({ kind: "merge", source, target, undo: "" }),
    move: (node: number, to: number | null, from: number | null) => {
      if (to !== from) act({ kind: "move", node, from, to });
    },
    rename: (node: number, text: string) => act({ kind: "rename", node, text, undo: "" }),
    hide: (node: number, hidden: boolean) => act({ kind: "hide", node, hidden }),
    undo,
    redo,
    canUndo: (current?.undo.length ?? 0) > 0,
    canRedo: (current?.redo.length ?? 0) > 0,
  };
}
