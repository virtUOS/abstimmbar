/** The chair reviews the wording of an agenda item in both languages and
 *  confirms the translation; until then English-speaking members see the
 *  original text (spec § 7.6). Confirming is bound to the digest the dialog
 *  loaded, so a text changed in the meantime is never confirmed unseen. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { RichText } from "@basicbar/ui";
import { api, requestBody, requestError, type ItemTranslation } from "../api";
import { Button } from "../components/ui";
import { Modal } from "./MeetingAgenda";

const CONFIRM_ERRORS: Record<string, string> = {
  stale: "The text has changed in the meantime. Please review it again.",
  vote_open: "The translation cannot be confirmed while a vote is open.",
  empty: "The translation is empty.",
};

const RICH =
  "break-words text-sm text-slate-800 dark:text-slate-200 [&_ol]:list-decimal [&_ol]:pl-6 [&_ul]:list-disc [&_ul]:pl-6";

export default function TranslationReviewDialog({
  setId,
  questionId,
  onDone,
  onCancel,
}: {
  setId: number;
  questionId: number;
  /** Called after a successful confirmation. */
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [data, setData] = useState<ItemTranslation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    return api
      .getItemTranslation(setId, questionId)
      .then(setData)
      .catch((err) => setError(t(requestError(err))));
  }
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setId, questionId]);

  async function confirm() {
    if (!data) return;
    setBusy(true);
    setError("");
    try {
      await api.confirmItemTranslation(setId, questionId, data.digest);
      onDone();
    } catch (err) {
      const code = requestBody(err)?.code;
      setError(t((typeof code === "string" && CONFIRM_ERRORS[code]) || requestError(err)));
      // A changed text: show the current one.
      if (code === "stale") await load();
    } finally {
      setBusy(false);
    }
  }

  const name = (lang: "de" | "en") => t(lang === "de" ? "German" : "English");
  return (
    <Modal label={t("Review translation")} onCancel={onCancel} wide>
      <div className="grid gap-3" data-testid="translation-dialog">
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">{t("Review translation")}</h2>
        <p className="text-sm text-slate-600 dark:text-slate-400">
          {t("English-speaking members see the original text until you confirm the translation.")}
        </p>
        {data && (
          <div className="grid gap-3 sm:grid-cols-2">
            {([data.canonical, data.other] as const).map((lang, index) => (
              <section key={lang} className="grid content-start gap-2" aria-label={name(lang)}>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {name(lang)}
                  {index === 0 && ` · ${t("original")}`}
                </h3>
                {data.text[lang].trim() ? (
                  <RichText className={RICH} html={data.text[lang]} />
                ) : (
                  <p className="text-sm italic text-slate-500">{t("(empty)")}</p>
                )}
                {data.options.length > 0 && (
                  <ul className="grid gap-1 text-sm text-slate-800 dark:text-slate-200">
                    {data.options.map((option) => (
                      <li key={option.id} className="rounded-lg border border-slate-200 px-2 py-1 dark:border-slate-700">
                        {option.text[lang] || <span className="italic text-slate-500">{t("(empty)")}</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            ))}
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
          <Button variant="primary" disabled={busy || data === null} onClick={() => void confirm()}>
            {t("Confirm translation")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
