// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Meeting console (Gremien-Raum): the beamer picture fullscreen, with a
 *  collapsible side panel (agenda, attendance, beamer window, end meeting)
 *  on the right — a full-width overlay on phones. One screen is enough: the
 *  chair can share it as is, or open the panel-free beamer window
 *  (`MeetingBeamerWindow`) on a second screen. Both follow the manager
 *  stream. */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useTranslation } from "react-i18next";
import { ChevronLeft, MonitorUp, Volume2, VolumeX, PanelRightClose, PanelRightOpen, SquareStop } from "lucide-react";
import { api, requestError, type MeetingManager } from "../api";
import { Button, ConfirmDialog } from "../components/ui";
import MeetingBeamer from "./MeetingBeamer";
import MeetingAgenda from "./MeetingAgenda";
import MeetingAttendance from "./MeetingAttendance";
import { STATE_BADGE, STATE_LABEL } from "./MeetingList";
import { useMeetingStream } from "./useMeetingStream";
import { useCloseWhenEnded } from "./meetingEnd";
import { playSignal, primeSignal, readSignalEnabled, writeSignalEnabled } from "./signal";

const COLLAPSED_KEY = "abstimmbar_meeting_panel_collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    /* storage unavailable: the choice just isn't remembered */
  }
}

/** Initial snapshot (also tells a foreign/missing meeting apart), then the
 *  stream. */
function useConsoleData(setId: number) {
  const { t } = useTranslation();
  const [loadError, setLoadError] = useState("");
  const [ready, setReady] = useState(false);
  const stream = useMeetingStream(ready ? setId : null);
  const { apply } = stream;
  const refresh = useCallback(() => {
    api
      .meetingControl(setId)
      .then((snapshot) => {
        apply(snapshot);
        setReady(true);
        setLoadError("");
      })
      .catch((err) => setLoadError(t(requestError(err))));
  }, [setId, apply, t]);
  useEffect(refresh, [refresh]);
  return { ...stream, loadError, refresh };
}

function FullscreenMessage({ text, error = false }: { text: string; error?: boolean }) {
  return (
    <div className="flex h-screen items-center justify-center bg-white p-6 text-center dark:bg-slate-950">
      <p
        role={error ? "alert" : undefined}
        className={error ? "text-danger" : "text-slate-500 dark:text-slate-400"}
      >
        {text}
      </p>
    </div>
  );
}

/** Shown when the meeting is not running: over (also when the browser did not
 *  let the page close itself) or not begun yet. Neither closes the window. */
function NotRunningView({ setId, over }: { setId: number; over: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4 bg-white p-6 text-center dark:bg-slate-950">
      <p role="status" className="text-lg text-slate-700 dark:text-slate-200">
        {over ? t("The meeting has ended.") : t("The meeting has not begun yet.")}
      </p>
      <Link
        to={`/sets/${setId}`}
        className="font-semibold text-brand-700 underline dark:text-brand-300"
      >
        {t("To the meeting")}
      </Link>
    </div>
  );
}

/** `/sets/:setId/meeting/beamer`: the beamer picture only, no controls. */
export function MeetingBeamerWindow() {
  const setId = Number(useParams().setId);
  const { data, loadError } = useConsoleData(setId);
  const { ended, stuck } = useCloseWhenEnded(setId, data?.meeting.state);
  useEffect(() => {
    if (data) document.title = data.meeting.title;
  }, [data]);
  if (ended && stuck) return <NotRunningView setId={setId} over />;
  if (loadError) return <FullscreenMessage text={loadError} error />;
  if (!data) return <FullscreenMessage text="" />;
  if (!ended && data.meeting.state !== "started")
    return <NotRunningView setId={setId} over={data.meeting.state === "ended"} />;
  return (
    <div className="h-screen">
      <MeetingBeamer data={data} />
    </div>
  );
}

export default function MeetingConsole() {
  const { t } = useTranslation();
  const setId = Number(useParams().setId);
  const { data, lost, apply, loadError, refresh } = useConsoleData(setId);
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [signalOn, setSignalOn] = useState(readSignalEnabled);
  const [autoClosed, setAutoClosed] = useState(false);
  const beamerWindow = useRef<Window | null>(null);
  const { ended, stuck } = useCloseWhenEnded(setId, data?.meeting.state, true);
  const navigate = useNavigate();
  // Reached through the same-tab "Lead meeting" link and the browser refuses
  // to close it: back to the meeting page (the beamer keeps its ended view).
  useEffect(() => {
    if (ended && stuck) navigate(`/sets/${setId}`, { replace: true });
  }, [ended, stuck, navigate, setId]);

  // The shown vote closing by itself (everyone voted): notice and tone.
  const shown = data?.item?.ballot ?? null;
  const prevBallot = useRef<{ id: number; status: string } | null>(null);
  useEffect(() => {
    const prev = prevBallot.current;
    prevBallot.current = shown && { id: shown.id, status: shown.status };
    if (!shown) {
      setAutoClosed(false);
      return;
    }
    if (prev && prev.id === shown.id && prev.status === "open" && shown.status === "closed") {
      if (shown.closed_automatically) {
        setAutoClosed(true);
        if (signalOn) playSignal();
      }
    } else if (!prev || prev.id !== shown.id || shown.status === "open") {
      setAutoClosed(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown?.id, shown?.status]);

  // Audio needs a user gesture: prime it on the first click anywhere.
  useEffect(() => {
    window.addEventListener("click", primeSignal, { once: true });
    return () => window.removeEventListener("click", primeSignal);
  }, []);

  // The beamer window this console opened closes with the meeting.
  useEffect(() => {
    if (!ended) return;
    try {
      beamerWindow.current?.close();
    } catch {
      /* already gone */
    }
  }, [ended]);

  function toggleSignal() {
    const next = !signalOn;
    setSignalOn(next);
    writeSignalEnabled(next);
    if (next) primeSignal();
  }

  function toggle(next: boolean) {
    setCollapsed(next);
    writeCollapsed(next);
  }

  /** Run a console action; apply the snapshot it returns (or reload). */
  const act = useCallback(
    async (fn: () => Promise<unknown>): Promise<boolean> => {
      setError("");
      setBusy(true);
      try {
        const result = await fn();
        if (result && typeof result === "object" && "attendance" in result)
          apply(result as MeetingManager);
        else refresh();
        return true;
      } catch (err) {
        setError(t(requestError(err)));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [apply, refresh, t],
  );

  if (loadError && !data) return <FullscreenMessage text={loadError} error />;
  if (!data) return <FullscreenMessage text="" />;
  if (ended && stuck) return <FullscreenMessage text="" />;
  if (!ended && data.meeting.state !== "started")
    return <NotRunningView setId={setId} over={data.meeting.state === "ended"} />;

  const state = data.meeting.state;
  const panelId = "meeting-console-panel";

  return (
    <div className="relative flex h-screen overflow-hidden bg-white dark:bg-slate-950">
      <div className="min-w-0 flex-1">
        <MeetingBeamer data={data} />
      </div>

      {collapsed ? (
        <button
          type="button"
          onClick={() => toggle(false)}
          aria-controls={panelId}
          aria-expanded={false}
          aria-label={t("Show panel")}
          title={t("Show panel")}
          className="absolute right-0 top-1/2 z-20 -translate-y-1/2 rounded-l-xl border border-r-0 border-slate-200 bg-white px-1.5 py-4 text-slate-600 shadow-md hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          <PanelRightOpen aria-hidden className="h-5 w-5" />
        </button>
      ) : (
        <aside
          id={panelId}
          aria-label={t("Meeting")}
          className="fixed inset-0 z-30 flex flex-col bg-white dark:bg-slate-900 md:static md:inset-auto md:z-auto md:w-96 md:shrink-0 md:border-l md:border-slate-200 md:dark:border-slate-800"
        >
          <div className="grid shrink-0 gap-2 border-b border-slate-200 p-3 dark:border-slate-800">
            {data.trial && state === "started" && (
              <p
                data-testid="trial-banner"
                role="status"
                className="rounded-lg bg-amber-100 px-3 py-1.5 text-sm font-semibold text-amber-900 dark:bg-amber-900/40 dark:text-amber-200"
              >
                {t("Test run – nothing is recorded.")}
              </p>
            )}
            <div className="flex items-center gap-2">
              <Link
                to={`/sets/${setId}`}
                aria-label={t("Back")}
                title={t("Back")}
                className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 dark:text-slate-400 dark:hover:bg-slate-800"
              >
                <ChevronLeft aria-hidden className="h-5 w-5" />
              </Link>
              <h1 className="min-w-0 flex-1 truncate font-semibold text-slate-900 dark:text-slate-100">
                {data.meeting.title}
              </h1>
              <span
                className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold ${STATE_BADGE[state]}`}
              >
                {t(data.trial && state === "started" ? "Test run" : STATE_LABEL[state])}
              </span>
              <Button
                variant="ghost"
                onClick={() => toggle(true)}
                aria-controls={panelId}
                aria-expanded
                aria-label={t("Hide panel")}
                title={t("Hide panel")}
                className="px-1.5"
              >
                <PanelRightClose aria-hidden className="h-5 w-5" />
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              <Button
                onClick={() => {
                  beamerWindow.current = window.open(
                    `/sets/${setId}/meeting/beamer`,
                    `meeting-beamer-${setId}`,
                  );
                }}
                className="inline-flex items-center gap-1.5"
              >
                <MonitorUp aria-hidden className="h-4 w-4" />
                {t("Open beamer window")}
              </Button>
              <Button
                variant="ghost"
                role="switch"
                aria-checked={signalOn}
                onClick={toggleSignal}
                title={t("Signal tone when a vote closes automatically")}
                className="inline-flex items-center gap-1.5"
              >
                {signalOn ? (
                  <Volume2 aria-hidden className="h-4 w-4" />
                ) : (
                  <VolumeX aria-hidden className="h-4 w-4" />
                )}
                {t("Signal tone")}
              </Button>
              {state === "started" && (
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => setConfirmEnd(true)}
                  className="inline-flex items-center gap-1.5 border border-red-200 dark:border-red-900"
                >
                  <SquareStop aria-hidden className="h-4 w-4" />
                  {data.trial ? t("End test run") : t("End meeting")}
                </Button>
              )}
            </div>
            {autoClosed && (
              <p
                role="status"
                data-testid="auto-closed-notice"
                className="rounded-lg bg-emerald-100 px-3 py-1.5 text-sm font-semibold text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200"
              >
                {t("Everyone has voted – the vote was closed automatically.")}
              </p>
            )}
            {lost && (
              <p role="status" className="text-xs text-amber-700 dark:text-amber-400">
                {t("Connection lost – reconnecting…")}
              </p>
            )}
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
          </div>
          <div className="grid min-h-0 flex-1 content-start gap-6 overflow-y-auto p-3">
            <MeetingAgenda
              setId={setId}
              data={data}
              busy={busy}
              act={act}
              apply={apply}
              onRefresh={refresh}
            />
            <MeetingAttendance setId={setId} data={data} busy={busy} act={act} />
          </div>
        </aside>
      )}

      {confirmEnd && (
        <ConfirmDialog
          message={
            data.trial
              ? t(
                  "All votes, attendance and versions of the test run will be deleted. The agenda returns to its state before the test run.",
                )
              : t("End the meeting? All personal links become invalid afterwards.")
          }
          confirmLabel={data.trial ? t("End test run") : t("End meeting")}
          onConfirm={() => {
            setConfirmEnd(false);
            void act(() => api.endMeeting(setId));
          }}
          onCancel={() => setConfirmEnd(false)}
        />
      )}
    </div>
  );
}
