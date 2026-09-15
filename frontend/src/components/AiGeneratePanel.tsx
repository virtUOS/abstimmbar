// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Human-in-the-loop panel to generate draft questions from a document
 * (PDF/PPTX/ODP) or pasted text. Generation runs as an async, chunked
 * background job: the teacher sees live progress and drafts as they arrive,
 * can cancel, and — reopening the panel — resumes a run already in flight.
 * On completion they pick the drafts to keep and import them into the set.
 * Only rendered when AI is on. */
import { Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type GeneratedQuestion, type GenerationJob } from "../api";
import AiAssistPanel from "./AiAssistPanel";
import { Button } from "./ui";

// Labels are English source strings, translated with t() at the render site
// (these live at module scope, outside the component).
const KIND_OPTIONS = [
  { value: "single_choice", label: "Single Choice" },
  { value: "multiple_choice", label: "Multiple Choice" },
  { value: "true_false", label: "True/False" },
  { value: "open_text", label: "Free text" },
];
const KIND_LABEL: Record<string, string> = {
  single_choice: "Single Choice",
  multiple_choice: "Multiple Choice",
  open_text: "Free text",
};
const LEVEL_OPTIONS = [
  { value: "mixed", label: "Mixed levels" },
  { value: "basics", label: "Basic level" },
  { value: "deep", label: "Advanced level" },
];

function aiErrorText(err: unknown): string {
  try {
    return JSON.parse((err as Error).message).detail ?? String(err);
  } catch {
    return String(err);
  }
}

function isActive(job: GenerationJob | null): boolean {
  return !!job && (job.status === "pending" || job.status === "running");
}

export default function AiGeneratePanel({
  setId,
  onClose,
  onImported,
}: {
  setId: number;
  onClose: () => void;
  onImported: () => void | Promise<void>;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [kinds, setKinds] = useState<string[]>(KIND_OPTIONS.map((k) => k.value));
  const [level, setLevel] = useState("mixed");
  const [guidance, setGuidance] = useState("");
  const [starting, setStarting] = useState(false);
  const [importing, setImporting] = useState(false);
  // `error` holds user-facing failures that must persist until acted on
  // (start/cancel/import); `pollError` is a transient polling blip that
  // self-heals on the next successful tick — kept apart so a routine poll
  // success can clear its own error without wiping a cancel/import error.
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [job, setJob] = useState<GenerationJob | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Once the teacher has touched the selection we stop auto-selecting new
  // drafts, so a re-render (or the final poll) never clobbers their choices.
  const selectionTouched = useRef(false);

  // Resume: on open, attach to a run already in flight (or a finished one).
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const active = await api.aiGenerateActive(setId);
        if (!cancelled && active && "id" in active) {
          // Don't overwrite a job the teacher started while this fetch was in
          // flight — attach only when we're still on the empty form.
          setJob((prev) => prev ?? (active as GenerationJob));
        }
      } catch {
        // No active job (or transient error) — start fresh from the form.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [setId]);

  // Poll while the job is running; stop on done/failed/cancelled.
  useEffect(() => {
    if (!isActive(job)) return;
    const jobId = job!.id;
    let stopped = false;
    const timer = setInterval(() => {
      void (async () => {
        try {
          const fresh = await api.aiGenerateJob(setId, jobId);
          if (stopped) return; // unmounted / job changed while the request ran
          setJob(fresh);
          setPollError(""); // a transient poll blip self-heals on the next tick
        } catch (err) {
          if (!stopped) setPollError(aiErrorText(err));
        }
      })();
    }, 1500);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [job?.id, job?.status, setId]);

  // When a run finishes, pre-select every draft (unless the teacher already
  // curated the selection while it was still streaming in).
  useEffect(() => {
    if (job?.status === "done" && !selectionTouched.current) {
      setSelected(new Set(job.drafts.map((_, index) => index)));
    }
  }, [job?.status, job?.id]);

  function toggleKind(value: string) {
    setKinds((current) =>
      current.includes(value)
        ? current.filter((k) => k !== value)
        : [...current, value],
    );
  }

  function toggleSelected(index: number) {
    selectionTouched.current = true;
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  function resetToForm() {
    setJob(null);
    setError("");
    setPollError("");
    setSelected(new Set());
    selectionTouched.current = false;
  }

  async function start() {
    setStarting(true);
    setError("");
    setPollError("");
    selectionTouched.current = false;
    try {
      const { job_id } = await api.aiGenerateStart(setId, {
        file: file ?? undefined,
        text: text.trim() || undefined,
        kinds,
        level,
        guidance: guidance.trim() || undefined,
      });
      const fresh = await api.aiGenerateJob(setId, job_id);
      setJob(fresh);
    } catch (err) {
      setError(aiErrorText(err));
    } finally {
      setStarting(false);
    }
  }

  async function cancel() {
    if (!job) return;
    try {
      await api.aiGenerateCancel(setId, job.id);
    } catch (err) {
      // Keep the progress view (the job may still be running server-side) and
      // surface the error, rather than silently dropping back to the form.
      setError(aiErrorText(err));
      return;
    }
    resetToForm();
  }

  async function importSelected() {
    const drafts = job?.drafts ?? [];
    setImporting(true);
    setError("");
    try {
      for (let index = 0; index < drafts.length; index++) {
        if (!selected.has(index)) continue;
        const draft = drafts[index];
        await api.createQuestion({
          question_set: setId,
          kind: draft.kind,
          text: draft.text,
          binary_choice: draft.binary_choice ?? false,
          options: draft.options.map((option) => ({
            text: option.text,
            is_correct: option.is_correct,
          })),
          model_solution: draft.model_solution ?? "",
          ai_evaluate: draft.kind === "open_text" && !!draft.model_solution,
        });
      }
      await onImported();
      onClose();
    } catch (err) {
      setError(aiErrorText(err));
      setImporting(false);
    }
  }

  const canGenerate =
    !starting && (file !== null || text.trim().length > 0) && kinds.length > 0;

  // Inner content of one draft (kind label, question, options, solution) —
  // shared by the live progress list and the final selectable list.
  function draftBody(draft: GeneratedQuestion) {
    return (
      <div className="min-w-0 flex-1">
        <div className="text-xs uppercase tracking-wide text-slate-400">
          {KIND_LABEL[draft.kind] ? t(KIND_LABEL[draft.kind]) : draft.kind}
        </div>
        <div className="text-sm font-medium text-slate-900 dark:text-slate-100">
          {draft.text}
        </div>
        {draft.options.length > 0 && (
          <ul className="mt-1 space-y-0.5 text-sm text-slate-600 dark:text-slate-300">
            {draft.options.map((option, oi) => (
              <li key={oi} className="flex items-center gap-1.5">
                {option.is_correct ? (
                  <Check aria-hidden className="h-4 w-4 text-brand-600" />
                ) : (
                  <span aria-hidden className="inline-block h-4 w-4" />
                )}
                <span
                  className={
                    option.is_correct ? "text-brand-700 dark:text-brand-300" : ""
                  }
                >
                  {option.text}
                </span>
              </li>
            ))}
          </ul>
        )}
        {draft.kind === "open_text" && draft.model_solution && (
          <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            <span className="text-slate-400">{t("Model solution")}: </span>
            {draft.model_solution}
          </div>
        )}
      </div>
    );
  }

  function truncationBanner() {
    if (!job?.truncated) return null;
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200">
        {job.notice ||
          t(
            "The document is long — only its first sections were used for generation.",
          )}
      </div>
    );
  }

  function renderBody() {
    // 1) No job yet → the configuration form.
    if (!job) {
      return (
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">
              {t("Document (PDF, PPTX or ODP)")}
            </label>
            <input
              type="file"
              accept=".pdf,.pptx,.odp"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-brand-100 file:px-3 file:py-1.5 file:text-brand-800 hover:file:bg-brand-200 dark:text-slate-300 dark:file:bg-brand-900 dark:file:text-brand-200"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">
              {t("… or paste text")}
            </label>
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={4}
              placeholder={t("Paste material as text (alternative to upload)")}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex flex-wrap items-center gap-3">
              {KIND_OPTIONS.map((option) => (
                <label
                  key={option.value}
                  className="flex items-center gap-1.5 text-sm text-slate-700 dark:text-slate-300"
                >
                  <input
                    type="checkbox"
                    checked={kinds.includes(option.value)}
                    onChange={() => toggleKind(option.value)}
                    className="h-4 w-4 rounded border-slate-300 accent-brand-600 dark:border-slate-700"
                  />
                  {t(option.label)}
                </label>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              {t("Question level")}
              <select
                value={level}
                onChange={(event) => setLevel(event.target.value)}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
                {LEVEL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {t(o.label)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-600 dark:text-slate-300">
              {t("Extra instructions (optional)")}
            </label>
            <textarea
              rows={2}
              value={guidance}
              onChange={(event) => setGuidance(event.target.value)}
              maxLength={1000}
              placeholder={t(
                "e.g. focus on understanding and application, use everyday examples, avoid dates and names",
              )}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" disabled={!canGenerate} onClick={() => void start()}>
              {starting ? t("Starting …") : t("Generate questions")}
            </Button>
            <Button variant="ghost" onClick={onClose}>
              {t("Cancel")}
            </Button>
          </div>
        </div>
      );
    }

    // 2) Failed → error + restart.
    if (job.status === "failed") {
      return (
        <div className="space-y-3">
          <p className="text-sm text-red-600">
            {job.error || t("Generation failed.")}
          </p>
          <Button variant="primary" onClick={resetToForm}>
            {t("Restart")}
          </Button>
        </div>
      );
    }

    // 3) Cancelled → note + restart.
    if (job.status === "cancelled") {
      return (
        <div className="space-y-3">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("Generation was cancelled.")}
          </p>
          <Button variant="primary" onClick={resetToForm}>
            {t("Restart")}
          </Button>
        </div>
      );
    }

    // 4) Running/pending → progress + live drafts.
    if (isActive(job)) {
      const total = job.total_chunks;
      const done = job.done_chunks;
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      return (
        <div className="space-y-3">
          {truncationBanner()}
          <div className="space-y-1">
            <div className="flex items-center justify-between text-sm text-slate-600 dark:text-slate-300">
              <span>
                {total > 0
                  ? t("Section {{done}} of {{total}}", { done, total })
                  : t("Preparing …")}
              </span>
              <span>{t("{{n}} suggestions", { n: job.drafts.length })}</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div
                className="h-full rounded-full bg-brand-600 transition-all duration-500"
                style={{ width: total > 0 ? `${pct}%` : "15%" }}
              />
            </div>
          </div>
          {job.drafts.length > 0 && (
            <ul className="space-y-2">
              {job.drafts.map((draft, index) => (
                <li
                  key={index}
                  className="rounded-lg border border-slate-200 bg-white/60 p-3 dark:border-slate-700 dark:bg-slate-900/40"
                >
                  {draftBody(draft)}
                </li>
              ))}
            </ul>
          )}
          <Button variant="ghost" onClick={() => void cancel()}>
            {t("Cancel generation")}
          </Button>
        </div>
      );
    }

    // 5) Done → selectable drafts + import.
    const drafts = job.drafts;
    return (
      <div className="space-y-2">
        {truncationBanner()}
        {drafts.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {/* When truncated, truncationBanner() already shows job.notice. */}
            {job.truncated
              ? t("No questions generated.")
              : job.notice || t("No questions generated.")}
          </p>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("{{selected}} of {{total}} selected — review the drafts and use them.", {
              selected: selected.size,
              total: drafts.length,
            })}
          </p>
        )}
        <ul className="space-y-2">
          {drafts.map((draft, index) => (
            <li
              key={index}
              className="rounded-lg border border-slate-200 bg-white/60 p-3 dark:border-slate-700 dark:bg-slate-900/40"
            >
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  checked={selected.has(index)}
                  onChange={() => toggleSelected(index)}
                  className="mt-1 h-4 w-4 rounded border-slate-300 accent-brand-600 dark:border-slate-700"
                />
                {draftBody(draft)}
              </label>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            variant="primary"
            disabled={importing || selected.size === 0}
            onClick={() => void importSelected()}
          >
            {importing
              ? t("Applying …")
              : t("Use selected ({{count}})", { count: selected.size })}
          </Button>
          <Button variant="ghost" onClick={resetToForm}>
            {t("Back")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mb-4">
      <AiAssistPanel title={t("Generate questions from document")}>
        {renderBody()}
        {(error || pollError) && (
          <p className="mt-2 text-sm text-red-600">{error || pollError}</p>
        )}
      </AiAssistPanel>
    </div>
  );
}
