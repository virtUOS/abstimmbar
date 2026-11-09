// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** The end of a meeting, across windows: whoever sees it first posts
 *  `{type: "ended"}` on a BroadcastChannel; console and beamer window close
 *  themselves (or show an ended view if the browser refuses), the meeting
 *  page reloads its summary. */
import { useEffect, useRef, useState } from "react";

const channelName = (setId: number) => `abstimmbar-meeting-${setId}`;

export function broadcastEnded(setId: number): void {
  if (typeof BroadcastChannel === "undefined") return;
  try {
    const channel = new BroadcastChannel(channelName(setId));
    channel.postMessage({ type: "ended" });
    channel.close();
  } catch {
    /* no cross-window notice; each page still follows its own stream */
  }
}

/** Call `callback` when another window reports the end; returns unsubscribe. */
export function onMeetingEnded(setId: number, callback: () => void): () => void {
  if (typeof BroadcastChannel === "undefined") return () => undefined;
  try {
    const channel = new BroadcastChannel(channelName(setId));
    channel.onmessage = (event) => {
      if (event.data?.type === "ended") callback();
    };
    return () => channel.close();
  } catch {
    return () => undefined;
  }
}

/** Closes this window when it sees the meeting go from "started" to anything
 *  else (end, or a test run's reset), or when another window reports it. Only
 *  a transition seen by this page counts: the first snapshot never does, so a
 *  stale link to a draft or finished meeting neither closes nor broadcasts.
 *  `stuck` is true when the browser refused to close the window (not
 *  script-opened): show the ended view instead. */
export function useCloseWhenEnded(setId: number, state: string | undefined, focusOpener = false) {
  const [ended, setEnded] = useState(false);
  const [stuck, setStuck] = useState(false);
  const previous = useRef<string | undefined>(undefined);

  useEffect(() => onMeetingEnded(setId, () => setEnded(true)), [setId]);
  useEffect(() => {
    const before = previous.current;
    previous.current = state;
    if (before === "started" && state !== undefined && state !== "started") {
      setEnded(true);
      broadcastEnded(setId);
    }
  }, [state, setId]);

  useEffect(() => {
    if (!ended) return;
    try {
      if (focusOpener) window.opener?.focus();
    } catch {
      /* best effort */
    }
    try {
      window.close();
    } catch {
      /* refused */
    }
    const timer = window.setTimeout(() => setStuck(true), 300);
    return () => window.clearTimeout(timer);
  }, [ended, focusOpener]);

  return { ended, stuck };
}
