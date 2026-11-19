// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** "Insert image" / "Edit image" dialog: the image's description (alt text,
 *  optionally pre-filled by an AI suggestion on request) and its credit.
 *  A native modal `<dialog>`; every way out (Apply, Skip/Cancel, Esc) ends in
 *  its `close` event, which reports the result exactly once.
 *
 *  Deliberately no `<form>`: the dialog sits inside the question editor's
 *  React tree, where a submit would bubble to the host's handlers. */
import { Loader2, Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, detailText, requestError, type ImageCredit } from "../api";
import { ImageCredits } from "./ImageCredits";
import {
  CreditFields,
  EMPTY_CREDIT_DRAFT,
  creditSaveErrors,
  normalizedCredit,
  toCreditDraft,
  type CreditDraft,
} from "./ImageCreditsEditor";
import { Button } from "./ui";

export interface ImageDetailsResult {
  alt: string;
  /** The stored credit, when Apply saved a changed one. */
  credit?: ImageCredit;
}

interface ImageDetailsDialogProps {
  /** The image's relative /media/… URL. */
  src: string;
  /** The uploaded image's id; unknown → no credit fields, no AI suggestion. */
  imageId?: number;
  /** "insert" right after an upload (Skip keeps it without alt text),
   *  "edit" for an image already in the text (Cancel = no change). */
  mode: "insert" | "edit";
  /** Content language of the edited field: the alt text's (and the
   *  suggestion's) language. */
  lang: string;
  alt: string;
  /** The image's current credit (none yet: empty fields). */
  credit?: ImageCredit;
  /** Credit is someone else's (image also used in a foreign room): shown
   *  read-only; the alt text stays editable (it lives in the question). */
  creditEditable: boolean;
  /** Offer the credit fields (needs `imageId`). */
  showCredit?: boolean;
  /** Ask for the alt text (option images have none: credit only). */
  showAlt: boolean;
  /** AI_VISION is on: offer "Suggest" (needs `imageId`). */
  aiVision: boolean;
  /** `{alt}` on Apply, `null` on Skip/Cancel/Esc. */
  onDone: (result: ImageDetailsResult | null) => void;
}

export default function ImageDetailsDialog({
  src,
  imageId,
  mode,
  lang,
  alt: initialAlt,
  credit,
  creditEditable,
  showCredit = true,
  showAlt,
  aiVision,
  onDone,
}: ImageDetailsDialogProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const altId = useId();
  const [alt, setAlt] = useState(initialAlt);
  const initialCredit = credit ? toCreditDraft(credit) : EMPTY_CREDIT_DRAFT;
  const [draft, setDraft] = useState<CreditDraft>(initialCredit);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState("");
  // What the `close` event reports; null = skipped/cancelled.
  const result = useRef<ImageDetailsResult | null>(null);
  const done = useRef(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  const withCredit = showCredit && imageId !== undefined;
  const canSuggest = showAlt && aiVision && imageId !== undefined;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  function handleClose() {
    if (done.current) return;
    done.current = true;
    onDoneRef.current(result.current);
  }

  function finish(value: ImageDetailsResult | null) {
    result.current = value;
    dialogRef.current?.close(); // → handleClose
  }

  /** Only the fields that changed (a stale prefill must not overwrite
   *  newer values), stored the way the backend keeps them. */
  function changedCredit(): Partial<CreditDraft> {
    const before = normalizedCredit(initialCredit);
    const after = normalizedCredit(draft);
    const patch: Partial<CreditDraft> = {};
    for (const key of Object.keys(after) as (keyof CreditDraft)[]) {
      if (after[key] !== before[key]) patch[key] = after[key];
    }
    return patch;
  }

  async function apply() {
    if (saving) return;
    const next: ImageDetailsResult = { alt: alt.trim() };
    const patch = withCredit && creditEditable ? changedCredit() : {};
    if (imageId !== undefined && Object.keys(patch).length) {
      setSaving(true);
      setErrors({});
      setError("");
      try {
        next.credit = await api.updateImageCredit(imageId, patch);
      } catch (err) {
        const { fields, message } = creditSaveErrors(err);
        setErrors(fields);
        setError(message ? detailText(message, t) : "");
        setSaving(false);
        return; // stays open with the input
      }
      setSaving(false);
    }
    finish(next);
  }

  async function suggest() {
    if (imageId === undefined || suggesting) return;
    setSuggesting(true);
    setSuggestError("");
    try {
      const { alt: suggestion } = await api.suggestImageAlt(imageId, lang);
      if (!done.current) setAlt(suggestion);
    } catch (err) {
      if (!done.current) setSuggestError(detailText(requestError(err), t));
    } finally {
      if (!done.current) setSuggesting(false);
    }
  }

  return (
    <dialog
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClose={handleClose}
      // Esc: the browser closes the dialog (result still null = skipped) —
      // but not while the credit is being saved.
      onCancel={(event) => {
        if (saving) event.preventDefault();
      }}
      // Esc belongs to this dialog alone (not to e.g. the guided tour).
      onKeyDown={(event) => {
        if (event.key === "Escape") event.stopPropagation();
      }}
      className="m-auto max-h-[calc(100dvh-2rem)] w-[min(32rem,calc(100vw-2rem))] overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 text-slate-900 shadow-xl backdrop:bg-slate-950/50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
    >
      <h2 id={titleId} className="text-base font-semibold">
        {mode === "insert" ? t("Insert image") : t("Edit image")}
      </h2>
      <img
        src={src}
        alt=""
        className="mt-3 max-h-40 max-w-full rounded-lg border border-slate-200 bg-slate-50 object-contain dark:border-slate-700 dark:bg-slate-950"
      />
      <div className="mt-4 space-y-4">
        {showAlt && (
          <div>
            <label htmlFor={altId} className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              {t("Image description (alt text)")}
            </label>
            <input
              id={altId}
              type="text"
              lang={lang}
              autoFocus
              value={alt}
              aria-describedby={`${altId}-hint`}
              onChange={(event) => setAlt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
                event.preventDefault();
                event.stopPropagation();
                void apply();
              }}
              className="w-full rounded-lg border border-field bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-hidden focus:ring-2 focus:ring-brand-600 focus:ring-offset-2 focus:ring-offset-white dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-offset-slate-950"
            />
            <p id={`${altId}-hint`} className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {t("Describes the image for people who cannot see it.")}
            </p>
            {canSuggest && (
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Button type="button" onClick={() => void suggest()} disabled={suggesting} aria-busy={suggesting}>
                  <span className="inline-flex items-center gap-1.5">
                    {suggesting ? (
                      <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles aria-hidden className="h-4 w-4" />
                    )}
                    {t("Suggest")}
                  </span>
                </Button>
                {suggesting && (
                  <span role="status" className="text-sm text-slate-500 dark:text-slate-400">
                    {t("Creating suggestion …")}
                  </span>
                )}
              </div>
            )}
            {suggestError && (
              <p role="alert" className="mt-2 text-sm text-danger">
                {suggestError}
              </p>
            )}
          </div>
        )}
        {withCredit && (
          <fieldset className="space-y-2">
            <legend className="mb-1 text-sm font-semibold text-slate-700 dark:text-slate-300">
              {t("Image credit (optional)")}
            </legend>
            {creditEditable ? (
              <CreditFields draft={draft} onChange={(patch) => setDraft((d) => ({ ...d, ...patch }))} errors={errors} />
            ) : (
              <>
                {credit?.has_credit && (
                  <ImageCredits credits={[credit]} html="" optionImages={[credit.src]} links={false} />
                )}
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  {t("You can't edit this image credit; the image is also used in a room that isn't yours.")}
                </p>
              </>
            )}
          </fieldset>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
      </div>
      <div className="mt-5 flex flex-wrap justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => finish(null)} disabled={saving}>
          {mode === "insert" ? t("Skip") : t("Cancel")}
        </Button>
        <Button type="button" variant="primary" onClick={() => void apply()} disabled={saving}>
          {t("Apply")}
        </Button>
      </div>
    </dialog>
  );
}
