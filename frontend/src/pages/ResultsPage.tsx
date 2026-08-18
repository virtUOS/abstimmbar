// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Stored results per run (concept §7): the same bar charts as in the
 * presentation, viewable after the lecture; runs are deletable. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ChartColumnDecreasing, Check, Download, Trash2 } from "lucide-react";
import {
  api,
  results,
  type FreeTextEvaluation,
  type QuestionSet,
  type RunResults,
  type WordCloudOptimization,
} from "../api";
import { useApp, useEasyMode } from "../App";
import { localizedText } from "@basicbar/ui";
import AiAssistPanel from "../components/AiAssistPanel";
import RichText from "../components/RichText";
import { Button, ConfirmInline, EmptyState, TextInput } from "../components/ui";
import LikertResult from "../components/LikertResult";

function aiErrorText(err: unknown): string {
  try {
    return JSON.parse((err as Error).message).detail ?? String(err);
  } catch {
    return String(err);
  }
}

/** Word-cloud result with an optional AI cleanup (merge spelling variants and
 * synonyms, group into thematic clusters). Non-destructive: the raw votes are
 * untouched, and the teacher can flip back to the original at any time. */
function WordCloudResult({
  runId,
  questionId,
  words,
  aiEnabled,
}: {
  runId: number;
  questionId: number;
  words: { text: string; count: number }[];
  aiEnabled: boolean;
}) {
  const { t } = useTranslation();
  const [optimized, setOptimized] = useState<WordCloudOptimization | null>(null);
  const [showOptimized, setShowOptimized] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function optimize() {
    setBusy(true);
    setError("");
    try {
      const data = await results.optimizeWordCloud(runId, questionId);
      setOptimized(data);
      setShowOptimized(true);
    } catch (err) {
      setError(aiErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  const showClusters = optimized && showOptimized;

  return (
    <>
      {!showClusters && (
        <p className="text-sm leading-7">
          {words.map((word) => (
            <span
              key={word.text}
              className="mr-3 inline-block rounded-lg bg-brand-50 dark:bg-brand-950 px-2 py-0.5 text-brand-800 dark:text-brand-200"
            >
              {word.text} <span className="text-slate-400">×{word.count}</span>
            </span>
          ))}
          {words.length === 0 && <span className="text-slate-400">{t("No terms.")}</span>}
        </p>
      )}
      {showClusters && (
        <div className="space-y-3">
          {optimized.clusters.map((cluster) => (
            <div key={cluster.label}>
              <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                {cluster.label}{" "}
                <span className="text-slate-300 dark:text-slate-600">· {cluster.count}</span>
              </div>
              <p className="text-sm leading-7">
                {cluster.words.map((word) => (
                  <span
                    key={word.text}
                    title={
                      word.variants.length > 1
                        ? t("Merged: {{variants}}", { variants: word.variants.join(", ") })
                        : undefined
                    }
                    className="mr-3 inline-block rounded-lg bg-brand-50 dark:bg-brand-950 px-2 py-0.5 text-brand-800 dark:text-brand-200"
                  >
                    {word.text} <span className="text-slate-400">×{word.count}</span>
                  </span>
                ))}
              </p>
            </div>
          ))}
        </div>
      )}
      {aiEnabled && words.length > 0 && (
        <div className="mt-3">
          <AiAssistPanel title={t("Optimize word cloud")}>
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => void optimize()} disabled={busy}>
                {busy
                  ? t("Optimizing …")
                  : optimized
                    ? t("Optimize again")
                    : t("Optimize with AI")}
              </Button>
              {optimized && (
                <Button variant="ghost" onClick={() => setShowOptimized((v) => !v)}>
                  {showOptimized ? t("Show original") : t("Show optimized")}
                </Button>
              )}
            </div>
            {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
          </AiAssistPanel>
        </div>
      )}
    </>
  );
}

function stripHtml(html: string) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent?.trim() ?? "";
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Categories are coloured by position (first three green/amber/red so both
// presets read naturally, custom scales get follow-up colours).
const EVAL_CHIPS = [
  { chip: "bg-brand-50 text-brand-800 dark:bg-brand-950 dark:text-brand-200", bar: "bg-brand-500" },
  { chip: "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200", bar: "bg-amber-400" },
  { chip: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-200", bar: "bg-red-400" },
  { chip: "bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200", bar: "bg-blue-500" },
  { chip: "bg-violet-50 text-violet-800 dark:bg-violet-950/40 dark:text-violet-200", bar: "bg-violet-500" },
];

function evalLabel(verdict: string) {
  return verdict ? verdict[0].toUpperCase() + verdict.slice(1) : verdict;
}

/** Free-text result with an optional AI evaluation: each distinct answer is
 * sorted into korrekt / unklar / falsch. An optional reference (expected
 * answer or criterion) sharpens the judgement. Non-destructive. */
function FreeTextResult({
  runId,
  questionId,
  words,
  aiEnabled,
}: {
  runId: number;
  questionId: number;
  words: { text: string; count: number }[];
  aiEnabled: boolean;
}) {
  const { t } = useTranslation();
  const [reference, setReference] = useState("");
  const [evaluation, setEvaluation] = useState<FreeTextEvaluation | null>(null);
  const [showEvaluation, setShowEvaluation] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function evaluate() {
    setBusy(true);
    setError("");
    try {
      const data = await results.evaluateFreeText(runId, questionId, reference);
      setEvaluation(data);
      setShowEvaluation(true);
    } catch (err) {
      setError(aiErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  const showGroups = evaluation && showEvaluation;

  return (
    <>
      {!showGroups && (
        <p className="text-sm leading-7">
          {words.map((word) => (
            <span
              key={word.text}
              className="mr-3 inline-block rounded-lg bg-brand-50 dark:bg-brand-950 px-2 py-0.5 text-brand-800 dark:text-brand-200"
            >
              {word.text} <span className="text-slate-400">×{word.count}</span>
            </span>
          ))}
          {words.length === 0 && <span className="text-slate-400">{t("No terms.")}</span>}
        </p>
      )}
      {showGroups && (
        <div className="space-y-3">
          {/* Optional bar chart of the category distribution. */}
          {evaluation.chart && (
            <div className="mb-4 space-y-2">
              {evaluation.groups.map((group, i) => {
                const total = evaluation.groups.reduce((s, g) => s + g.count, 0);
                const pct = total ? Math.round((group.count / total) * 100) : 0;
                return (
                  <div key={group.verdict}>
                    <div className="mb-0.5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                      <span>{evalLabel(group.verdict)}</span>
                      <span className="tabular-nums">{group.count} · {pct} %</span>
                    </div>
                    <div className="h-3 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
                      <div
                        className={`h-full ${EVAL_CHIPS[i % EVAL_CHIPS.length].bar}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {evaluation.groups.map((group, i) =>
            group.items.length === 0 ? null : (
              <div key={group.verdict}>
                <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">
                  {evalLabel(group.verdict)}{" "}
                  <span className="text-slate-300 dark:text-slate-600">
                    · {group.count}
                  </span>
                </div>
                <p className="text-sm leading-7">
                  {group.items.map((item) => (
                    <span
                      key={item.text}
                      title={item.note || undefined}
                      className={`mr-3 inline-block rounded-lg px-2 py-0.5 ${EVAL_CHIPS[i % EVAL_CHIPS.length].chip}`}
                    >
                      {item.text} <span className="opacity-60">×{item.count}</span>
                    </span>
                  ))}
                </p>
              </div>
            ),
          )}
        </div>
      )}
      {aiEnabled && words.length > 0 && (
        <div className="mt-3">
          <AiAssistPanel title={t("Evaluate free text")}>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <TextInput
                value={reference}
                onChange={(event) => setReference(event.target.value)}
                placeholder={t("Expected answer / criterion (optional)")}
                className="sm:max-w-xs"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => void evaluate()} disabled={busy}>
                  {busy
                    ? t("Evaluating …")
                    : evaluation
                      ? t("Evaluate again")
                      : t("Evaluate answers")}
                </Button>
                {evaluation && (
                  <Button variant="ghost" onClick={() => setShowEvaluation((v) => !v)}>
                    {showEvaluation ? t("Show original") : t("Show evaluation")}
                  </Button>
                )}
              </div>
            </div>
            {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
          </AiAssistPanel>
        </div>
      )}
    </>
  );
}

/** Optional AI short report of one run's results, rendered as sanitized
 * HTML via `RichText`. Display-only; the teacher triggers it and can
 * regenerate. */
function RunReport({ runId, aiEnabled }: { runId: number; aiEnabled: boolean }) {
  const { t } = useTranslation();
  const [report, setReport] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function make() {
    setBusy(true);
    setError("");
    try {
      const data = await results.summarize(runId);
      setReport(data.report);
    } catch (err) {
      setError(aiErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!aiEnabled) return null;
  return (
    <div className="mb-4">
      <AiAssistPanel title={t("Short report")}>
        <Button onClick={() => void make()} disabled={busy}>
          {busy
            ? t("Generating …")
            : report
              ? t("Create again")
              : t("Create short report")}
        </Button>
        {report && (
          <div className="mt-2 text-sm">
            <RichText html={report} />
          </div>
        )}
        {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
      </AiAssistPanel>
    </div>
  );
}

export default function ResultsPage() {
  const { t } = useTranslation();
  const { setId } = useParams();
  const id = Number(setId);
  const { whoami } = useApp();
  const easyMode = useEasyMode();
  const aiEnabled = !!whoami?.ai_enabled && !easyMode;
  const [set, setSet] = useState<QuestionSet | null>(null);
  const [runs, setRuns] = useState<RunResults[] | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | "all" | null>(null);
  // Which Durchführung (archive) is shown, and whether export covers all (#17).
  const [selected, setSelected] = useState<number | null>(null);
  const [exportAll, setExportAll] = useState(false);

  const reload = () =>
    Promise.all([api.getQuestionSet(id), results.list(id)]).then(
      ([setData, payload]) => {
        setSet(setData);
        setRuns(payload.results);
      },
    );
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!set || !runs) return null;

  // Runs come newest-first; the newest is the default selection.
  const current = runs.find((r) => r.run === selected) ?? runs[0] ?? null;
  const runLabel = (run: RunResults) =>
    t("Run on {{date}}", { date: formatDate(run.first_opened_at ?? run.created_at) });

  return (
    <div>
      <nav className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        <Link to="/" className="hover:text-brand-700 dark:hover:text-brand-300">{t("My rooms")}</Link> /{" "}
        <Link to={`/rooms/${set.room}`} className="hover:text-brand-700 dark:hover:text-brand-300">{set.room_title}</Link> /{" "}
        <Link to={`/sets/${set.id}`} className="hover:text-brand-700 dark:hover:text-brand-300">{localizedText(set.title)}</Link> /{" "}
        {t("Results")}
      </nav>

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("Results — {{title}}", { title: localizedText(set.title) })}</h1>
        {runs.length > 0 && current && (
          <div className="flex flex-wrap items-center gap-3">
            {/* Export as one visibly grouped unit: scope + download. */}
            <div className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-2.5 py-1.5 dark:border-slate-700 dark:bg-slate-900/40">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                {t("Export")}
              </span>
              <select
                aria-label={t("Export scope")}
                value={exportAll ? "all" : "one"}
                onChange={(event) => setExportAll(event.target.value === "all")}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
              >
                <option value="one">{t("only this session")}</option>
                <option value="all">{t("all sessions (incl. archive)")}</option>
              </select>
              <a
                href={results.csvUrl(id, exportAll ? undefined : current.run)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                <Download aria-hidden className="h-4 w-4" /> CSV
              </a>
            </div>
            {confirmDelete === "all" ? (
              <ConfirmInline
                message={t("Delete all results?")}
                onConfirm={() =>
                  void results.deleteAll(id).then(() => {
                    setConfirmDelete(null);
                    return reload();
                  })
                }
                onCancel={() => setConfirmDelete(null)}
              />
            ) : (
              <Button variant="danger" onClick={() => setConfirmDelete("all")}>
                {t("Delete all")}
              </Button>
            )}
          </div>
        )}
      </div>

      {runs.length === 0 ? (
        <EmptyState icon={ChartColumnDecreasing} title={t("No results yet")}>
          {t(
            "Results appear here once the question set has been presented and answered at least once.",
          )}
        </EmptyState>
      ) : (
        <div className="space-y-6">
          {(current ? [current] : []).map((run) => (
            <section
              key={run.run}
              className="rounded-2xl border border-slate-200 dark:border-slate-800 p-5"
            >
              <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                {/* The Termin picker doubles as the block heading (#17-Feedback). */}
                <div className="flex flex-wrap items-center gap-2">
                  <select
                    aria-label={t("Select session")}
                    value={run.run}
                    onChange={(event) => setSelected(Number(event.target.value))}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-base font-semibold text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
                  >
                    {runs.map((r) => (
                      <option key={r.run} value={r.run}>
                        {runLabel(r)}
                      </option>
                    ))}
                  </select>
                  <span className="text-sm text-slate-500 dark:text-slate-400">
                    {run.votes_total} {t("vote", { count: run.votes_total })}
                    {run.phase !== "finished" && t(" · still running")}
                  </span>
                </div>
                {confirmDelete === run.run ? (
                  <ConfirmInline
                    message={t("Delete run?")}
                    onConfirm={() =>
                      void results.deleteRun(run.run).then(() => {
                        setConfirmDelete(null);
                        return reload();
                      })
                    }
                    onCancel={() => setConfirmDelete(null)}
                  />
                ) : (
                  <Button
                    variant="ghost"
                    aria-label={t("Delete run")}
                    onClick={() => setConfirmDelete(run.run)}
                  >
                    <Trash2 aria-hidden className="h-4 w-4" />
                  </Button>
                )}
              </div>

              {run.votes_total > 0 && (
                <RunReport runId={run.run} aiEnabled={aiEnabled} />
              )}

              <div className="space-y-5">
                {run.questions.map((question) => {
                  const total = question.votes;
                  // Before/after pair (#54): at the after-question's slot, show
                  // the before-question (from the same run) stacked above it.
                  const before =
                    question.before_question != null
                      ? run.questions.find((q) => q.id === question.before_question)
                      : undefined;
                  const isBefore = run.questions.some(
                    (q) => q.before_question === question.id,
                  );
                  return (
                    <div key={question.id}>
                      <h3 className="mb-2 flex items-center gap-2 text-sm font-medium text-slate-900 dark:text-slate-100">
                        {(before || isBefore) && (
                          <span className="shrink-0 rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                            {before ? t("After") : t("Before")}
                          </span>
                        )}
                        <span>
                          {question.position + 1}. {stripHtml(localizedText(question.text)) || t("No question text")}
                        </span>
                        <span className="font-normal text-slate-400">
                          {total} {t("answer", { count: total })}
                        </span>
                        {question.votes_recording > 0 && (
                          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                            {t("{{n}} from recording", { n: question.votes_recording })}
                          </span>
                        )}
                      </h3>
                      {before ? (
                        question.kind === "likert" ? (
                          <BeforeAfterLikert before={before} after={question} />
                        ) : (
                          <BeforeAfterChoice before={before} after={question} />
                        )
                      ) : (
                        <>
                          {question.kind === "likert" && question.likert && (
                            <LikertResult summary={question.likert} variant="compact" />
                          )}
                          {question.options && !(question.kind === "likert" && question.likert) && (
                            <div className="space-y-1.5">
                              {question.options.map((option) => {
                                const count = option.count ?? 0;
                                const percent = total ? Math.round((count / total) * 100) : 0;
                                return (
                                  <div key={option.id}>
                                    <div className="flex items-center gap-3 text-sm">
                                      <span
                                        className={`w-56 truncate ${option.is_correct ? "font-semibold text-brand-700 dark:text-brand-300" : "text-slate-700 dark:text-slate-300"}`}
                                      >
                                        {localizedText(option.text)} {option.is_correct && <Check aria-hidden className="inline h-4 w-4 text-brand-700 dark:text-brand-300" />}
                                      </span>
                                      <div className="h-4 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                                        <div
                                          className={`h-4 rounded ${option.is_correct ? "bg-brand-400" : "bg-slate-300 dark:bg-slate-600"}`}
                                          style={{ width: `${percent}%` }}
                                        />
                                      </div>
                                      <span className="w-20 text-right tabular-nums text-slate-500 dark:text-slate-400">
                                        {count} · {percent} %
                                      </span>
                                    </div>
                                    {/* Recording split (#53): on-site vs async. */}
                                    {run.recording_votes > 0 && (
                                      <div className="pl-[14.75rem] text-[11px] text-slate-400 dark:text-slate-500">
                                        {t("On-site")}: {option.onsite ?? 0} · {t("Recording")}: {option.recording ?? 0}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                          {question.priorities && question.kind === "priorities" && (
                            <div className="space-y-1.5">
                              {question.priorities.map((opt) => (
                                <div key={opt.id} className="text-sm">
                                  <div className="flex items-center gap-3">
                                    <span className="w-56 truncate text-slate-700 dark:text-slate-300">
                                      {localizedText(opt.text)}
                                    </span>
                                    <div className="relative h-4 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                                      {/* average fill */}
                                      <div
                                        className="absolute inset-y-0 left-0 rounded bg-brand-400"
                                        style={{ width: `${opt.avg}%` }}
                                      />
                                      {/* deviation range line on top */}
                                      <div
                                        className="absolute top-1/2 h-0.5 -translate-y-1/2 bg-slate-600 dark:bg-slate-300"
                                        style={{ left: `${opt.min}%`, width: `${Math.max(opt.max - opt.min, 0)}%` }}
                                      />
                                      {/* min / max whiskers */}
                                      <div
                                        className="absolute -top-0.5 -bottom-0.5 w-0.5 -translate-x-1/2 bg-slate-600 dark:bg-slate-300"
                                        style={{ left: `${opt.min}%` }}
                                      />
                                      <div
                                        className="absolute -top-0.5 -bottom-0.5 w-0.5 -translate-x-1/2 bg-slate-600 dark:bg-slate-300"
                                        style={{ left: `${opt.max}%` }}
                                      />
                                    </div>
                                    <span className="w-28 text-right tabular-nums text-slate-500 dark:text-slate-400">
                                      Ø {opt.avg} · {opt.min}–{opt.max}
                                    </span>
                                  </div>
                                </div>
                              ))}
                              {question.priorities.length === 0 && (
                                <span className="text-slate-400">{t("No answers yet.")}</span>
                              )}
                            </div>
                          )}
                          {question.ordering && question.kind === "ordering" && (
                            <div className="space-y-1.5">
                              {question.ordering.n === 0 ? (
                                <span className="text-slate-400">{t("No answers yet.")}</span>
                              ) : (
                                <>
                                  <div className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                                    {t("{{pct}}% got the full order correct", {
                                      pct: question.ordering.full_correct_rate,
                                    })}
                                  </div>
                                  {question.ordering.items.map((it) => (
                                    <div key={it.id} className="text-sm">
                                      <div className="flex items-center gap-3">
                                        <span className="w-56 truncate text-slate-700 dark:text-slate-300">
                                          {it.correct_position}. {localizedText(it.text)}
                                        </span>
                                        <div className="relative h-4 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                                          <div
                                            className="absolute h-4 rounded bg-brand-400"
                                            style={{ width: `${it.correct_rate}%` }}
                                          />
                                        </div>
                                        <span className="w-28 text-right tabular-nums text-slate-500 dark:text-slate-400">
                                          {it.correct_rate}%
                                        </span>
                                      </div>
                                    </div>
                                  ))}
                                </>
                              )}
                            </div>
                          )}
                          {question.words && question.kind === "word_cloud" && (
                            <WordCloudResult
                              runId={run.run}
                              questionId={question.id}
                              words={question.words}
                              aiEnabled={aiEnabled}
                            />
                          )}
                          {question.words && question.kind === "open_text" && (
                            <FreeTextResult
                              runId={run.run}
                              questionId={question.id}
                              words={question.words}
                              aiEnabled={aiEnabled}
                            />
                          )}
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

type ResultQuestion = RunResults["questions"][number];

/** Before/after choice comparison (#54): per option the before bar (lighter)
 * sits above the after bar, each labelled. Options are paired by position;
 * percentages use each side's own vote total. */
function BeforeAfterChoice({ before, after }: { before: ResultQuestion; after: ResultQuestion }) {
  const { t } = useTranslation();
  const options = after.options ?? [];
  return (
    <div className="space-y-3">
      {options.map((option, index) => {
        const beforeOption = before.options?.[index];
        const rows = [
          { key: "before", label: t("Before"), count: beforeOption?.count ?? 0, total: before.votes, light: true },
          { key: "after", label: t("After"), count: option.count ?? 0, total: after.votes, light: false },
        ];
        return (
          <div key={option.id}>
            <span className={`mb-1 block text-sm ${option.is_correct ? "font-semibold text-brand-700 dark:text-brand-300" : "text-slate-700 dark:text-slate-300"}`}>
              {localizedText(option.text)} {option.is_correct && <Check aria-hidden className="inline h-4 w-4 text-brand-700 dark:text-brand-300" />}
            </span>
            <div className="space-y-1">
              {rows.map((row) => {
                const percent = row.total ? Math.round((row.count / row.total) * 100) : 0;
                const barColor = option.is_correct
                  ? row.light
                    ? "bg-brand-200 dark:bg-brand-800"
                    : "bg-brand-400"
                  : row.light
                    ? "bg-slate-200 dark:bg-slate-700"
                    : "bg-slate-300 dark:bg-slate-600";
                return (
                  <div key={row.key} className="flex items-center gap-3 text-sm">
                    <span className="w-16 shrink-0 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                      {row.label}
                    </span>
                    <div className="h-4 flex-1 rounded bg-slate-100 dark:bg-slate-800">
                      <div className={`h-4 rounded ${barColor}`} style={{ width: `${percent}%` }} />
                    </div>
                    <span className="w-20 text-right tabular-nums text-slate-500 dark:text-slate-400">
                      {row.count} · {percent} %
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Before/after likert comparison (#54): before above after, before dimmed. */
function BeforeAfterLikert({ before, after }: { before: ResultQuestion; after: ResultQuestion }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3">
      {before.likert && (
        <div>
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t("Before")}
          </span>
          <div className="opacity-70">
            <LikertResult summary={before.likert} variant="compact" />
          </div>
        </div>
      )}
      {after.likert && (
        <div>
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            {t("After")}
          </span>
          <LikertResult summary={after.likert} variant="compact" />
        </div>
      )}
    </div>
  );
}
