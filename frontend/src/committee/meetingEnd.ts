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

/** Closes this window once the meeting is over (own state or a message from
 *  another window). Returns true when the window could not be closed (not
 *  script-opened): show the ended view instead. */
export function useCloseWhenEnded(setId: number, endedByState: boolean, focusOpener = false) {
  const [ended, setEnded] = useState(false);
  const [stuck, setStuck] = useState(false);
  const announced = useRef(false);

  useEffect(() => onMeetingEnded(setId, () => setEnded(true)), [setId]);
  useEffect(() => {
    if (endedByState) setEnded(true);
  }, [endedByState]);

  useEffect(() => {
    if (!ended) return;
    if (!announced.current) {
      announced.current = true;
      broadcastEnded(setId);
    }
    let timer: number | undefined;
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
    timer = window.setTimeout(() => setStuck(true), 300);
    return () => window.clearTimeout(timer);
  }, [ended, setId, focusOpener]);

  return { ended, stuck };
}
