// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Start-only form for "generate questions from a document" (PDF/PPTX/ODP)
 * or pasted text. It only KICKS OFF the async background job; progress and
 * reviewing the drafts happen elsewhere (the app-wide status bar and the
 * set's review hint → AiReviewPanel). So this form always opens fresh and
 * never shows drafts. Only rendered when AI is on. */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import AiAssistPanel from "./AiAssistPanel";
import { Button, TextInput } from "./ui";

// Labels are English source strings, translated with t() at the render site.
const KIND_OPTIONS = [
  { value: "single_choice", label: "Single Choice" },
  { value: "multiple_choice", label: "Multiple Choice" },
  { value: "true_false", label: "True/False" },
  { value: "open_text", label: "Free text" },
];
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

export default function AiGenerateForm({
  setId,
  onStarted,
  onClose,
}: {
  setId: number;
  onStarted: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [density, setDensity] = useState(1);
  const [kinds, setKinds] = useState<string[]>(KIND_OPTIONS.map((k) => k.value));
  const [level, setLevel] = useState("mixed");
  const [guidance, setGuidance] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");

  function toggleKind(value: string) {
    setKinds((current) =>
      current.includes(value)
        ? current.filter((k) => k !== value)
        : [...current, value],
    );
  }

  async function start() {
    setStarting(true);
    setError("");
    try {
      await api.aiGenerateStart(setId, {
        file: file ?? undefined,
        text: text.trim() || undefined,
        density,
        kinds,
        level,
        guidance: guidance.trim() || undefined,
      });
      onStarted();
    } catch (err) {
      setError(aiErrorText(err));
    } finally {
      setStarting(false);
    }
  }

  const canGenerate =
    !starting && (file !== null || text.trim().length > 0) && kinds.length > 0;

  return (
    <div className="mb-4">
      <AiAssistPanel title={t("Generate questions from document")}>
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
              {t("Questions per page")}
              <TextInput
                type="number"
                min={0.1}
                max={5}
                step={0.5}
                value={density}
                onChange={(event) => setDensity(Number(event.target.value))}
                className="!w-20"
              />
            </label>
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
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t("Covers the whole document; more per page means more questions.")}
          </p>
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
          {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
        </div>
      </AiAssistPanel>
    </div>
  );
}
