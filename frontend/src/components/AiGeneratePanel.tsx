// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Human-in-the-loop panel to generate draft questions from a document
 * (PDF/PPTX/ODP) or pasted text. The teacher reviews the drafts, picks the
 * ones to keep and imports them into the set. Only rendered when AI is on. */
import { Check } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type GeneratedQuestion } from "../api";
import AiAssistPanel from "./AiAssistPanel";
import { Button, TextInput } from "./ui";

// Labels are English source strings, translated with t() at the render site
// (these live at module scope, outside the component).
const KIND_OPTIONS = [
  { value: "single_choice", label: "Single Choice" },
  { value: "multiple_choice", label: "Multiple Choice" },
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
  const [count, setCount] = useState(5);
  const [kinds, setKinds] = useState<string[]>(KIND_OPTIONS.map((k) => k.value));
  const [level, setLevel] = useState("mixed");
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");
  const [drafts, setDrafts] = useState<GeneratedQuestion[] | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  function toggleKind(value: string) {
    setKinds((current) =>
      current.includes(value)
        ? current.filter((k) => k !== value)
        : [...current, value],
    );
  }

  function toggleSelected(index: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

  async function generate() {
    setBusy(true);
    setError("");
    setDrafts(null);
    try {
      const { questions, notice } = await api.aiGenerateQuestions(setId, {
        file: file ?? undefined,
        text: text.trim() || undefined,
        count,
        kinds,
        level,
      });
      setDrafts(questions);
      setSelected(new Set(questions.map((_, index) => index)));
      if (questions.length === 0) setError(notice || t("No questions generated."));
    } catch (err) {
      setError(aiErrorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function importSelected() {
    if (!drafts) return;
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
          options: draft.options.map((option) => ({
            text: option.text,
            is_correct: option.is_correct,
          })),
        });
      }
      await onImported();
      onClose();
    } catch (err) {
      setError(aiErrorText(err));
      setImporting(false);
    }
  }

  const canGenerate = !busy && (file !== null || text.trim().length > 0) && kinds.length > 0;

  return (
    <div className="mb-4">
      <AiAssistPanel title={t("Generate questions from document")}>
        {!drafts ? (
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
              <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                {t("Count")}
                <TextInput
                  type="number"
                  min={1}
                  max={15}
                  value={count}
                  onChange={(event) =>
                    setCount(Math.min(15, Math.max(1, Number(event.target.value) || 1)))
                  }
                  className="!w-20"
                />
              </label>
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
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" disabled={!canGenerate} onClick={() => void generate()}>
                {busy ? t("Generating …") : t("Generate questions")}
              </Button>
              <Button variant="ghost" onClick={onClose}>
                {t("Cancel")}
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm text-slate-500 dark:text-slate-400">
              {t("{{selected}} of {{total}} selected — review the drafts and use them.", {
                selected: selected.size,
                total: drafts.length,
              })}
            </p>
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
                                  option.is_correct
                                    ? "text-brand-700 dark:text-brand-300"
                                    : ""
                                }
                              >
                                {option.text}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
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
              <Button variant="ghost" onClick={() => setDrafts(null)}>
                {t("Back")}
              </Button>
            </div>
          </div>
        )}
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </AiAssistPanel>
    </div>
  );
}
