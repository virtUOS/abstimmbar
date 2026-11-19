// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** "Fragen importieren" (#323): bring existing questions in from pasted text
 *  (simple text format or GIFT) or a file (.txt, .gift, .h5p, ILIAS .zip/.xml).
 *  Needs no AI and is offered in both modes. Parsing is synchronous; the
 *  result is a job reviewed in the same panel as AI proposals. */
import { ExternalLink, FileInput } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  api,
  detailText,
  errorDetail,
  requestBody,
  type ImportFormat,
  type ImportSkip,
} from "../api";
import { guideUrl } from "../guide";
import AiAssistPanel from "./AiAssistPanel";
import FileDropzone from "./FileDropzone";
import ImportSkipList from "./ImportSkipList";
import { Button } from "./ui";

const EXAMPLE = `F: Welche Farbe hat der Himmel?
* Blau
- Grün

F: Erklären Sie kurz die Photosynthese.
L: Pflanzen wandeln Licht in Energie um.`;

const EXAMPLE_EN = `Q: What colour is the sky?
* Blue
- Green

Q: Briefly explain photosynthesis.
A: Plants turn light into energy.`;

export default function ImportQuestionsForm({
  setId,
  onImported,
  onClose,
  pendingProposals = 0,
}: {
  setId: number;
  /** The import produced a reviewable job. */
  onImported: (result: { job_id: number; format: ImportFormat }) => void;
  onClose: () => void;
  /** Unreviewed proposals of an earlier run/import; this import discards them. */
  pendingProposals?: number;
}) {
  const { t, i18n } = useTranslation();
  const textId = useId();
  const [mode, setMode] = useState<"text" | "file">("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorSkipped, setErrorSkipped] = useState<ImportSkip[]>([]);

  const canImport = !busy && (mode === "text" ? text.trim().length > 0 : file !== null);
  const isGerman = !!i18n.language?.startsWith("de");

  async function submit() {
    setBusy(true);
    setError("");
    setErrorSkipped([]);
    try {
      const result = await api.importQuestions(
        setId,
        mode === "file" && file ? { file } : { text },
      );
      onImported(result);
    } catch (err) {
      // 400 (unreadable / nothing found, possibly with a skipped list),
      // 409 (an AI generation of this set is still running): the backend
      // detail is already in the UI language.
      setError(detailText(errorDetail(err), t));
      const skipped = requestBody(err)?.skipped;
      if (Array.isArray(skipped)) setErrorSkipped(skipped as ImportSkip[]);
    } finally {
      setBusy(false);
    }
  }

  const tabClass = (active: boolean) =>
    "rounded-md px-3 py-1.5 text-sm font-medium transition-colors " +
    (active
      ? "bg-white text-slate-900 shadow-xs dark:bg-slate-800 dark:text-slate-100"
      : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-200");

  return (
    <div className="mb-4">
      <AiAssistPanel title={t("Import questions")} icon={FileInput} aiNote={false}>
        <div className="space-y-3">
          {pendingProposals > 0 && (
            <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700/60 dark:bg-amber-950/40 dark:text-amber-200">
              {t(
                "There are still {{n}} unreviewed proposals — importing discards them.",
                { n: pendingProposals },
              )}
            </p>
          )}
          <div
            role="group"
            aria-label={t("Source")}
            className="inline-flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1 dark:bg-slate-900"
          >
            <button
              type="button"
              aria-pressed={mode === "text"}
              onClick={() => setMode("text")}
              className={tabClass(mode === "text")}
            >
              {t("Paste text")}
            </button>
            <button
              type="button"
              aria-pressed={mode === "file"}
              onClick={() => setMode("file")}
              className={tabClass(mode === "file")}
            >
              {t("Upload file")}
            </button>
          </div>

          {mode === "text" ? (
            <div>
              <label
                htmlFor={textId}
                className="mb-1 block text-sm text-slate-600 dark:text-slate-300"
              >
                {t("Paste text")}
              </label>
              <textarea
                id={textId}
                value={text}
                onChange={(event) => setText(event.target.value)}
                rows={8}
                placeholder={t("Questions in the simple text format or in GIFT (Moodle)")}
                className="w-full rounded-lg border border-field bg-white px-3 py-2 font-mono text-sm text-slate-900 placeholder:font-sans placeholder:text-slate-400 focus:border-brand-600 focus:outline-hidden focus:ring-1 focus:ring-brand-600 dark:bg-slate-900 dark:text-slate-100"
              />
            </div>
          ) : (
            <FileDropzone
              accept=".txt,.gift,.h5p,.zip,.xml"
              file={file}
              onFile={setFile}
              hint={t("Text, GIFT (Moodle), H5P or ILIAS export (ZIP/XML), at most 10 MB")}
            />
          )}

          <div className="text-xs text-slate-500 dark:text-slate-400">
            <p>
              {t(
                "Simple text format: a question starts with “Q:”, correct answers with “*”, wrong ones with “-”; “A:” adds a model solution to a free-text question.",
              )}
            </p>
            <pre className="mt-1 whitespace-pre-wrap break-words rounded-md bg-white/70 px-2 py-1.5 font-mono text-slate-600 dark:bg-slate-900/60 dark:text-slate-300">
              {isGerman ? EXAMPLE : EXAMPLE_EN}
            </pre>
            <a
              href={guideUrl(
                i18n.language,
                { de: "fragen/", en: "questions/" },
                "fertige-fragen-ubernehmen",
              )}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-flex items-center gap-1 font-medium text-brand-700 hover:underline dark:text-brand-300"
            >
              {t("All formats and rules in the guide")}
              <ExternalLink aria-hidden className="h-3.5 w-3.5" />
            </a>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button variant="primary" disabled={!canImport} onClick={() => void submit()}>
              {busy ? t("Reading …") : t("Import")}
            </Button>
            <Button variant="ghost" onClick={onClose}>
              {t("Cancel")}
            </Button>
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          <ImportSkipList skipped={errorSkipped} />
        </div>
      </AiAssistPanel>
    </div>
  );
}
