import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, requestBody, requestError, type ImageCredit } from "../api";
import { ImageCredits } from "./ImageCredits";
import { Button, Field, Select, TextInput } from "./ui";

const LICENSES: [string, string][] = [
  ["cc-by", "CC BY"],
  ["cc-by-sa", "CC BY-SA"],
  ["cc-by-nd", "CC BY-ND"],
  ["cc-by-nc", "CC BY-NC"],
  ["cc-by-nc-sa", "CC BY-NC-SA"],
  ["cc-by-nc-nd", "CC BY-NC-ND"],
  ["cc0", "CC0"],
];

/** The editable part of an image credit. */
export type CreditDraft = Pick<ImageCredit, "author" | "title" | "source" | "license" | "version" | "text">;

export const EMPTY_CREDIT_DRAFT: CreditDraft = {
  author: "",
  title: "",
  source: "",
  license: "",
  version: "",
  text: "",
};

export const toCreditDraft = (c: CreditDraft): CreditDraft => ({
  author: c.author,
  title: c.title,
  source: c.source,
  license: c.license,
  version: c.version,
  text: c.text,
});

/** "Other" needs the note; "All rights reserved" may carry one (H5P extras). */
const licenseHasNote = (license: string) => license === "other" || license === "arr";

/** The draft as stored: the version only for CC licenses, the note only
 *  where the license takes one. */
export function normalizedCredit(draft: CreditDraft): CreditDraft {
  return {
    ...draft,
    version: draft.license.startsWith("cc-") ? draft.version : "",
    text: licenseHasNote(draft.license) ? draft.text : "",
  };
}

/** A failed credit save, split into per-field messages (400) or one message. */
export function creditSaveErrors(err: unknown): { fields: Record<string, string>; message: string } {
  const body = requestBody(err);
  const fields: Record<string, string> = {};
  for (const [k, v] of Object.entries(body ?? {})) {
    const m = Array.isArray(v) ? v[0] : v;
    if (typeof m === "string") fields[k] = m;
  }
  if (Object.keys(fields).length && !fields.detail) return { fields, message: "" };
  return { fields: {}, message: requestError(err) };
}

/** The credit inputs (author, title, source, license, version, note) — used
 *  by the "Image credits" cards and by the image dialog. */
export function CreditFields({
  draft,
  onChange: set,
  errors = {},
}: {
  draft: CreditDraft;
  onChange: (patch: Partial<CreditDraft>) => void;
  errors?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const isCc = draft.license.startsWith("cc-");
  const hasNote = licenseHasNote(draft.license);
  const err = (k: string) =>
    errors[k] ? (
      <span role="alert" className="mt-1 block text-sm text-danger">
        {errors[k]}
      </span>
    ) : null;
  return (
    <>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label={t("Author")}>
          <TextInput value={draft.author} maxLength={200} onChange={(e) => set({ author: e.target.value })} />
          {err("author")}
        </Field>
        <Field label={t("Title")}>
          <TextInput value={draft.title} maxLength={300} onChange={(e) => set({ title: e.target.value })} />
          {err("title")}
        </Field>
      </div>
      <Field label={t("Source (link)")}>
        <TextInput
          type="url"
          inputMode="url"
          placeholder="https://"
          maxLength={500}
          value={draft.source}
          onChange={(e) => set({ source: e.target.value })}
        />
        {err("source")}
      </Field>
      <div className="grid gap-2 sm:grid-cols-2">
        <Field label={t("License")}>
          <Select value={draft.license} onChange={(e) => set({ license: e.target.value })}>
            <option value="">{t("Unknown")}</option>
            {LICENSES.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
            <option value="pd">{t("Public domain")}</option>
            <option value="arr">{t("All rights reserved")}</option>
            <option value="other">{t("Other")}</option>
          </Select>
          {err("license")}
        </Field>
        {isCc && (
          <Field label={t("Version")}>
            <TextInput
              inputMode="decimal"
              placeholder="4.0"
              maxLength={8}
              value={draft.version}
              onChange={(e) => set({ version: e.target.value })}
            />
            {err("version")}
          </Field>
        )}
      </div>
      {hasNote && (
        <Field label={t("License note")}>
          <TextInput value={draft.text} maxLength={100} onChange={(e) => set({ text: e.target.value })} />
          {err("text")}
        </Field>
      )}
    </>
  );
}

/** Editor section "Image credits" (#336): one card per image of the saved
 *  question, saved individually (the credit belongs to the image file and
 *  applies everywhere it is used). */
export default function ImageCreditsEditor({ credits }: { credits: ImageCredit[] }) {
  const { t } = useTranslation();
  if (!credits.length) return null;
  return (
    <section data-testid="image-credits-editor" className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{t("Image credits")}</h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        {t("Optional. The credit is shown to participants and on the presenter view; it belongs to the image file and applies wherever it is used.")}
      </p>
      <ul className="mt-3 space-y-4">
        {credits.map((c) => (
          <CreditCard key={c.id} credit={c} />
        ))}
      </ul>
    </section>
  );
}

function CreditCard({ credit }: { credit: ImageCredit }) {
  const { t } = useTranslation();
  const [saved, setSaved] = useState(credit);
  const [draft, setDraft] = useState<CreditDraft>(toCreditDraft(credit));
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const readOnly = saved.editable === false;

  const dirty = (Object.keys(draft) as (keyof CreditDraft)[]).some((k) => draft[k] !== saved[k]);
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  // Fresh server state (e.g. the question was saved again): take it over,
  // but only when the stored credit actually changed — a refetch hands in a
  // new object every time — and never overwrite unsaved input.
  const creditKey = JSON.stringify([credit.id, credit.editable, credit.has_credit, toCreditDraft(credit)]);
  useEffect(() => {
    setSaved(credit);
    if (!dirtyRef.current) setDraft(toCreditDraft(credit));
    // Keyed by content, not identity (see above).
  }, [creditKey]);

  const set = (patch: Partial<CreditDraft>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setDone(false);
  };
  const save = async () => {
    setBusy(true);
    setErrors({});
    setError("");
    try {
      const updated = await api.updateImageCredit(saved.id, normalizedCredit(draft));
      const next = { ...saved, ...updated };
      setSaved(next);
      setDraft(toCreditDraft(next));
      setDone(true);
    } catch (err) {
      const { fields, message } = creditSaveErrors(err);
      setErrors(fields);
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <li data-testid="image-credit-card" className="flex flex-col gap-3 sm:flex-row">
      <img
        src={saved.src}
        alt=""
        className="h-20 w-20 shrink-0 rounded-lg border border-slate-200 bg-slate-50 object-contain dark:border-slate-700 dark:bg-slate-900"
      />
      <div className="min-w-0 flex-1 space-y-2">
        {!saved.has_credit && (
          <p data-testid="no-image-credit" className="text-sm text-slate-500 dark:text-slate-400">
            {t("No image credit")}
          </p>
        )}
        <ImageCredits credits={[saved]} html="" optionImages={[saved.src]} links={false} />
        {readOnly ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t("You can't edit this image credit; the image is also used in a room that isn't yours.")}
          </p>
        ) : (
          <>
            <CreditFields draft={draft} onChange={set} errors={errors} />
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" onClick={save} disabled={busy || !dirty}>
                {t("Save credit")}
              </Button>
              {done && !dirty && (
                <span role="status" className="text-sm text-slate-500 dark:text-slate-400">
                  {t("Saved")}
                </span>
              )}
            </div>
            {error && (
              <p role="alert" className="text-sm text-danger">
                {error}
              </p>
            )}
          </>
        )}
      </div>
    </li>
  );
}
