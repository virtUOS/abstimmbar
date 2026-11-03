// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** The console's SSE stream of a running meeting (manager snapshots).
 *
 * EventSource reconnects by itself after network errors, but a connection
 * can die silently (laptop sleep, proxy), and a failed reconnect (e.g. a 502
 * during a restart) closes it for good. The server pings every 25 s; a
 * stream quiet for longer than STALE_MS, or closed, is replaced — the
 * keepalive pattern of the ballot page (`ballot.html`). */
import { useEffect, useState } from "react";
import { api, type MeetingManager } from "../api";

const STALE_MS = 60000;
const CHECK_MS = 15000;

export function useMeetingStream(setId: number | null): {
  data: MeetingManager | null;
  /** True while the stream is lost and being re-established. */
  lost: boolean;
  /** Apply a snapshot an API call returned (before the stream echoes it). */
  apply: (next: MeetingManager) => void;
} {
  const [data, setData] = useState<MeetingManager | null>(null);
  const [lost, setLost] = useState(false);

  useEffect(() => {
    if (setId === null) return;
    let stopped = false;
    let source: EventSource | null = null;
    let lastSeen = 0;
    let retryTimer: number | undefined;
    let retryDelay = 1000;

    function connect() {
      if (stopped) return;
      source?.close();
      window.clearTimeout(retryTimer);
      retryTimer = undefined;
      const es = new EventSource(api.meetingStreamUrl(setId!), { withCredentials: true });
      source = es;
      lastSeen = Date.now();
      es.onopen = () => {
        lastSeen = Date.now();
        retryDelay = 1000;
        setLost(false);
      };
      es.onmessage = (event) => {
        lastSeen = Date.now();
        setLost(false);
        setData(JSON.parse(event.data));
      };
      es.addEventListener("ping", () => {
        lastSeen = Date.now();
      });
      es.onerror = () => {
        if (es !== source) return;
        setLost(true);
        if (es.readyState === EventSource.CLOSED) reconnectLater();
      };
    }
    function reconnectLater() {
      if (retryTimer !== undefined || stopped) return;
      retryTimer = window.setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30000);
    }
    function ensureLive() {
      if (!source || stopped) return;
      if (source.readyState === EventSource.CLOSED || Date.now() - lastSeen > STALE_MS) {
        setLost(true);
        connect();
      }
    }
    const onVisible = () => {
      if (document.visibilityState === "visible") ensureLive();
    };

    connect();
    const check = window.setInterval(ensureLive, CHECK_MS);
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", ensureLive);
    return () => {
      stopped = true;
      window.clearInterval(check);
      window.clearTimeout(retryTimer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", ensureLive);
      source?.close();
    };
  }, [setId]);

  return { data, lost, apply: setData };
}
