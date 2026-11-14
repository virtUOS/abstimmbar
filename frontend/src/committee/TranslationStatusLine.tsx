/** Meeting item editor: review status of the saved wording's translation,
 *  with the same review dialog as the console. Reflects the stored item, so
 *  it reloads whenever the item was saved (`savedKey`). */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { api, type TranslationStatus } from "../api";
import { Button } from "../components/ui";
import TranslationReviewDialog from "./TranslationReviewDialog";

export default function TranslationStatusLine({
  setId,
  questionId,
  savedKey,
}: {
  setId: number;
  questionId: number;
  savedKey: unknown;
}) {
  const { t } = useTranslation();
  const [status, setStatus] = useState<TranslationStatus>("none");
  const [reviewing, setReviewing] = useState(false);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let live = true;
    api
      .getItemTranslation(setId, questionId)
      .then((data) => live && setStatus(data.status))
      .catch(() => live && setStatus("none"));
    return () => {
      live = false;
    };
  }, [setId, questionId, savedKey, nonce]);
  if (status === "none") return null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-sm" data-testid="translation-line">
      {status === "pending" ? (
        <>
          <span className="font-medium text-amber-700 dark:text-amber-400" data-testid="translation-status">
            {t("Translation not confirmed")}
          </span>
          <Button onClick={() => setReviewing(true)} data-testid="translation-review">
            {t("Review and confirm")}
          </Button>
        </>
      ) : (
        <span className="text-slate-500 dark:text-slate-400" data-testid="translation-status">
          {t("Translation confirmed")}
        </span>
      )}
      {reviewing && (
        <TranslationReviewDialog
          setId={setId}
          questionId={questionId}
          onDone={() => {
            setReviewing(false);
            setNonce((n) => n + 1);
          }}
          onCancel={() => setReviewing(false)}
        />
      )}
    </div>
  );
}
