// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Outlet, matchPath, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { driver } from "driver.js";
import type { Driver } from "driver.js";
import "./driverTheme.css";
import {
  PAGE_PATTERNS,
  type AutoPerform,
  type NavigateTarget,
  type TourMode,
  type TourPage,
  type TourStep,
  tourFor,
} from "./steps";
import { resolveExampleSetId } from "./resolveExampleSet";
import { api } from "../api";

/** How long to wait for a step's target element to appear before pausing. */
const TARGET_TIMEOUT_MS = 6000;
/** Polling fallback interval (belt-and-braces alongside the MutationObserver). */
const TARGET_POLL_MS = 200;

interface TourApi {
  active: boolean;
  startTour: (mode: TourMode, opts?: { aiEnabled?: boolean }) => void;
}

export const TourContext = createContext<TourApi | null>(null);

export function useTour(): TourApi {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within a <TourProvider>");
  return ctx;
}

/** Which tour page a pathname is on, or null for unknown routes. */
function pageFor(pathname: string): TourPage | null {
  for (const [page, pattern] of Object.entries(PAGE_PATTERNS) as [TourPage, string][]) {
    if (matchPath(pattern, pathname)) return page;
  }
  return null;
}

/** First step index for the page a pathname is on, or -1. */
function entryIndexFor(steps: TourStep[], pathname: string): number {
  const page = pageFor(pathname);
  if (!page) return -1;
  return steps.findIndex((s) => s.page === page);
}

const stripQuery = (path: string) => path.split("?")[0];

/** Route pattern of each `navigateTo` target — lets Effect A skip navigating
 *  when the user is already there (e.g. a tour started in context). */
const DEST_PATTERN: Record<NavigateTarget, string> = {
  exampleSetPresent: "/sets/:id/present",
  exampleSetResults: "/sets/:id/results",
  roomsHome: "/",
};

function matchesMilestone(step: TourStep, pathname: string): boolean {
  if (step.kind !== "action" || !step.milestone) return false;
  const m = step.milestone;
  if (m.type === "element") return false; // DOM-based; handled by its own effect
  const pattern = m.type === "present" ? "/sets/:setId/present" : m.pattern;
  return matchPath(pattern, pathname) != null;
}

export function TourProvider({
  children,
  onEnd,
}: {
  children: ReactNode;
  /** Called once when the tour ends (Task 5 wires `api.markTourSeen`). */
  onEnd?: () => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  // Current pathname for async callbacks (startTour, autoPerform, Effect A).
  const pathRef = useRef(location.pathname);
  pathRef.current = location.pathname;

  const [active, setActive] = useState(false);
  // Live `active` for async callbacks: an autoPerform resolving after the user
  // ended the tour must not re-sync/navigate. Also set synchronously in
  // startTour/end so it's correct before the next render.
  const activeRef = useRef(active);
  activeRef.current = active;
  const [mode, setMode] = useState<TourMode>("pro");
  const [aiEnabled, setAiEnabled] = useState(false);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const steps = useMemo(() => tourFor(mode, { aiEnabled }), [mode, aiEnabled]);
  const step: TourStep | undefined = active ? steps[index] : undefined;

  const driverRef = useRef<Driver | null>(null);
  // True while an action step's autoPerform is in flight — a second Next click
  // must not create a duplicate room/set.
  const autoBusyRef = useRef(false);
  // Cache the resolved example-set id for the whole run (one lookup, reused by
  // the present + results steps).
  const exampleSetIdRef = useRef<number | null | undefined>(undefined);
  const onEndRef = useRef(onEnd);
  onEndRef.current = onEnd;

  const destroyDriver = useCallback(() => {
    try {
      driverRef.current?.destroy();
    } catch {
      /* driver already torn down */
    }
    driverRef.current = null;
    // Single source of truth for the action-step interactivity class: always
    // cleared on teardown so it can never leak across a step change, pause,
    // end (Esc/✕), or unmount. highlight() re-adds it only for action steps.
    document.body.classList.remove("tour-action");
  }, []);

  const startTour = useCallback((m: TourMode, opts: { aiEnabled?: boolean } = {}) => {
    exampleSetIdRef.current = undefined; // force a fresh lookup per run
    setMode(m);
    // TourProvider sits above <App/> (TourHost), so it can't read App's whoami
    // context — the entry points (WelcomeDialog/HelpMenu) pass ai_enabled in.
    setAiEnabled(!!opts.aiEnabled);
    // Start in context: jump to the first step of the page the user is on.
    // Built from the arguments (the `steps` memo still reflects the old mode);
    // `tourFor` is the same function the memo uses, so indices agree.
    const list = tourFor(m, { aiEnabled: !!opts.aiEnabled });
    const entry = entryIndexFor(list, pathRef.current);
    if (entry < 0) navigate("/"); // unknown page → start from the overview
    setIndex(entry < 0 ? 0 : entry);
    setPaused(false);
    setToast(null);
    activeRef.current = true;
    setActive(true);
  }, [navigate]);

  const end = useCallback(() => {
    destroyDriver();
    activeRef.current = false;
    setActive(false);
    setPaused(false);
    onEndRef.current?.();
    setToast(t("You can restart the tour anytime from the ? in the header."));
    window.setTimeout(() => setToast(null), 6000);
  }, [destroyDriver, t]);

  const advance = useCallback(() => {
    setIndex((i) => {
      if (i >= steps.length - 1) {
        // Last step's Next acts as Done.
        end();
        return i;
      }
      return i + 1;
    });
  }, [steps.length, end]);

  /** Resolve a `navigateTo` target to a concrete route (async for the example
   *  set). Falls back to rooms home when no example set can be resolved. */
  const resolveRoute = useCallback(async (target: NavigateTarget): Promise<string> => {
    if (target === "roomsHome") return "/";
    if (exampleSetIdRef.current === undefined) {
      try {
        exampleSetIdRef.current = await resolveExampleSetId();
      } catch {
        exampleSetIdRef.current = null;
      }
    }
    const id = exampleSetIdRef.current;
    if (id == null) return "/"; // fallback: no example set → rooms home
    return target === "exampleSetPresent" ? `/sets/${id}/present` : `/sets/${id}/results`;
  }, []);

  /** Perform a step's action through the app's APIs/navigation (never
   *  simulated clicks) and return the destination path. Throws on failure. */
  const runAutoPerform = useCallback(
    async (ap: AutoPerform, pathname: string): Promise<string> => {
      // Local "YYYY-MM-DD HH:MM:SS": the time keeps titles unique per run — the
      // server rejects duplicate room titles per user / set titles per room.
      const now = new Date();
      const p2 = (n: number) => String(n).padStart(2, "0");
      const stamp =
        `${now.getFullYear()}-${p2(now.getMonth() + 1)}-${p2(now.getDate())} ` +
        `${p2(now.getHours())}:${p2(now.getMinutes())}:${p2(now.getSeconds())}`;
      switch (ap.kind) {
        case "createRoom": {
          const room = await api.createRoom({
            title: { de: `Rundgang-Beispiel ${stamp}`, en: `Tour example ${stamp}` },
          });
          return `/rooms/${room.id}`;
        }
        case "createSet": {
          const m = matchPath("/rooms/:id", pathname);
          if (!m?.params.id) throw new Error("createSet: not on a room page");
          const set = await api.createQuestionSet({
            room: Number(m.params.id),
            title: { de: `Rundgang-Set ${stamp}`, en: `Tour set ${stamp}` },
            type: "live_poll",
          });
          return `/sets/${set.id}`;
        }
        case "newQuestion": {
          const m = matchPath("/sets/:id", pathname);
          if (!m?.params.id) throw new Error("newQuestion: not on a set page");
          // Same route SetPage.addQuestion() builds.
          return `/sets/${m.params.id}/questions/new?kind=single_choice`;
        }
        case "navigate":
          return await resolveRoute(ap.to);
      }
    },
    [resolveRoute],
  );

  /** "Next" on an action step: perform its action, then re-sync the tour to
   *  the first step of the page it lands on. Failure → paused pill + toast. */
  const handleAuto = useCallback(
    async (s: TourStep) => {
      if (!s.autoPerform) return advance();
      if (autoBusyRef.current) return; // already performing — ignore repeat clicks
      autoBusyRef.current = true;
      // Visual cue: grey out the popover's Next while busy. The popover is torn
      // down on both success (step change) and failure (destroyDriver), so this
      // never needs undoing.
      const nextBtn = driverRef.current?.getState("popover")?.nextButton as
        | HTMLButtonElement
        | undefined;
      if (nextBtn) {
        nextBtn.disabled = true;
        nextBtn.classList.add("driver-popover-btn-disabled");
      }
      try {
        const dest = await runAutoPerform(s.autoPerform, pathRef.current);
        if (!activeRef.current) return; // tour ended meanwhile — stay put
        const destPath = stripQuery(dest);
        // Re-sync BEFORE the router commits so the outgoing step's watchers
        // (Effect A/B/B2) are torn down first; then navigate. Fallback: plain
        // advance if the destination page is unknown.
        const entry = entryIndexFor(steps, destPath);
        setIndex(entry >= 0 ? entry : (i) => Math.min(i + 1, steps.length - 1));
        navigate(dest);
      } catch {
        if (!activeRef.current) return; // tour ended meanwhile — nothing to pause
        destroyDriver(); // no stale overlay behind the pill
        setPaused(true);
        setToast(t("Couldn’t do that automatically — try it yourself, or skip the step."));
        window.setTimeout(() => setToast(null), 6000);
      } finally {
        // Always release, so a failed attempt can be retried after Resume.
        autoBusyRef.current = false;
      }
    },
    [advance, runAutoPerform, steps, navigate, destroyDriver, t],
  );

  /** Build + show the driver popover for the current step against `element`
   *  (undefined → centered, element-less popover). */
  const highlight = useCallback(
    (s: TourStep, element: Element | undefined) => {
      destroyDriver();
      const isLast = index === steps.length - 1;
      const isAction = s.kind === "action";

      // No Back: the tour is forward-only (earlier steps may have created
      // things / navigated away); the user ends it via ✕ or Esc.
      const showButtons: ("next" | "close")[] = ["next", "close"];

      let description = t(s.bodyKey);
      if (isAction) {
        // Inline-styled so we don't depend on classes outside driverTheme.css.
        description += `<div style="margin-top:0.5rem;font-size:0.75rem;opacity:0.7">${t(
          "Do this yourself — or click Next and we’ll do it for you.",
        )}</div>`;
      }

      const d = driver({
        animate: true,
        allowClose: true,
        allowKeyboardControl: false, // we own Esc (see the keydown effect)
        // Prevent an accidental overlay click from tearing the tour down; the
        // user ends it via the ✕ / End controls.
        overlayClickBehavior: () => {},
        stagePadding: 6,
        stageRadius: 8,
      });
      driverRef.current = d;

      // Action steps: the user must reach elements OUTSIDE the spotlight (e.g. an
      // inline form the trigger opens, whose submit button sits in the dimmed
      // area). driver.js otherwise inerts the whole page (`.driver-active *` →
      // pointer-events:none) and its overlay <svg> mask captures clicks. This
      // class (see driverTheme.css) re-enables the page and lets the overlay pass
      // clicks through, while the popover stays clickable and the spotlight stays
      // visible. destroyDriver() removes it; info steps keep the blocking modal.
      if (isAction) document.body.classList.add("tour-action");

      d.highlight({
        element,
        // Action steps must keep their target clickable (it's the thing the
        // user acts on); driver leaves the spotlighted element interactive.
        disableActiveInteraction: false,
        popover: {
          title: t(s.titleKey),
          description,
          showButtons,
          // Explicit side only where a step needs it; otherwise driver
          // auto-positions.
          ...(s.popoverSide ? { side: s.popoverSide } : {}),
          // Next is always enabled. On action steps it performs the step's
          // action for the user (handleAuto). If the user does the step
          // themselves while the tour is running, its milestone advances it
          // (Effect B for routes, B2 for elements). While paused, B2 is off;
          // a navigation then re-syncs the tour to the new page (Effect C).
          disableButtons: [],
          nextBtnText: isLast ? t("Finish") : t("Next"),
          onNextClick: () => (isAction ? void handleAuto(s) : advance()),
          onCloseClick: () => end(),
        },
      });
    },
    [destroyDriver, index, steps.length, t, advance, handleAuto, end],
  );

  // --- Effect A: present the current step (navigate → wait for target → show).
  useEffect(() => {
    if (!active || paused || !step) return;
    const current = step;
    let cancelled = false;
    let observer: MutationObserver | null = null;
    let pollTimer: number | undefined;
    let timeoutTimer: number | undefined;

    const clearWaiters = () => {
      observer?.disconnect();
      observer = null;
      if (pollTimer !== undefined) window.clearInterval(pollTimer);
      if (timeoutTimer !== undefined) window.clearTimeout(timeoutTimer);
      pollTimer = undefined;
      timeoutTimer = undefined;
    };

    const run = async () => {
      if (current.navigateTo) {
        // Already there (e.g. tour started in context) → don't navigate again.
        const already = matchPath(DEST_PATTERN[current.navigateTo], pathRef.current) != null;
        if (!already) {
          const route = await resolveRoute(current.navigateTo);
          if (cancelled) return;
          navigate(route);
          // Let the router commit + the destination mount before we hunt for
          // the target (which usually lives on that new page).
          await new Promise((r) => window.setTimeout(r, 0));
          if (cancelled) return;
        }
      }

      if (current.target === null) {
        if (cancelled) return;
        highlight(current, undefined);
        return;
      }

      const selector = `[data-tour="${current.target}"]`;
      const found = (el: Element) => {
        if (cancelled) return;
        clearWaiters();
        highlight(current, el);
      };

      const existing = document.querySelector(selector);
      if (existing) {
        found(existing);
        return;
      }

      observer = new MutationObserver(() => {
        const el = document.querySelector(selector);
        if (el) found(el);
      });
      observer.observe(document.body, { childList: true, subtree: true });
      pollTimer = window.setInterval(() => {
        const el = document.querySelector(selector);
        if (el) found(el);
      }, TARGET_POLL_MS);
      timeoutTimer = window.setTimeout(() => {
        if (cancelled) return;
        clearWaiters();
        destroyDriver(); // no stale overlay behind the paused pill
        setPaused(true);
      }, TARGET_TIMEOUT_MS);
    };

    void run();

    return () => {
      cancelled = true;
      clearWaiters();
      // Tear down THIS step's driver overlay before the next step's run() begins
      // its (possibly async) navigate/target-wait, so a stale dark backdrop +
      // popover (pointing at a now-unmounted element) never lingers over a wait
      // or the paused pill. driver.js appends to <body> outside React, so
      // nothing else removes it.
      destroyDriver();
    };
  }, [active, paused, step, navigate, resolveRoute, highlight, destroyDriver]);

  // --- Effect B: auto-advance an action step when its ROUTE milestone matches.
  useEffect(() => {
    if (!active || !step) return;
    if (matchesMilestone(step, location.pathname)) advance();
  }, [active, step, location.pathname, advance]);

  // --- Effect B2: auto-advance an action step with an ELEMENT milestone when a
  // `[data-tour="<anchor>"]` element appears (e.g. clicking ‘New room’ opens the
  // inline form → its ‘Create’ button mounts). Mirrors the target-wait watcher
  // (MutationObserver + poll), but waits indefinitely like a route milestone (no
  // timeout/pause). Cleaned up on step change / pause / end / unmount.
  useEffect(() => {
    if (!active || paused || !step) return;
    const milestone = step.milestone;
    if (step.kind !== "action" || milestone?.type !== "element") return;
    const selector = `[data-tour="${milestone.anchor}"]`;

    let advanced = false;
    const tryAdvance = () => {
      if (advanced) return;
      if (document.querySelector(selector)) {
        advanced = true;
        advance();
      }
    };

    tryAdvance(); // already present → advance right away
    if (advanced) return;

    const observer = new MutationObserver(tryAdvance);
    observer.observe(document.body, { childList: true, subtree: true });
    const poll = window.setInterval(tryAdvance, TARGET_POLL_MS);
    return () => {
      observer.disconnect();
      window.clearInterval(poll);
    };
  }, [active, paused, step, advance]);

  // --- Effect C: pause recovery — a location change re-attempts the step.
  // If the user left the paused step's page (e.g. did the step themselves after
  // a failed autoPerform: saved the room → /rooms/5), re-sync to the first step
  // of the page they're on instead of waiting for a target that isn't there.
  // Only in the paused branch, so it never fights a navigateTo step's own
  // navigation (the tour isn't paused then). Declared after Effect B: on the
  // same commit B's functional advance() is queued first and this plain
  // setIndex(entry) wins.
  useEffect(() => {
    if (!paused) return;
    if (active && step?.page !== pageFor(location.pathname)) {
      const entry = entryIndexFor(steps, location.pathname);
      if (entry >= 0) setIndex(entry);
    }
    setPaused(false);
    // Only react to path changes; `paused` (and active/step/steps, read from
    // this render's closure, which is current when the effect runs) are
    // intentionally NOT deps so that setting paused=true (from the timeout)
    // does not immediately clear it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  // --- Esc ends the tour (driver's own keyboard control is disabled).
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") end();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active, end]);

  // --- Tear the driver down when the tour deactivates or the provider unmounts.
  useEffect(() => {
    if (!active) destroyDriver();
    return () => destroyDriver();
  }, [active, destroyDriver]);

  const value = useMemo<TourApi>(() => ({ active, startTour }), [active, startTour]);

  return (
    <TourContext.Provider value={value}>
      {children}
      {active && paused && (
        <div
          className="fixed inset-x-0 bottom-4 z-[10000] flex justify-center px-4"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-3 rounded-full border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            <span>{t("Tour paused")}</span>
            <button
              type="button"
              className="font-semibold text-brand-600 hover:text-brand-700 dark:text-brand-400 dark:hover:text-brand-300"
              onClick={() => setPaused(false)}
            >
              {t("Resume")}
            </button>
            {/* Safety net: always advance past an unexpectedly missing target so
                the tour can never dead-end before the final step. Clear paused so
                Effect A presents the next step (its guard returns while paused). */}
            <button
              type="button"
              className="text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
              onClick={() => {
                setPaused(false);
                advance();
              }}
            >
              {t("Skip step")}
            </button>
            <button
              type="button"
              className="text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200"
              onClick={end}
            >
              {t("End")}
            </button>
          </div>
        </div>
      )}
      {toast && (
        <div
          // Stack above the paused pill (also bottom-4) so it never covers
          // the pill's Resume / Skip step / End buttons.
          className={`fixed inset-x-0 ${active && paused ? "bottom-20" : "bottom-4"} z-[10000] flex justify-center px-4`}
          role="status"
          aria-live="polite"
        >
          <div className="max-w-sm rounded-lg border border-slate-300 bg-white px-4 py-2 text-center text-sm text-slate-700 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            {toast}
          </div>
        </div>
      )}
    </TourContext.Provider>
  );
}

/** Pathless layout route: keeps the TourProvider (tour state + driver overlay)
 *  mounted across the app-shell ↔ present/quiz boundary. */
export function TourHost() {
  return (
    <TourProvider>
      <Outlet />
    </TourProvider>
  );
}
