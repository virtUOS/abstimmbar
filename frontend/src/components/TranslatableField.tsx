// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Thin Abstimmbar wrapper around @basicbar/ui's TranslatableField.
 *
 * Keeps the tool's own conventions on top of the shared component: the
 * map-based value contract (`LocalizedText` + `onChange(next)`), the
 * rich-text variant (the shared RichTextEditor from @basicbar/ui, plugged
 * in via `renderInput`), easy mode (#52: non-staff simple users author in a single
 * canonical language; staff are always Pro) and the prominent form label. */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  TranslatableField as BaseTranslatableField,
  localizedMap,
  setLocalizedLang,
  type LocalizedText,
} from "@basicbar/ui";
import { RichTextEditor, type InsertedImage } from "@basicbar/ui/rich-text-editor";
import { useApp, useEasyMode, type AppContext } from "../App";
import { api, requestError, type ImageCredit } from "../api";
import ImageDetailsDialog, { type ImageDetailsResult } from "./ImageDetailsDialog";

export type TranslatableFieldVariant = "input" | "rich";

/** Images uploaded in this page session (`/media/…` URL → id and the credit
 *  saved for it in the dialog): an image not yet in a saved question has no
 *  other source for its id. Module-level, so it survives a field remount
 *  (e.g. switching language tabs). */
const uploadedImages = new Map<string, { id: number; credit?: ImageCredit }>();

interface PendingImageDialog {
  /** Per request: a new dialog never reuses the previous one's state. */
  key: number;
  image: InsertedImage;
  lang: string;
  resolve: (answer: { alt: string } | null) => void;
}

const INPUT_CLASS =
  "w-full rounded-lg border border-field bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-hidden focus:ring-2 focus:ring-brand-600 focus:ring-offset-2 focus:ring-offset-white dark:focus:ring-offset-slate-950 dark:bg-slate-900 dark:text-slate-100";

interface TranslatableFieldProps {
  /** The field's current value — a legacy plain string or a `{de, en}` map. */
  value: LocalizedText;
  onChange: (next: LocalizedText) => void;
  label?: string;
  /** Accessible name when there is no visible `label` (e.g. a list row). */
  ariaLabel?: string;
  variant?: TranslatableFieldVariant;
  placeholder?: string;
  hint?: string;
  required?: boolean;
  className?: string;
  labelAddon?: ReactNode;
  /** Extra classes appended to the input; ignored for the rich variant. */
  inputClassName?: string;
  onBlur?: () => void;
  onActiveLangChange?: (lang: "de" | "en") => void;
  /** Language codes whose translation is outdated (#91): amber tab dot +
   *  hint, and enables the per-field re-translate button even when the
   *  field is non-empty. */
  stale?: readonly string[];
  /** Renders "Mark as up to date" on a stale tab. */
  onMarkSynced?: () => void;
  /** Fires right after a machine-translation pre-fill (languages now in
   *  sync). */
  onTranslated?: (lang: string, text: string) => void;
  /** Rich variant: the credits of the images the edited object already has
   *  (`Question.image_credits`). Given → the image dialog offers the credit
   *  fields (credits are shown for question images only). */
  imageCredits?: ImageCredit[];
  /** A credit was saved from the image dialog. */
  onImageCreditSaved?: (credit: ImageCredit) => void;
}

export default function TranslatableField({
  value,
  onChange,
  variant = "input",
  inputClassName = "",
  onActiveLangChange,
  className = "",
  imageCredits,
  onImageCreditSaved,
  ...rest
}: TranslatableFieldProps) {
  const easyMode = useEasyMode();
  // Outside the app shell (no outlet context) there is no whoami: no AI.
  const aiVision = !!(useApp() as AppContext | undefined)?.whoami?.ai_vision_enabled;
  const { t } = useTranslation();
  const [imageDialog, setImageDialog] = useState<PendingImageDialog | null>(null);
  const pendingDialog = useRef<PendingImageDialog | null>(null);
  const dialogKey = useRef(0);
  // The editor waits for every answer (its dialogs run one after another):
  // never leave one pending when the field goes away.
  useEffect(() => () => pendingDialog.current?.resolve(null), []);
  /** Rich-text image upload for the shared editor: stores the file in our
   *  media storage and returns its relative /media/… URL (the only kind the
   *  backend sanitizer keeps). The editor shows the error's message inline, so
   *  hand it the translated server detail, not the raw JSON body (#280). */
  async function uploadEditorImage(file: File): Promise<string> {
    try {
      const { id, url } = await api.uploadImage(file);
      uploadedImages.set(url, { id });
      return url;
    } catch (err) {
      throw new Error(t(requestError(err)));
    }
  }

  /** The editor's image dialog (after an upload / "Image description"). */
  function askImageDetails(image: InsertedImage, lang: string) {
    return new Promise<{ alt: string } | null>((resolve) => {
      // The editor never overlaps its calls; should one still be pending,
      // settle it rather than leave the editor waiting forever.
      pendingDialog.current?.resolve(null);
      const next = { key: ++dialogKey.current, image, lang, resolve };
      pendingDialog.current = next;
      setImageDialog(next);
    });
  }

  function finishImageDialog(result: ImageDetailsResult | null) {
    const pending = pendingDialog.current;
    if (!pending) return;
    if (result?.credit) {
      const uploaded = uploadedImages.get(pending.image.src);
      if (uploaded) uploadedImages.set(pending.image.src, { ...uploaded, credit: result.credit });
      onImageCreditSaved?.(result.credit);
    }
    pendingDialog.current = null;
    setImageDialog(null);
    pending.resolve(result ? { alt: result.alt } : null);
  }

  function renderImageDialog({ key, image, lang }: PendingImageDialog) {
    const known = imageCredits?.find((c) => c.src === image.src);
    const uploaded = uploadedImages.get(image.src);
    return (
      <ImageDetailsDialog
        key={key}
        src={image.src}
        imageId={known?.id ?? uploaded?.id}
        mode={image.mode}
        lang={lang}
        alt={image.alt}
        credit={known ?? uploaded?.credit}
        // Own uploads are always editable.
        creditEditable={known ? known.editable !== false : true}
        showCredit={imageCredits !== undefined}
        showAlt
        aiVision={aiVision}
        onDone={finishImageDialog}
      />
    );
  }
  return (
    <BaseTranslatableField
      {...rest}
      // Space the label/language-tab row off the input so the input's focus
      // ring doesn't crowd the DE/EN tags above it.
      className={`space-y-1.5 ${className}`.trim()}
      values={localizedMap(value)}
      onChange={(lang, text) => onChange(setLocalizedLang(value, lang, text))}
      singleLanguage={easyMode}
      format={variant === "rich" ? "html" : "text"}
      inputClass={`${INPUT_CLASS} ${inputClassName}`.trim()}
      labelClassName="text-sm font-medium text-slate-700 dark:text-slate-300"
      onActiveLangChange={
        onActiveLangChange
          ? (lang) => onActiveLangChange(lang as "de" | "en")
          : undefined
      }
      renderInput={
        variant === "rich"
          ? ({ lang, value: html, onChange: set, labelId, describedBy }) => (
              <div>
                <RichTextEditor
                  key={lang}
                  value={html}
                  onChange={set}
                  labelledBy={labelId}
                  describedBy={describedBy}
                  onUploadImage={uploadEditorImage}
                  onImageInserted={(image) => askImageDetails(image, lang)}
                />
                {imageDialog && renderImageDialog(imageDialog)}
              </div>
            )
          : undefined
      }
    />
  );
}
