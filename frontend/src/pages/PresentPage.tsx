// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Presentation mode (concept §6.1): a reduced fullscreen view for the
 * beamer. Keyboard-first — S start/stop, E/R results, ←/→ navigate,
 * A reveal correct answers (in "after_close" mode), Esc ends. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { Check, ChevronLeft, ChevronRight, QrCode, Timer, Users, Vote, X } from "lucide-react";
import { API_BASE_URL, api, live, type LiveState, type Question, type WordCloudAI } from "../api";
import { localizedText } from "@basicbar/ui";
import LikertResult from "../components/LikertResult";
import RichText from "../components/RichText";

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

// Live free-text verdict styling for the (always-light) beamer view.
// Evaluation categories are coloured by position; the first three are
// green/amber/red so both presets (Korrektheit, Stimmung) read naturally,
// custom scales get follow-up colours (#Freitext-Skalen).
const EVAL_COLORS = [
  { box: "border-brand-200 bg-brand-50", title: "text-brand-700", bar: "bg-brand-500" },
  { box: "border-amber-200 bg-amber-50", title: "text-amber-700", bar: "bg-amber-400" },
  { box: "border-red-200 bg-red-50", title: "text-red-700", bar: "bg-red-400" },
  { box: "border-blue-200 bg-blue-50", title: "text-blue-700", bar: "bg-blue-500" },
  { box: "border-violet-200 bg-violet-50", title: "text-violet-700", bar: "bg-violet-500" },
];

function evalLabel(verdict: string) {
  return verdict ? verdict[0].toUpperCase() + verdict.slice(1) : verdict;
}

/** Seconds until `endsAt`, ticking every 250 ms; null without deadline. */
// Countdown display: colour warns in the final seconds; long timers show
// minutes so the number on the beamer changes slowly, not every second.
function countdownColor(remaining: number) {
  if (remaining <= 10) return "text-red-600";
  if (remaining <= 20) return "text-amber-500";
  return "text-slate-700";
}
function countdownLabel(remaining: number) {
  return remaining > 60 ? `${Math.ceil(remaining / 60)} min` : `${remaining} s`;
}

function useCountdown(endsAt: string | undefined) {
  const [remaining, setRemaining] = useState<number | null>(null);
  useEffect(() => {
    if (!endsAt) {
      setRemaining(null);
      return;
    }
    const compute = () =>
      setRemaining(Math.max(0, Math.ceil((Date.parse(endsAt) - Date.now()) / 1000)));
    compute();
    const timer = window.setInterval(compute, 250);
    return () => window.clearInterval(timer);
  }, [endsAt]);
  return remaining;
}

function useEventSource(code: string | null, onState: (s: LiveState) => void) {
  useEffect(() => {
    if (!code) return;
    const source = new EventSource(live.streamUrl(code), { withCredentials: true });
    source.onmessage = (event) => onState(JSON.parse(event.data));
    return () => source.close();
  }, [code, onState]);
}

export default function PresentPage({ mode = "live" }: { mode?: "live" | "self_paced" }) {
  const { t } = useTranslation();
  const { setId } = useParams();
  const id = Number(setId);
  const navigate = useNavigate();
  const selfPaced = mode === "self_paced";

  const [questions, setQuestions] = useState<Question[]>([]);
  const [openOnShow, setOpenOnShow] = useState(false);
  const [runId, setRunId] = useState<number | null>(null);
  // Recording mode (#53): opted in on the set page (checkbox), carried here as
  // ?recording=1; live only (self-paced is already async).
  const [searchParams] = useSearchParams();
  const recording = searchParams.get("recording") === "1" && mode !== "self_paced";
  // Deep link (#7): jump straight to a specific question.
  const targetQuestionId = Number(searchParams.get("question")) || null;
  const [code, setCode] = useState<string | null>(null);
  const [state, setState] = useState<LiveState | null>(null);
  const [dialog, setDialog] = useState(false);
  // Section interstitial (v2 "Zwischenfolie"): shown when advancing into a
  // section for the first time, before its first question is called up.
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [sectionTitles, setSectionTitles] = useState<Map<number, string>>(new Map());

  // Institution logo for the beamer (shown only if the room opts in).
  useEffect(() => {
    void api.getSite().then((s) => setLogoUrl(s.logo)).catch(() => setLogoUrl(null));
  }, []);
  const beamerLogo = state?.room.show_logo && logoUrl ? logoUrl : null;
  const [interstitial, setInterstitial] = useState<{ title: string; index: number } | null>(null);
  const announcedRef = useRef<Set<number>>(new Set());
  const indexRef = useRef(-1);
  // #7 deep link: index the lobby Start should open, and a one-shot guard.
  const pendingStartIndexRef = useRef<number | null>(null);
  const appliedTargetRef = useRef(false);
  // Keyed by the deadline (not the question): re-opening the same question
  // gets a fresh opened_at/ends_at and must auto-close again.
  const autoClosedRef = useRef<string | null>(null);
  // #10: in-page prompt when advancing away from a question that was dwelled
  // on. Two cases: it was never started ("not_started" — the main worry), or
  // it is still open and left too early. Quick paging stays silent. The
  // teacher can silence the prompt for the rest of this presentation.
  const shownSinceRef = useRef<number>(Date.now());
  const openSinceRef = useRef<number | null>(null);
  const [leaveWarn, setLeaveWarn] = useState<
    { mode: "not_started" | "still_open"; go: () => void } | null
  >(null);
  const [suppressLeaveWarn, setSuppressLeaveWarn] = useState(false);
  const [dontAskAgain, setDontAskAgain] = useState(false);
  // After ending, dwell on a closing slide instead of jumping straight back
  // to the management screen (#32).
  const [ended, setEnded] = useState(false);
  // On-demand QR/join panel on the beamer (#): a scannable side panel the
  // presenter can flash without changing the vote phase. Toggled by the
  // footer icon or the "q" key; Esc closes it.
  const [showJoin, setShowJoin] = useState(false);
  // Word-cloud view cycle: raw → AI-consolidated → AI-grouped (#Wortwolke-KI).
  const [wcView, setWcView] = useState<"raw" | "consolidated" | "grouped">("raw");
  // Word-cloud reveal is a beamer-only display state, deliberately decoupled
  // from the run phase: switching to "Ergebnis" shows the interim cloud
  // WITHOUT closing the vote, so participants keep answering (only Stop/timer
  // closes it). "Frage" hides the cloud again. (This interim-results-without-
  // closing behaviour should eventually apply to every question type, but is
  // wired only for word clouds for now.)
  const [wcReveal, setWcReveal] = useState<"question" | "results">("results");
  const activeAiRef = useRef<number | null>(null);

  // --- setup: load questions, ask about old results, start the run --------
  // Easy mode (#52) is fetched here rather than via `useEasyMode()`: this
  // page is a top-level route outside App's <Outlet> (fullscreen, no header
  // shell), so the outlet context useApp() relies on is unavailable.
  useEffect(() => {
    void (async () => {
      const [page, status, setData, sectionPage, who] = await Promise.all([
        api.listQuestions(id),
        live.status(id),
        api.getQuestionSet(id),
        api.listSections(id),
        api.whoami(),
      ]);
      const easyMode = !!who.easy_mode;
      setQuestions(page.results);
      setSectionTitles(
        new Map(sectionPage.results.map((s) => [s.id, localizedText(s.title)])),
      );
      setOpenOnShow(setData.open_on_show);
      // Offer the start dialog whenever we'd otherwise touch stored answers:
      // either there are results and no run is active, OR the run we'd resume
      // already carries answers (presenter left it unfinished) — so archiving
      // is reliably offered instead of silently appending (#70).
      if (
        !easyMode &&
        !status.recently_started &&
        ((status.has_votes && !status.active_run) || status.active_run_has_votes)
      ) {
        setDialog(true); // ask before touching stored results
      } else {
        const started = await live.startRun(
          id, easyMode ? undefined : "continue", mode, recording,
        );
        setRunId(started.run);
        setCode(started.room_code);
      }
    })();
  }, [id, mode]);

  async function startAfterDialog(existing: "continue" | "delete" | "archive") {
    setDialog(false);
    const started = await live.startRun(id, existing, mode, recording);
    setRunId(started.run);
    setCode(started.room_code);
  }

  const handleState = useCallback((s: LiveState) => {
    setState(s);
  }, []);
  useEventSource(code, handleState);

  // Track which question is active (for ←/→ navigation).
  const activeId = state?.question?.id;
  indexRef.current = activeId
    ? questions.findIndex((q) => q.id === activeId)
    : indexRef.current;

  const activeKind = state?.question?.kind;
  // AI cleanup/grouping views are opt-in per question (#Wortwolke-KI).
  const aiCloud =
    activeKind === "word_cloud" && state?.question?.wordcloud_ai_enabled === true;

  // Each new question starts on the raw view. Word clouds start revealed when
  // they build live, and hidden (question only) when deferred to close (#30).
  useEffect(() => {
    setWcView("raw");
    setWcReveal(state?.question?.wordcloud_live === false ? "question" : "results");
    // Only re-run when the active question changes; reading the fresh
    // wordcloud_live off state is intentional (not a reactive dependency).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // Tell the backend to keep the live AI views fresh only while one is shown
  // (capacity); deactivate the previous question when switching away.
  useEffect(() => {
    const wantAi = aiCloud && wcView !== "raw" && activeId != null;
    const target = wantAi ? activeId! : null;
    if (activeAiRef.current === target) return;
    if (activeAiRef.current != null && runId) {
      void live.wordcloudAi(runId, activeAiRef.current, false);
    }
    if (target != null && runId) void live.wordcloudAi(runId, target, true);
    activeAiRef.current = target;
  }, [wcView, activeId, aiCloud, runId]);

  // Stop the live AI computation when leaving the presentation.
  useEffect(
    () => () => {
      if (activeAiRef.current != null && runId) {
        void live.wordcloudAi(runId, activeAiRef.current, false);
      }
    },
    [runId],
  );

  const cycleWcView = useCallback(() => {
    setWcView((v) =>
      v === "raw" ? "consolidated" : v === "consolidated" ? "grouped" : "raw",
    );
  }, []);

  const phase = state?.phase ?? "lobby";

  // A presenter tab opened via the editor's play button (window.open) keeps a
  // window.opener and can close itself; a normally-opened tab cannot, so we
  // only offer "Close window" in the former case (#deep-link-polish).
  const canCloseWindow = typeof window !== "undefined" && window.opener != null;

  const reveal = state?.reveal_answers ?? "after_close";
  const revealed = state?.revealed ?? false;
  // Only single/multiple choice have a correct answer to reveal (#82/#83).
  const hasCorrect = activeKind === "single_choice" || activeKind === "multiple_choice";
  const canReveal = hasCorrect && reveal === "after_close";
  const showCorrect =
    phase === "results" && (reveal === "immediately" || (reveal === "after_close" && revealed));

  // Countdown (v2): tick locally, auto-close once per question when time is up.
  const remaining = useCountdown(phase === "open" ? state?.ends_at : undefined);
  useEffect(() => {
    const deadline = state?.ends_at ?? null;
    if (
      runId &&
      phase === "open" &&
      remaining === 0 &&
      deadline !== null &&
      autoClosedRef.current !== deadline
    ) {
      autoClosedRef.current = deadline;
      void live.control(runId, { phase: "closed" });
      // Reveal the cloud once the timer closes voting (surfaces #30's deferred
      // cloud); the beamer display is local, so no phase change beyond closing.
      if (activeKind === "word_cloud") setWcReveal("results");
    }
  }, [remaining, phase, runId, activeKind, state?.ends_at]);

  // Track dwell time: when a new question slide appears, and when its vote
  // opens (both feed the leave prompt).
  useEffect(() => {
    shownSinceRef.current = Date.now();
  }, [activeId]);
  useEffect(() => {
    if (phase === "open") {
      if (openSinceRef.current === null) openSinceRef.current = Date.now();
    } else {
      openSinceRef.current = null;
    }
  }, [phase, activeId]);

  // --- presenter actions ----------------------------------------------------
  const goto = useCallback(
    async (index: number) => {
      if (!runId || questions.length === 0) return;
      const clamped = Math.max(0, Math.min(questions.length - 1, index));
      await live.control(runId, {
        // Set option: calling up a question can open it right away.
        phase: openOnShow ? "open" : "preview",
        question: questions[clamped].id,
      });
    },
    [runId, questions, openOnShow],
  );

  // Navigate, but first show the section interstitial when entering a
  // section for the first time this run (v2 "Zwischenfolie").
  const requestGoto = useCallback(
    (index: number) => {
      if (!runId || questions.length === 0) return;
      const clamped = Math.max(0, Math.min(questions.length - 1, index));
      const section = questions[clamped].section;
      if (section !== null && !announcedRef.current.has(section)) {
        setInterstitial({ title: sectionTitles.get(section) ?? "", index: clamped });
        return;
      }
      void goto(clamped);
    },
    [runId, questions, sectionTitles, goto],
  );

  // Start from the lobby into the armed deep-link question (#7), or the first
  // question when there is no target.
  const startFromLobby = useCallback(() => {
    const index = pendingStartIndexRef.current ?? 0;
    pendingStartIndexRef.current = null;
    requestGoto(index);
  }, [requestGoto]);

  // Once the run is ready, apply the ?question=<id> target exactly once:
  // arm the lobby Start (fresh run) or jump straight (a question already live).
  useEffect(() => {
    if (appliedTargetRef.current) return;
    if (!runId || questions.length === 0 || !state) return;
    appliedTargetRef.current = true;
    if (targetQuestionId == null) return;
    const targetIndex = questions.findIndex((q) => q.id === targetQuestionId);
    if (targetIndex < 0) return; // unknown/deleted id → normal presenter start
    if (state.question?.id != null) {
      void goto(targetIndex); // run already showing a question → jump straight
    } else {
      pendingStartIndexRef.current = targetIndex; // fresh lobby → arm Start
    }
  }, [runId, questions, state, targetQuestionId, goto]);

  const confirmInterstitial = useCallback(() => {
    if (!interstitial) return;
    const section = questions[interstitial.index]?.section;
    if (section !== null && section !== undefined) announcedRef.current.add(section);
    const target = interstitial.index;
    setInterstitial(null);
    void goto(target);
  }, [interstitial, questions, goto]);

  // Going back from a section's first question lands on the section header
  // again (#7), rather than skipping straight to the previous question.
  const goPrev = useCallback(() => {
    const idx = indexRef.current;
    const current = questions[idx];
    if (
      current &&
      current.section != null &&
      (idx === 0 || questions[idx - 1].section !== current.section)
    ) {
      setInterstitial({ title: sectionTitles.get(current.section) ?? "", index: idx });
    } else {
      requestGoto(idx - 1);
    }
  }, [questions, sectionTitles, requestGoto]);

  // Guarded "advance" (#10). Quick paging stays silent; only when a slide was
  // dwelled on do we prompt — either "you didn't start this vote" (preview,
  // > 5 s) or "the vote is still running" (open, timed with the countdown not
  // yet up, or untimed under 30 s). Silenced for the presentation on request.
  const PREVIEW_DWELL_MS = 5000;
  const OPEN_MIN_MS = 30000;
  const advanceNext = useCallback(() => {
    if (phase === "lobby") return startFromLobby();
    // Past the last question there is nothing to page to — end the run so it
    // reaches the finished state (#29), instead of clamping onto the last
    // slide and appearing to do nothing.
    const go = () =>
      indexRef.current + 1 >= questions.length
        ? void finish()
        : requestGoto(indexRef.current + 1);
    if (suppressLeaveWarn) return go();
    const now = Date.now();
    if (phase === "preview" && now - shownSinceRef.current > PREVIEW_DWELL_MS) {
      setLeaveWarn({ mode: "not_started", go });
    } else if (
      phase === "open" &&
      (state?.ends_at != null ||
        (openSinceRef.current !== null && now - openSinceRef.current < OPEN_MIN_MS))
    ) {
      setLeaveWarn({ mode: "still_open", go });
    } else {
      go();
    }
  }, [suppressLeaveWarn, phase, state?.ends_at, requestGoto, questions.length, startFromLobby]);

  // Prompt actions.
  function dismissWarn() {
    setLeaveWarn(null);
    setDontAskAgain(false);
  }
  function proceedLeave() {
    if (dontAskAgain) setSuppressLeaveWarn(true);
    const go = leaveWarn?.go;
    dismissWarn();
    go?.();
  }
  function startCurrentVote() {
    if (dontAskAgain) setSuppressLeaveWarn(true);
    dismissWarn();
    if (runId) void live.control(runId, { phase: "open" });
  }

  // Reveal-level controls for the footer pill (Frage · Ergebnisse · Lösung).
  // No-ops in lobby/finished so we never request results without a question.
  const showQuestion = useCallback(() => {
    if (runId && phase === "results") void live.control(runId, { phase: "closed" });
  }, [runId, phase]);

  const showResults = useCallback(async () => {
    if (!runId) return;
    if (phase === "results") {
      if (revealed) await live.control(runId, { reveal: false });
      return;
    }
    if (phase === "open" || phase === "closed" || phase === "preview") {
      if (phase === "open") await live.control(runId, { phase: "closed" });
      await live.control(runId, { phase: "results" });
    }
  }, [runId, phase, revealed]);

  const showSolution = useCallback(async () => {
    if (!runId) return;
    if (phase === "lobby" || phase === "finished") return; // no active question
    if (phase === "open") await live.control(runId, { phase: "closed" });
    if (phase !== "results") await live.control(runId, { phase: "results" });
    await live.control(runId, { reveal: true });
  }, [runId, phase]);

  const onKey = useCallback(
    (event: KeyboardEvent) => {
      if (!runId) return;
      const key = event.key.toLowerCase();
      // Space and Enter act as the primary "advance" key alongside S — a
      // presenter can page through with a clicker. Space must not scroll.
      if (key === " ") event.preventDefault();
      const advance = key === "s" || key === "enter" || key === " ";
      // On the closing slide (#32) any advance/Esc leaves to management.
      if (ended) {
        if (key === "escape" || advance) leavePresentation();
        return;
      }
      if (selfPaced) {
        if (key === "escape") void finish();
        return;
      }
      // While the interstitial is up, S/→/Enter/Space confirm it, Esc dismisses.
      if (interstitial) {
        if (advance || key === "arrowright") confirmInterstitial();
        else if (key === "escape") setInterstitial(null);
        return;
      }
      // The QR/join panel is a transient overlay — Esc closes it first (so it
      // doesn't end the presentation), "q" toggles it. Neither touches the
      // vote phase.
      if (key === "escape" && showJoin) {
        setShowJoin(false);
        return;
      }
      if (key === "q") {
        setShowJoin((v) => !v);
        return;
      }
      if (key === "arrowright") advanceNext();
      else if (key === "arrowleft") goPrev();
      else if (advance) {
        if (phase === "open") {
          void live.control(runId, { phase: "closed" });
          // Closing reveals the word cloud (incl. #30's deferred one); the
          // beamer display is local, so voting just stops, nothing else.
          if (activeKind === "word_cloud") setWcReveal("results");
        } else if (phase === "preview" || phase === "closed" || phase === "results")
          void live.control(runId, { phase: "open" });
        else if (phase === "lobby") startFromLobby();
      } else if (key === "e" || key === "r") {
        // Word clouds toggle the beamer cloud locally without touching the
        // vote phase (interim results stay open); other kinds reveal via phase.
        if (activeKind === "word_cloud")
          setWcReveal((v) => (v === "results" ? "question" : "results"));
        else if (phase === "results") showQuestion();
        else showResults();
      } else if (key === "a" && aiCloud) {
        // Word clouds have no correct answer — "a" cycles the AI views.
        cycleWcView();
      } else if (key === "a" && canReveal && phase === "results") {
        if (revealed) showResults();
        else showSolution();
      } else if (key === "escape") {
        void finish();
      }
    },
    [runId, phase, activeKind, requestGoto, goPrev, advanceNext, confirmInterstitial, interstitial, selfPaced, ended, aiCloud, cycleWcView, startFromLobby, showQuestion, showResults, showSolution, canReveal, revealed, showJoin],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  async function finish() {
    if (runId) await live.control(runId, { phase: "finished" });
    setEnded(true); // show the closing slide; leaving is a separate step (#32)
  }

  function leavePresentation() {
    navigate(`/sets/${id}`);
  }

  // --- rendering --------------------------------------------------------------
  if (dialog) {
    return (
      <Shell>
        <div className="mx-auto max-w-xl rounded-2xl border border-slate-200 p-8 text-center">
          <h2 className="text-2xl font-bold">
            {selfPaced
              ? t("There are already answers for this quiz")
              : t("There are already results")}
          </h2>
          <p className="mt-2 text-slate-500">
            {selfPaced
              ? t("How do you want to handle the existing answers?")
              : t("How do you want to handle the existing results?")}
          </p>
          <div className="mt-6 grid gap-2 text-left">
            <button
              className="rounded-xl bg-brand-400 px-5 py-3 font-semibold text-slate-900 hover:bg-brand-500"
              onClick={() => void startAfterDialog("continue")}
            >
              {t("Keep counting")}
              <span className="block text-sm font-normal text-slate-700">
                {selfPaced
                  ? t("New answers count into the same run.")
                  : t("New votes count into the same run.")}
              </span>
            </button>
            <button
              className="rounded-xl border border-slate-300 px-5 py-3 font-semibold hover:bg-slate-50"
              onClick={() => void startAfterDialog("archive")}
            >
              {t("Archive & restart")}
              <span className="block text-sm font-normal text-slate-500">
                {t("The existing run stays archived.")}
              </span>
            </button>
            <button
              className="rounded-xl border border-red-200 px-5 py-3 font-semibold text-red-700 hover:bg-red-50"
              onClick={() => void startAfterDialog("delete")}
            >
              {t("Delete")}
              <span className="block text-sm font-normal text-red-500/80">
                {selfPaced
                  ? t("All existing answers are discarded.")
                  : t("All existing results are discarded.")}
              </span>
            </button>
            <button
              className="mt-1 rounded-xl px-5 py-2 text-sm font-medium text-slate-500 hover:bg-slate-50"
              onClick={() => navigate(`/sets/${id}`)}
            >
              {t("Cancel")}
            </button>
          </div>
        </div>
      </Shell>
    );
  }

  // Closing slide (#32): the run is finished — dwell here until the presenter
  // actively leaves, rather than snapping back to the management screen.
  if (ended) {
    return (
      <Shell logo={beamerLogo}>
        <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
          <div className="text-7xl" aria-hidden>✅</div>
          <h1 className="text-5xl font-bold">{t("The survey has ended")}</h1>
          <p className="text-2xl text-slate-500">{t("Thanks for taking part!")}</p>
          <button
            onClick={leavePresentation}
            className="mt-4 inline-flex items-center gap-2 rounded-xl bg-brand-400 px-6 py-3 text-lg font-semibold text-slate-900 hover:bg-brand-500"
          >
            {t("Back to overview")} <Kbd>Esc</Kbd>
          </button>
        </div>
      </Shell>
    );
  }

  if (!state) return <Shell>{t("Connecting …")}</Shell>;

  // Self-paced dashboard (concept §6.3): QR for joining plus live progress;
  // participants drive themselves, the teacher only watches and ends.
  if (selfPaced) {
    const progress = state.progress ?? [];
    const denominator = Math.max(
      state.participants ?? 0,
      ...progress.map((row) => row.votes),
      1,
    );
    return (
      <Shell
        logo={beamerLogo}
        footer={
          <footer className="flex items-center justify-between border-t border-slate-200 px-6 py-3 text-sm text-slate-500">
            <span>
              <Users aria-hidden className="inline h-4 w-4" /> {state.participants ?? 0} · {state.votes_total ?? 0}{" "}
              {t("answer", { count: state.votes_total ?? 0 })}
            </span>
            <button
              className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-slate-50"
              onClick={() => void finish()}
            >
              {t("End quiz (Esc)")}
            </button>
          </footer>
        }
      >
        <div className="mx-auto flex h-full max-w-5xl flex-col justify-center gap-10 lg:flex-row lg:items-center">
          <div className="flex flex-col items-center gap-4 text-center">
            <span className="rounded-full bg-brand-50 px-3 py-1 text-sm font-semibold text-brand-700">
              {t("Self-paced quiz")}
            </span>
            <h1 className="text-3xl font-bold">{localizedText(state.set_title)}</h1>
            <img
              src={live.qrUrl(state.room.code)}
              alt={t("QR code for {{url}}", { url: live.participantUrl(state.room.code) })}
              className="h-64 w-64 rounded-2xl border border-slate-200"
            />
            <p className="text-xl text-slate-600">
              {live.participantHost(state.room.code)}
            </p>
            <p className="text-4xl font-extrabold tracking-widest text-brand-700">
              {state.room.code}
            </p>
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="mb-4 text-lg font-semibold text-slate-700">
              {t("Answers per question")}
            </h2>
            <ol className="space-y-3">
              {progress.map((row, i) => (
                <li key={row.id}>
                  <div className="mb-1 flex items-baseline justify-between gap-4">
                    <span className="truncate text-slate-700">
                      <span className="font-bold text-brand-700">{i + 1}.</span>{" "}
                      {localizedText(row.text) || t("(no text)")}
                    </span>
                    <span className="shrink-0 tabular-nums text-slate-500">
                      {row.votes}
                    </span>
                  </div>
                  <div className="h-3 rounded-md bg-slate-100">
                    <div
                      className="h-3 rounded-md bg-brand-400 transition-all duration-500"
                      style={{ width: `${Math.round((row.votes / denominator) * 100)}%` }}
                    />
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </Shell>
    );
  }

  // Section interstitial (v2 "Zwischenfolie"): a full slide with the section
  // name; the teacher confirms with S / → to call up the section's first
  // question.
  if (interstitial) {
    const target = interstitial.index;
    return (
      <Shell
        logo={beamerLogo}
        overlay={<JoinCorner room={state.room} />}
        stats={<LiveStats participants={state.participants ?? 0} votes={state.votes ?? 0} />}
        footer={
          <Footer
            phase={phase}
            participants={state.participants ?? 0}
            index={target}
            count={questions.length}
            variant="section"
            onPrev={() => {
              setInterstitial(null);
              requestGoto(target - 1);
            }}
            onNext={confirmInterstitial}
            onFinish={() => void finish()}
            onCloseWindow={canCloseWindow ? () => window.close() : undefined}
          />
        }
      >
        <div className="flex h-full flex-col items-center justify-center text-center">
          <h1 className="max-w-4xl text-6xl font-extrabold leading-tight">
            {interstitial.title}
          </h1>
        </div>
      </Shell>
    );
  }

  const question = state.question;
  const total = state.votes ?? 0;

  return (
    <Shell
      logo={beamerLogo}
      overlay={
        phase !== "lobby" ? (
          <>
            <JoinCorner room={state.room} />
            {state.recording_token && question && (
              <RecordingCorner
                room={state.room}
                token={state.recording_token}
                questionId={question.id}
              />
            )}
            {showJoin && (
              <JoinPanel room={state.room} onClose={() => setShowJoin(false)} />
            )}
          </>
        ) : null
      }
      stats={<LiveStats participants={state.participants ?? 0} votes={state.votes ?? 0} />}
      footer={
        <Footer
          phase={phase}
          participants={state.participants ?? 0}
          index={indexRef.current}
          count={questions.length}
          onPrev={goPrev}
          onNext={advanceNext}
          onToggle={() => {
            if (phase === "open") {
              // Stop just closes voting; for a word cloud we also reveal the
              // cloud (incl. #30's deferred one) on the beamer. Its
              // "Frage"/"Ergebnis" toggle is local and never closes the vote.
              void live.control(runId!, { phase: "closed" });
              if (activeKind === "word_cloud") setWcReveal("results");
            } else if (phase === "lobby") startFromLobby();
            else void live.control(runId!, { phase: "open" });
          }}
          revealLevel={
            activeKind === "word_cloud"
              ? wcReveal
              : phase === "results"
                ? revealed
                  ? "solution"
                  : "results"
                : "question"
          }
          canReveal={canReveal}
          onShowQuestion={
            activeKind === "word_cloud" ? () => setWcReveal("question") : showQuestion
          }
          onShowResults={
            activeKind === "word_cloud" ? () => setWcReveal("results") : showResults
          }
          onShowSolution={showSolution}
          views={
            aiCloud
              ? [
                  { value: "raw", label: t("Original") },
                  { value: "consolidated", label: t("Cleaned up") },
                  { value: "grouped", label: t("Grouped") },
                ]
              : undefined
          }
          viewValue={wcView}
          onSelectView={(v) => setWcView(v as "raw" | "consolidated" | "grouped")}
          joinShown={showJoin}
          onToggleJoin={() => setShowJoin((v) => !v)}
          onFinish={() => void finish()}
          onCloseWindow={canCloseWindow ? () => window.close() : undefined}
        />
      }
    >
      {leaveWarn && (
        <div className="fixed inset-0 z-30 flex items-center justify-center bg-slate-900/40 p-6">
          <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-xl">
            <h2 className="text-xl font-bold text-slate-900">
              {leaveWarn.mode === "not_started"
                ? t("Question not started")
                : t("Vote still running")}
            </h2>
            <p className="mt-2 text-slate-600">
              {leaveWarn.mode === "not_started"
                ? t("This question hasn't been opened for voting yet.")
                : t("The current question is still open. Really move on?")}
            </p>
            <label className="mt-4 flex items-center justify-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                checked={dontAskAgain}
                onChange={(event) => setDontAskAgain(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 accent-brand-600"
              />
              {t("Don't ask again in this presentation")}
            </label>
            <div className="mt-5 flex flex-wrap justify-center gap-3">
              <button
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                onClick={dismissWarn}
              >
                {t("Cancel")}
              </button>
              {leaveWarn.mode === "not_started" && (
                <button
                  className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  onClick={proceedLeave}
                >
                  {t("Continue anyway")}
                </button>
              )}
              <button
                className="rounded-lg bg-brand-400 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-brand-500"
                onClick={leaveWarn.mode === "not_started" ? startCurrentVote : proceedLeave}
              >
                {leaveWarn.mode === "not_started" ? t("Start voting") : t("Continue")}
              </button>
            </div>
          </div>
        </div>
      )}
      {phase === "lobby" && (
        <div className="flex h-full flex-col items-center justify-center gap-6 text-center">
          <h1 className="text-4xl font-bold">{localizedText(state.set_title)}</h1>
          <img
            src={live.qrUrl(state.room.code)}
            alt={t("QR code for {{url}}", { url: live.participantUrl(state.room.code) })}
            className="h-72 w-72 rounded-2xl border border-slate-200"
          />
          <p className="text-2xl text-slate-600">
            {live.participantHost(state.room.code)}
          </p>
          <p className="text-5xl font-extrabold tracking-widest text-brand-700">
            {state.room.code}
          </p>
          <p className="text-slate-400">
            {state.participants ?? 0}{" "}
            <Trans i18nKey="present_lobby_hint">
              connected · First question with <Kbd>S</Kbd> or <Kbd>→</Kbd>
            </Trans>
          </p>
          {/* Recording mode (#53): enabled on the set page; just confirm here. */}
          {state.recording_token && (
            <p className="text-sm font-semibold text-brand-700">
              ● {t("Recording on — viewers can vote later via the per-question QR code.")}
            </p>
          )}
        </div>
      )}

      {question && phase !== "lobby" && (
        <div className="mx-auto flex h-full max-w-4xl flex-col justify-center">
          {phase === "open" && remaining !== null && (
            <div
              className={`fixed left-6 top-4 z-20 flex items-center gap-2 text-5xl font-extrabold tabular-nums ${countdownColor(remaining)}`}
            >
              <Timer aria-hidden className="h-9 w-9" /> {countdownLabel(remaining)}
            </div>
          )}
          <RichText
            className="text-3xl font-semibold leading-snug [&_img]:my-4 [&_img]:max-h-64 [&_ul]:list-disc [&_ul]:pl-8"
            html={localizedText(question.text)}
          />

          {question.kind !== "word_cloud" && question.kind !== "open_text" && phase !== "results" && (
            <ol className="mt-8 space-y-3">
              {question.options.map((option, i) => (
                <li key={option.id} className="flex items-center gap-4 rounded-2xl border border-slate-200 px-5 py-3 text-2xl">
                  <span className="font-bold text-brand-700">{LETTERS[i]}</span>
                  {option.image && (
                    <img
                      src={`${API_BASE_URL}${option.image}`}
                      alt=""
                      className="max-h-28 rounded-xl"
                    />
                  )}
                  {localizedText(option.text)}
                </li>
              ))}
            </ol>
          )}

          {question.kind === "likert" && state.likert && phase === "results" && (
            state.before?.likert ? (
              // Before/after pair (#54): before over after, before dimmed.
              <div className="space-y-6">
                <div>
                  <span className="mb-1 block text-lg font-semibold uppercase tracking-wide text-slate-400">
                    {t("Before")}
                  </span>
                  <div className="opacity-70">
                    <LikertResult summary={state.before.likert} variant="present" />
                  </div>
                </div>
                <div>
                  <span className="mb-1 block text-lg font-semibold uppercase tracking-wide text-slate-400">
                    {t("After")}
                  </span>
                  <LikertResult summary={state.likert} variant="present" />
                </div>
              </div>
            ) : (
              <LikertResult summary={state.likert} variant="present" />
            )
          )}

          {question.kind === "priorities" && state.priorities && phase === "results" && (
            <div className="mt-8 space-y-3">
              {state.priorities.map((opt) => (
                <div key={opt.id}>
                  <div className="mb-1 flex items-center justify-between text-xl">
                    <span>{localizedText(opt.text)}</span>
                    <span className="tabular-nums text-slate-500">
                      Ø {opt.avg} · {opt.min}–{opt.max}
                    </span>
                  </div>
                  <div className="relative h-6 rounded bg-slate-100 dark:bg-slate-800">
                    {/* average fill (green) */}
                    <div
                      className="absolute inset-y-0 left-0 rounded bg-brand-500"
                      style={{ width: `${opt.avg}%` }}
                    />
                    {/* deviation range line, drawn on top so the min side is visible */}
                    <div
                      className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-slate-700 dark:bg-slate-200"
                      style={{ left: `${opt.min}%`, width: `${Math.max(opt.max - opt.min, 0)}%` }}
                    />
                    {/* min / max whiskers, sticking out above and below the bar */}
                    <div
                      className="absolute -top-1 -bottom-1 w-0.5 -translate-x-1/2 bg-slate-700 dark:bg-slate-200"
                      style={{ left: `${opt.min}%` }}
                    />
                    <div
                      className="absolute -top-1 -bottom-1 w-0.5 -translate-x-1/2 bg-slate-700 dark:bg-slate-200"
                      style={{ left: `${opt.max}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}

          {question.kind === "ordering" && state.ordering && phase === "results" && (
            <div className="mt-8">
              <p className="mb-4 text-xl font-semibold">
                {t("{{pct}}% got the full order correct", { pct: state.ordering.full_correct_rate })}
              </p>
              <div className="inline-grid gap-x-3" style={{ gridTemplateColumns: "max-content auto" }}>
                {state.ordering.items.flatMap((it, i) => {
                  const link = state.ordering!.links?.[i];
                  const rows = [
                    <div
                      key={`item-${it.id}`}
                      className="col-start-1 flex items-center gap-3 text-xl"
                      style={{ gridRow: 2 * i + 1 }}
                    >
                      <span className="tabular-nums text-slate-400">{it.correct_position}.</span>
                      <span>{localizedText(it.text)}</span>
                    </div>,
                  ];
                  if (link) {
                    rows.push(
                      <div
                        key={`link-${it.id}`}
                        className="col-start-1 flex items-center justify-center py-1"
                        style={{ gridRow: 2 * i + 2 }}
                      >
                        <span
                          className="rounded-full bg-slate-100 px-2 py-0.5 text-xs tabular-nums text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                          style={{ opacity: 0.4 + 0.6 * (link.rate / 100) }}
                        >
                          {t("{{pct}}% in a row", { pct: link.rate })}
                        </span>
                      </div>,
                    );
                  }
                  return rows;
                })}
                {state.ordering.chains.map((c, idx) => (
                  <div
                    key={`chain-${idx}`}
                    className="col-start-2 flex items-center gap-2 pl-1"
                    style={{ gridRow: `${2 * c.start + 1} / ${2 * c.end + 2}` }}
                  >
                    <div className="h-full w-2 rounded-r-lg border-y-2 border-r-2 border-brand-400" />
                    <span className="text-sm font-medium tabular-nums text-brand-700 dark:text-brand-300">
                      {c.rate}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {question.kind !== "word_cloud" && question.kind !== "open_text" &&
            question.kind !== "priorities" && question.kind !== "ordering" &&
            !(question.kind === "likert" && state.likert) && phase === "results" && (
            <div className="mt-8 space-y-3">
              {(state.results ?? []).map((option, i) => {
                const count = option.count ?? 0;
                const percent = total ? Math.round((count / total) * 100) : 0;
                const correct = showCorrect && option.is_correct;
                // Before/after pair (#54): before bar (lighter) over after bar.
                const before = state.before;
                const beforeTotal = before?.votes ?? 0;
                const beforeCount = before?.results?.[i]?.count ?? 0;
                const beforePercent = beforeTotal
                  ? Math.round((beforeCount / beforeTotal) * 100)
                  : 0;
                return (
                  <div key={option.id}>
                    <div className="mb-1 flex items-center justify-between text-xl">
                      <span className={`flex items-center gap-2 ${correct ? "font-bold text-brand-700" : ""}`}>
                        {LETTERS[i]} ·{" "}
                        {option.image && (
                          <img
                            src={`${API_BASE_URL}${option.image}`}
                            alt=""
                            className="max-h-12 rounded-lg"
                          />
                        )}
                        {localizedText(option.text)} {correct && <Check aria-hidden className="inline h-4 w-4" />}
                      </span>
                      {!before && (
                        <span className="tabular-nums text-slate-500">
                          {count} · {percent} %
                        </span>
                      )}
                    </div>
                    {before ? (
                      <div className="space-y-1.5">
                        <div className="flex items-center gap-3">
                          <span className="w-24 shrink-0 text-sm font-semibold uppercase tracking-wide text-slate-400">
                            {t("Before")}
                          </span>
                          <div className="h-5 flex-1 rounded-lg bg-slate-100">
                            <div
                              className={`h-5 rounded-lg ${correct ? "bg-brand-200" : "bg-slate-200"}`}
                              style={{ width: `${beforePercent}%` }}
                            />
                          </div>
                          <span className="w-28 text-right tabular-nums text-slate-500">
                            {beforeCount} · {beforePercent} %
                          </span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="w-24 shrink-0 text-sm font-semibold uppercase tracking-wide text-slate-400">
                            {t("After")}
                          </span>
                          <div className="h-5 flex-1 rounded-lg bg-slate-100">
                            <div
                              className={`h-5 rounded-lg transition-all duration-500 ${correct ? "bg-brand-400" : "bg-slate-300"}`}
                              style={{ width: `${percent}%` }}
                            />
                          </div>
                          <span className="w-28 text-right tabular-nums text-slate-500">
                            {count} · {percent} %
                          </span>
                        </div>
                      </div>
                    ) : (
                      <div className="h-6 rounded-lg bg-slate-100">
                        <div
                          className={`h-6 rounded-lg transition-all duration-500 ${correct ? "bg-brand-400" : "bg-slate-300"}`}
                          style={{ width: `${percent}%` }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}
              {canReveal && !revealed && (
                <p className="pt-2 text-sm text-slate-400">
                  <Trans i18nKey="present_reveal_hint">
                    Reveal correct answer with <Kbd>A</Kbd>
                  </Trans>
                </p>
              )}
            </div>
          )}

          {question.kind === "open_text" && phase === "results" && state.evaluation && (
            <div className="mt-8">
              {state.evaluation.pending > 0 && (
                <p className="mb-4 text-lg text-slate-500">
                  {state.evaluation.pending}{" "}
                  {t("answer being evaluated", { count: state.evaluation.pending })}
                </p>
              )}
              {/* Optional bar chart of the category distribution (#Freitext-Skalen). */}
              {state.evaluation.chart && (
                <div className="mx-auto mb-6 max-w-3xl space-y-3">
                  {state.evaluation.groups.map((group, i) => {
                    const total = state.evaluation!.groups.reduce((s, g) => s + g.count, 0);
                    const pct = total ? Math.round((group.count / total) * 100) : 0;
                    return (
                      <div key={group.verdict}>
                        <div className="mb-1 flex items-center justify-between text-xl">
                          <span className={EVAL_COLORS[i % EVAL_COLORS.length].title}>
                            {evalLabel(group.verdict)}
                          </span>
                          <span className="tabular-nums text-slate-500">
                            {group.count} · {pct} %
                          </span>
                        </div>
                        <div className="h-6 overflow-hidden rounded-lg bg-slate-100">
                          <div
                            className={`h-full ${EVAL_COLORS[i % EVAL_COLORS.length].bar}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              <div
                className="grid gap-4"
                style={{
                  gridTemplateColumns: `repeat(${Math.max(
                    1,
                    state.evaluation.groups.length,
                  )}, minmax(0, 1fr))`,
                }}
              >
                {state.evaluation.groups.map((group, i) => (
                  <div
                    key={group.verdict}
                    className={`rounded-2xl border p-4 ${EVAL_COLORS[i % EVAL_COLORS.length].box}`}
                  >
                    <div
                      className={`mb-2 text-lg font-semibold ${EVAL_COLORS[i % EVAL_COLORS.length].title}`}
                    >
                      {evalLabel(group.verdict)} · {group.count}
                    </div>
                    <ul className="max-h-80 space-y-1.5 overflow-auto">
                      {group.items.map((item) => (
                        <li key={item.text} className="text-lg text-slate-800">
                          {item.text}
                          {item.count > 1 && (
                            <span className="ml-2 text-sm text-slate-400">
                              ×{item.count}
                            </span>
                          )}
                        </li>
                      ))}
                      {group.items.length === 0 && (
                        <li className="text-slate-300">—</li>
                      )}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          )}
          {question.kind === "open_text" && phase === "results" && !state.evaluation && (
            <ul className="mt-8 max-h-96 space-y-2 overflow-auto">
              {(state.words ?? []).map((entry) => (
                <li
                  key={entry.text}
                  className="rounded-xl border border-slate-200 px-4 py-2 text-xl"
                >
                  {entry.text}
                  {entry.count > 1 && (
                    <span className="ml-2 text-sm text-slate-400">×{entry.count}</span>
                  )}
                </li>
              ))}
              {(state.words ?? []).length === 0 && (
                <p className="text-slate-400">{t("No answers yet …")}</p>
              )}
            </ul>
          )}

          {/* Word cloud kept off the beamer while open when the presenter
              chose to reveal it only after closing (#30) and hasn't switched
              to "Ergebnis" yet. */}
          {question.kind === "word_cloud" &&
            phase === "open" &&
            wcReveal === "question" &&
            question.wordcloud_live === false && (
              <div className="mt-10 text-center text-slate-500">
                <p className="text-2xl">{t("Collecting answers …")}</p>
                <p className="mt-2 text-slate-400">
                  {t("The word cloud appears once voting closes.")}
                </p>
              </div>
            )}
          {/* The cloud is the word-cloud "result", shown whenever the reveal
              pill is on "Ergebnis" — including while the vote is still open, so
              the presenter can show the interim standing without closing it. On
              "Frage" it stays hidden (just the question). The view (raw / AI
              cleaned / AI grouped) is picked from the footer dropdown. */}
          {question.kind === "word_cloud" &&
            wcReveal === "results" &&
            (wcView === "raw" ? (
              (state.words ?? []).length === 0 ? (
                <p className="mt-8 text-center text-slate-400">
                  {t("No terms yet …")}
                </p>
              ) : (
                <WordCloud words={state.words ?? []} />
              )
            ) : (
              <WordCloudAiView view={wcView} ai={state.wordcloud_ai} />
            ))}

          <div className="mt-10 text-center text-slate-500">
            {phase === "preview" && (
              <span className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-4 py-1.5 text-lg font-semibold text-amber-800">
                <span aria-hidden className="h-2.5 w-2.5 rounded-full bg-amber-500" />
                {t("Vote not started yet")}
              </span>
            )}
            {phase === "open" && (
              <p className="text-3xl">
                <span className="font-extrabold tabular-nums text-brand-700">{total}</span>{" "}
                {t("answer", { count: total })}
              </p>
            )}
            {phase === "closed" && (
              <p className="text-xl">{t("Voting closed")}</p>
            )}
          </div>
        </div>
      )}
    </Shell>
  );
}

function Shell({
  children,
  footer,
  logo,
  overlay,
  stats,
}: {
  children: React.ReactNode;
  footer?: React.ReactNode;
  logo?: string | null;
  overlay?: React.ReactNode;
  stats?: React.ReactNode;
}) {
  return (
    <div className="relative flex h-screen flex-col bg-white font-sans text-slate-900">
      {logo && (
        <img
          src={logo}
          alt=""
          aria-hidden
          className="absolute right-6 top-5 z-10 h-10 w-auto max-w-[200px] object-contain"
        />
      )}
      <main className="min-h-0 flex-1 overflow-auto px-8 py-6">{children}</main>
      {overlay}
      {stats}
      {footer}
    </div>
  );
}

/** Permanent, phase-independent counter fixed to the lower-left corner of the
 * beamer view (#35): connected clients and votes cast for the current
 * question. Sits just above the footer action bar so the two never overlap. */
function LiveStats({ participants, votes }: { participants: number; votes: number }) {
  const { t } = useTranslation();
  return (
    <div
      className="fixed left-6 bottom-20 z-20 flex items-center gap-3 rounded-full border border-slate-200 bg-white/90 px-3 py-1.5 text-sm text-slate-500 shadow-sm backdrop-blur"
      aria-live="polite"
    >
      <span className="flex items-center gap-1.5 tabular-nums" title={t("Connected participants")}>
        <Users aria-hidden className="h-4 w-4" /> {participants}
      </span>
      <span className="flex items-center gap-1.5 tabular-nums" title={t("Votes for the current question")}>
        <Vote aria-hidden className="h-4 w-4" /> {votes}
      </span>
    </div>
  );
}

const CORNER_POSITION: Record<string, string> = {
  "top-left": "left-6 top-5",
  "top-right": "right-6 top-5",
  "bottom-left": "left-6 bottom-20",
  "bottom-right": "right-6 bottom-20",
};

/** Persistent join hint on the beamer so latecomers can still scan in (#6).
 * Corner is room-configurable; renders nothing unless a feature is enabled. */
/** Recording mode (#53): the per-question deep-link QR on the beamer, so the
 * code is captured in the recording and later viewers can vote on it. */
function RecordingCorner({
  room,
  token,
  questionId,
}: {
  room: LiveState["room"];
  token: string;
  questionId: number;
}) {
  const { t } = useTranslation();
  // Top-left; drop below the join corner if that also sits top-left so the two
  // QR boxes never overlap. Logo is top-right, LiveStats bottom-left.
  const joinTopLeft =
    (room.show_qr || room.show_code) && (room.corner ?? "bottom-right") === "top-left";
  const position = joinTopLeft ? "left-6 top-40" : "left-6 top-5";
  return (
    <div
      className={`absolute z-20 flex items-center gap-3 rounded-2xl border border-slate-200 bg-white/90 p-3 shadow-sm backdrop-blur ${position}`}
    >
      <img
        src={live.recordingQrUrl(token, questionId)}
        alt={t("QR code to vote on this question from the recording")}
        className="h-24 w-24 rounded-lg"
      />
      <p className="max-w-[10rem] text-left text-xs text-slate-500">
        {t("Watching the recording? Scan to vote on this question afterward.")}
      </p>
    </div>
  );
}

function JoinCorner({ room }: { room: LiveState["room"] }) {
  const { t } = useTranslation();
  if (!room.show_qr && !room.show_code) return null;
  const url = live.participantUrl(room.code);
  const position = CORNER_POSITION[room.corner ?? "bottom-right"];
  return (
    <div
      className={`absolute z-20 flex items-center gap-3 rounded-2xl border border-slate-200 bg-white/90 p-3 shadow-sm backdrop-blur ${position}`}
    >
      {room.show_qr && (
        <img
          src={live.qrUrl(room.code)}
          alt={t("QR code for {{url}}", { url })}
          className="h-24 w-24 rounded-lg"
        />
      )}
      {room.show_code && (
        <div className="pr-1 text-left">
          <p className="text-xs text-slate-500">
            {url.replace(/^https?:\/\//, "")}
          </p>
          <p className="text-2xl font-extrabold tracking-widest text-brand-700">
            {room.code}
          </p>
        </div>
      )}
    </div>
  );
}

/** On-demand join panel (#): a large, scannable QR plus the room name, join
 *  URL and code. Docked to the right so the question/vote stay fully visible;
 *  it only displays, never changes the vote phase. Closed via its X, the
 *  footer icon, or Esc. */
function JoinPanel({
  room,
  onClose,
}: {
  room: LiveState["room"];
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const url = live.participantUrl(room.code);
  return (
    <div className="fixed right-6 top-1/2 z-30 w-72 -translate-y-1/2 rounded-2xl border border-slate-200 bg-white/95 p-5 text-center shadow-xl backdrop-blur">
      <button
        type="button"
        aria-label={t("Close")}
        onClick={onClose}
        className="absolute right-2 top-2 rounded-lg p-1 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
      >
        <X aria-hidden className="h-4 w-4" />
      </button>
      <p className="mb-3 truncate pr-4 text-lg font-bold text-slate-900">
        {localizedText(room.title)}
      </p>
      <img
        src={live.qrUrl(room.code)}
        alt={t("QR code for {{url}}", { url })}
        className="mx-auto h-56 w-56 rounded-lg"
      />
      <p className="mt-3 break-all text-sm text-slate-600">
        {url.replace(/^https?:\/\//, "")}
      </p>
      <p className="text-3xl font-extrabold tracking-widest text-brand-700">
        {room.code}
      </p>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-md border border-slate-300 bg-slate-50 px-2 py-0.5 font-mono text-sm">
      {children}
    </kbd>
  );
}

type PlacedWord = {
  text: string;
  count: number;
  x: number;
  y: number;
  size: number;
  rank: number;
};

/** Lay the most frequent word large in the centre and arrange the rest
 * concentrically outward along an Archimedean spiral, biggest first (#31).
 * Box sizes are estimated from text length so no DOM measuring is needed. */
function layoutWordCloud(
  words: { text: string; count: number }[],
  scale = 1,
): PlacedWord[] {
  const top = [...words].sort((a, b) => b.count - a.count).slice(0, 40);
  if (top.length === 0) return [];
  const max = top[0].count;
  const min = top[top.length - 1].count;
  const sizeOf = (count: number) => {
    if (max === min) return 40 * scale;
    const t = (count - min) / (max - min);
    // 18–80px, quadratic so the leader really pops; scaled down for group clouds.
    return (18 + t * t * 62) * scale;
  };
  const placed: PlacedWord[] = [];
  const overlaps = (x: number, y: number, w: number, h: number) =>
    placed.some(
      (p) =>
        Math.abs(x - p.x) * 2 < w + estWidth(p) + 14 &&
        Math.abs(y - p.y) * 2 < h + p.size * 1.15 + 10,
    );
  const estWidth = (p: PlacedWord) => p.text.length * p.size * 0.58;
  top.forEach((word, rank) => {
    const size = sizeOf(word.count);
    const w = word.text.length * size * 0.58;
    const h = size * 1.15;
    let angle = 0;
    let x = 0;
    let y = 0;
    // Spiral out until the estimated box no longer collides.
    while (overlaps(x, y, w, h)) {
      angle += 0.35;
      const r = 6 * angle;
      x = r * Math.cos(angle);
      y = r * Math.sin(angle) * 0.62; // squash vertically → a wider cloud
    }
    placed.push({ text: word.text, count: word.count, x, y, size, rank });
  });
  return placed;
}

function WordCloud({
  words,
  color,
  scale = 1,
  heightClass = "h-[62vh]",
}: {
  words: { text: string; count: number }[];
  color?: string;
  scale?: number;
  heightClass?: string;
}) {
  const placed = useMemo(() => layoutWordCloud(words, scale), [words, scale]);
  return (
    <div className={`relative mx-auto w-full max-w-5xl ${heightClass}`}>
      <div className="absolute left-1/2 top-1/2">
        {placed.map((w) => (
          <span
            key={w.text}
            title={`${w.count}×`}
            className={`absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap font-bold ${
              color ? "" : "text-brand-700 dark:text-brand-300"
            }`}
            style={{
              left: `${w.x}px`,
              top: `${w.y}px`,
              fontSize: `${w.size}px`,
              opacity: 1 - Math.min(0.45, w.rank * 0.02),
              ...(color ? { color } : {}),
            }}
          >
            {w.text}
          </span>
        ))}
      </div>
    </div>
  );
}

// Categorical palette for grouped clouds (tuned for the always-light beamer).
const GROUP_COLORS = [
  "oklch(0.52 0.13 150)", // green (brand family)
  "oklch(0.52 0.12 245)", // blue
  "oklch(0.50 0.15 300)", // violet
  "oklch(0.55 0.14 40)", // orange
  "oklch(0.53 0.16 20)", // red
  "oklch(0.50 0.10 195)", // teal
  "oklch(0.50 0.13 330)", // magenta
];

function AiWait() {
  const { t } = useTranslation();
  return (
    <div className="mt-10 text-center text-slate-500">
      <p className="text-2xl">{t("Evaluating answers …")}</p>
      <p className="mt-2 text-slate-400">{t("The AI is summarizing the entries.")}</p>
    </div>
  );
}

/** The consolidated (single cloud) or grouped (many clouds) AI view, with a
 * wait state while the first LLM pass is still running (#Wortwolke-KI). */
function WordCloudAiView({
  view,
  ai,
}: {
  view: "consolidated" | "grouped";
  ai?: WordCloudAI;
}) {
  const { t } = useTranslation();
  if (!ai || ai.pending) return <AiWait />;
  if (view === "consolidated") {
    if (ai.merged.length === 0) {
      return <p className="mt-8 text-center text-slate-400">{t("No terms yet …")}</p>;
    }
    return <WordCloud words={ai.merged} />;
  }
  if (ai.clusters.length === 0) {
    return <p className="mt-8 text-center text-slate-400">{t("No terms yet …")}</p>;
  }
  return <GroupedWordClouds clusters={ai.clusters} />;
}

/** Several concentric clouds side by side, one per AI group, each in its own
 * colour with the most frequent word largest/centred (#Wortwolke-KI). */
function GroupedWordClouds({ clusters }: { clusters: WordCloudAI["clusters"] }) {
  const colsClass =
    clusters.length <= 1
      ? "grid-cols-1"
      : clusters.length === 2
        ? "sm:grid-cols-2"
        : "sm:grid-cols-2 lg:grid-cols-3";
  return (
    <div className={`mt-2 grid gap-4 ${colsClass}`}>
      {clusters.map((cluster, i) => {
        const color = GROUP_COLORS[i % GROUP_COLORS.length];
        return (
          <div
            key={cluster.label}
            className="rounded-2xl border border-slate-200 p-3"
          >
            <h3 className="text-center text-xl font-semibold" style={{ color }}>
              {cluster.label}{" "}
              <span className="font-normal text-slate-400">· {cluster.count}</span>
            </h3>
            <WordCloud
              words={cluster.words}
              color={color}
              scale={0.6}
              heightClass="h-[34vh]"
            />
          </div>
        );
      })}
    </div>
  );
}

function Footer(props: {
  phase: string;
  participants: number;
  index: number;
  count: number;
  variant?: "question" | "section";
  onPrev: () => void;
  onNext: () => void;
  onToggle?: () => void;
  revealLevel?: "question" | "results" | "solution";
  canReveal?: boolean;
  onShowQuestion?: () => void;
  onShowResults?: () => void;
  onShowSolution?: () => void;
  views?: { value: string; label: string }[];
  viewValue?: string;
  onSelectView?: (value: string) => void;
  onFinish: () => void;
  onCloseWindow?: () => void;
  joinShown?: boolean;
  onToggleJoin?: () => void;
}) {
  const { t } = useTranslation();
  const btn =
    "inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-600 hover:bg-slate-50";
  const isSection = props.variant === "section";
  return (
    <footer className="flex items-center justify-between border-t border-slate-200 px-6 py-3 text-sm text-slate-500">
      {/* Left cluster: the question indicator, and — next to it — the
       * Frage/Ergebnis/Lösung reveal pill (it belongs to the current
       * question, so it reads better beside "Frage x/Y" than over on the
       * right with Beenden/navigation). */}
      <div className="flex items-center gap-3">
        <span>
          {isSection
            ? t("Section")
            : props.index >= 0
              ? t("Question {{current}}/{{total}}", {
                  current: props.index + 1,
                  total: props.count,
                })
              : t("Start")}
        </span>
        {/* Toggle a scannable QR/join panel on demand (#), without touching
         *  the vote state. "Q" does the same. */}
        {!isSection && props.onToggleJoin && (
          <button
            type="button"
            aria-label={t("Show QR code and join link")}
            aria-pressed={props.joinShown}
            title={t("Show QR code and join link (Q)")}
            onClick={props.onToggleJoin}
            className={`rounded-lg p-1.5 transition-colors ${props.joinShown ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200" : "text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400"}`}
          >
            <QrCode aria-hidden className="h-5 w-5" />
          </button>
        )}
        {!isSection && props.onShowResults && props.phase !== "lobby" && (
          <div
            className="grid grid-flow-col auto-cols-fr items-center rounded-full border border-slate-200 p-0.5 text-xs dark:border-slate-700"
            role="group"
            aria-label={t("View")}
          >
            <button
              type="button"
              aria-pressed={props.revealLevel === "question"}
              onClick={props.onShowQuestion}
              className={`rounded-full px-2.5 py-1 text-center ${props.revealLevel === "question" ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200" : "text-slate-500 dark:text-slate-400"}`}
            >
              {t("Question")}
            </button>
            <button
              type="button"
              aria-pressed={props.revealLevel === "results"}
              onClick={props.onShowResults}
              className={`rounded-full px-2.5 py-1 text-center ${props.revealLevel === "results" ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200" : "text-slate-500 dark:text-slate-400"}`}
            >
              {t("Results")} <Kbd>E</Kbd>
            </button>
            {props.canReveal && (
              <button
                type="button"
                aria-pressed={props.revealLevel === "solution"}
                onClick={props.onShowSolution}
                className={`rounded-full px-2.5 py-1 text-center ${props.revealLevel === "solution" ? "bg-brand-100 text-brand-800 dark:bg-brand-900 dark:text-brand-200" : "text-slate-500 dark:text-slate-400"}`}
              >
                {t("Solution")} <Kbd>A</Kbd>
              </button>
            )}
          </div>
        )}
        {/* Word-cloud view (#75): sits right beside the Frage/Ergebnis pill —
            both steer what's on the beamer. A dropdown lists the available
            views (raw / AI cleaned / AI grouped); the "a" key still cycles
            them. */}
        {!isSection && props.views && props.onSelectView && (
          <label className={`${btn} gap-2`}>
            {t("View")}
            <select
              value={props.viewValue}
              onChange={(event) => props.onSelectView!(event.target.value)}
              className="bg-transparent font-medium text-slate-700 focus:outline-none dark:text-slate-200"
            >
              {props.views.map((view) => (
                <option key={view.value} value={view.value}>
                  {view.label}
                </option>
              ))}
            </select>
            <Kbd>A</Kbd>
          </label>
        )}
      </div>
      {/* Always-present Beenden + navigation stay flush right; Starten sits
       * on the left of this group so they never shift as it appears. */}
      <div className="flex gap-2">
        {/* Starting/results only make sense on a question, not a section. */}
        {!isSection && props.onToggle && (
          <button className={btn} onClick={props.onToggle}>
            {props.phase === "open" ? t("Stop") : t("Start", { context: "action" })}{" "}
            <Kbd>S</Kbd>
          </button>
        )}
        <button className={`${btn} text-red-700`} onClick={props.onFinish}>
          {t("End")} <Kbd>Esc</Kbd>
        </button>
        {props.onCloseWindow && (
          <button className={btn} onClick={props.onCloseWindow}>
            {t("Close window")}
          </button>
        )}
        <button className={btn} onClick={props.onPrev} aria-label={t("Back (←)")}>
          <ChevronLeft aria-hidden className="h-5 w-5" />
        </button>
        <button className={btn} onClick={props.onNext} aria-label={t("Next (→)")}>
          <ChevronRight aria-hidden className="h-5 w-5" />
        </button>
      </div>
    </footer>
  );
}
