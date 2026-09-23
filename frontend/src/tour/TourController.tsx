// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Outlet, matchPath, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { driver } from "driver.js";
import type { Driver } from "driver.js";
import "./driverTheme.css";
import { type NavigateTarget, type TourMode, type TourStep, tourFor } from "./steps";
import { resolveExampleSetId } from "./resolveExampleSet";

/** How long to wait for a step's target element to appear before pausing. */
const TARGET_TIMEOUT_MS = 6000;
/** Polling fallback interval (belt-and-braces alongside the MutationObserver). */
const TARGET_POLL_MS = 200;

interface TourApi {
  active: boolean;
  startTour: (mode: TourMode) => void;
}

export const TourContext = createContext<TourApi | null>(null);

export function useTour(): TourApi {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within a <TourProvider>");
  return ctx;
}

function matchesMilestone(step: TourStep, pathname: string): boolean {
  if (step.kind !== "action" || !step.milestone) return false;
  const m = step.milestone;
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

  const [active, setActive] = useState(false);
  const [mode, setMode] = useState<TourMode>("pro");
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const steps = useMemo(() => tourFor(mode), [mode]);
  const step: TourStep | undefined = active ? steps[index] : undefined;

  const driverRef = useRef<Driver | null>(null);
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

  const startTour = useCallback((m: TourMode) => {
    exampleSetIdRef.current = undefined; // force a fresh lookup per run
    setMode(m);
    setIndex(0);
    setPaused(false);
    setToast(null);
    setActive(true);
  }, []);

  const end = useCallback(() => {
    destroyDriver();
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

  const back = useCallback(() => {
    setPaused(false);
    setIndex((i) => Math.max(0, i - 1));
  }, []);

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

  /** Build + show the driver popover for the current step against `element`
   *  (undefined → centered, element-less popover). */
  const highlight = useCallback(
    (s: TourStep, element: Element | undefined) => {
      destroyDriver();
      const isFirst = index === 0;
      const isLast = index === steps.length - 1;
      const isAction = s.kind === "action";

      const showButtons: ("next" | "previous" | "close")[] = [];
      if (!isFirst) showButtons.push("previous");
      showButtons.push("next", "close");

      let description = t(s.bodyKey);
      if (isAction) {
        // Inline-styled so we don't depend on classes outside driverTheme.css.
        description += `<div style="margin-top:0.5rem;font-size:0.75rem;opacity:0.7">${t(
          "Do this to continue — the tour advances on its own.",
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
          disableButtons: isAction ? ["next"] : [],
          nextBtnText: isLast ? t("Finish") : t("Next"),
          prevBtnText: t("Back"),
          onNextClick: () => advance(),
          onPrevClick: () => back(),
          onCloseClick: () => end(),
        },
      });
    },
    [destroyDriver, index, steps.length, t, advance, back, end],
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
        const route = await resolveRoute(current.navigateTo);
        if (cancelled) return;
        navigate(route);
        // Let the router commit + the destination mount before we hunt for the
        // target (which usually lives on that new page).
        await new Promise((r) => window.setTimeout(r, 0));
        if (cancelled) return;
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

  // --- Effect B: auto-advance an action step when its milestone matches.
  useEffect(() => {
    if (!active || !step) return;
    if (matchesMilestone(step, location.pathname)) advance();
  }, [active, step, location.pathname, advance]);

  // --- Effect C: pause recovery — a location change re-attempts the step.
  useEffect(() => {
    if (paused) setPaused(false);
    // Only react to path changes; `paused` is intentionally NOT a dep so that
    // setting paused=true (from the timeout) does not immediately clear it.
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
          className="fixed inset-x-0 bottom-4 z-[10000] flex justify-center px-4"
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
