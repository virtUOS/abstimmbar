// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Console section "Agenda": show an item on the beamer, open/close/reset
 *  its vote, edit its text while no vote holds it, and — for a closed free
 *  text vote — read the answers and release them to the beamer. */
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Eye, Lock, Pencil, Play, RotateCcw, SquareStop, UserRound } from "lucide-react";
import { stripHtml, type LocalizedText } from "@basicbar/ui";
import { api, requestError, type MeetingAgendaItem, type MeetingManager } from "../api";
import { Button } from "../components/ui";
import TranslatableField from "../components/TranslatableField";
import { TextList, groupNames } from "./MeetingBeamer";

export type ConsoleAction = (fn: () => Promise<unknown>) => Promise<boolean>;

/** A centered modal (backdrop + Escape/backdrop-click cancel), like ConfirmDialog. */
export function Modal({
  label,
  onCancel,
  children,
  wide = false,
}: {
  label: string;
  onCancel: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-slate-900/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={label}
      onClick={onCancel}
    >
      <div
        className={`w-full ${wide ? "max-w-2xl" : "max-w-md"} rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900`}
        onClick={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function ErrorText({ text }: { text: string }) {
  if (!text) return null;
  return <p role="alert" className="text-sm text-danger">{text}</p>;
}

function ResetDialog({
  onConfirm,
  onCancel,
}: {
  onConfirm: (comment: string) => Promise<string>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    const message = await onConfirm(comment.trim());
    setBusy(false);
    if (message) setError(message);
  }
  return (
    <Modal label={t("Reset vote…")} onCancel={onCancel}>
      <div className="grid gap-3">
        <p className="text-slate-700 dark:text-slate-200">
          {t("The result is deleted for good; the minutes only note that the vote was repeated.")}
        </p>
        <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
          {t("Comment (required)")}
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            rows={3}
            className="w-full rounded-lg border border-field bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-600 dark:bg-slate-900 dark:text-slate-100"
          />
        </label>
        <ErrorText text={error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
          <Button
            variant="danger"
            disabled={busy || !comment.trim()}
            onClick={() => void submit()}
          >
            {t("Reset")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function EditTextDialog({
  questionId,
  onSaved,
  onCancel,
}: {
  questionId: number;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState<LocalizedText | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api
      .getQuestion(questionId)
      .then((question) => setText(question.text))
      .catch((err) => setError(t(requestError(err))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [questionId]);
  async function save() {
    if (text === null) return;
    setBusy(true);
    setError("");
    try {
      await api.updateQuestion(questionId, { text });
      onSaved();
    } catch (err) {
      setError(t(requestError(err)));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal label={t("Edit text")} onCancel={onCancel} wide>
      <div className="grid gap-3">
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">{t("Edit text")}</h2>
        {text !== null && (
          <TranslatableField variant="rich" label={t("Question text")} value={text} onChange={setText} />
        )}
        <ErrorText text={error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
          <Button variant="primary" disabled={busy || text === null} onClick={() => void save()}>
            {t("Save")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export default function MeetingAgenda({
  setId,
  data,
  busy,
  act,
  apply,
  onRefresh,
}: {
  setId: number;
  data: MeetingManager;
  busy: boolean;
  act: ConsoleAction;
  apply: (next: MeetingManager) => void;
  /** Reload the console snapshot (after a change the stream may not echo). */
  onRefresh: () => void;
}) {
  const { t } = useTranslation();
  const [resetting, setResetting] = useState<MeetingAgendaItem | null>(null);
  const [editing, setEditing] = useState<MeetingAgendaItem | null>(null);
  const running = data.meeting.state === "started";
  const shown = data.item;

  /** Reset a closed vote; its ballot id is known for the shown item only,
   *  so another item is shown first. Returns an error message or "". */
  async function reset(item: MeetingAgendaItem, comment: string): Promise<string> {
    try {
      let ballotId = shown?.id === item.id ? shown.ballot?.id : undefined;
      if (ballotId === undefined) ballotId = (await api.showItem(setId, item.id)).item?.ballot?.id;
      if (ballotId === undefined) throw new Error("Not found.");
      apply(await api.resetBallot(setId, ballotId, comment));
      setResetting(null);
      return "";
    } catch (err) {
      return t(requestError(err));
    }
  }

  return (
    <section aria-labelledby="console-agenda" className="grid gap-2">
      <h2 id="console-agenda" className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {t("Agenda")}
      </h2>
      <ol className="grid gap-2">
        {data.items.map((item) => {
          const current = shown?.id === item.id;
          const text = stripHtml(item.text).trim();
          const texts = current && item.kind === "open_text" ? data.texts : null;
          const ballot = current ? shown?.ballot ?? null : null;
          return (
            <li
              key={item.id}
              data-testid="console-item"
              className={`grid gap-2 rounded-xl border p-3 ${
                current
                  ? "border-brand-500 bg-brand-50 dark:border-brand-700 dark:bg-brand-950/40"
                  : "border-slate-200 dark:border-slate-800"
              }`}
            >
              <button
                type="button"
                disabled={busy || !running}
                aria-current={current ? "true" : undefined}
                onClick={() => void act(() => api.showItem(setId, item.id))}
                className="flex min-w-0 items-start gap-2 rounded-lg text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600"
              >
                <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                  {t("Item {{number}}", { number: item.number })}
                </span>
                <span className="line-clamp-2 min-w-0 break-words text-sm text-slate-800 dark:text-slate-200">
                  {text}
                </span>
                {current && <Eye aria-hidden className="ml-auto h-4 w-4 shrink-0 text-brand-700 dark:text-brand-400" />}
              </button>
              {item.ballot_status === "open" && (
                <p className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                  {item.named ? <UserRound aria-hidden className="h-3.5 w-3.5" /> : <Lock aria-hidden className="h-3.5 w-3.5" />}
                  {item.named ? t("Vote in progress · named") : t("Vote in progress · secret")}
                </p>
              )}
              {running && (
                <div className="flex flex-wrap gap-1.5">
                  {item.ballot_status === null && (
                    <>
                      <Button
                        variant="primary"
                        disabled={busy || data.open_ballot !== null}
                        onClick={() => void act(() => api.openBallot(setId, item.id))}
                        className="inline-flex items-center gap-1.5"
                      >
                        <Play aria-hidden className="h-4 w-4" />
                        {t("Open vote")}
                      </Button>
                      <Button
                        disabled={busy}
                        onClick={() => setEditing(item)}
                        className="inline-flex items-center gap-1.5"
                      >
                        <Pencil aria-hidden className="h-4 w-4" />
                        {t("Edit text")}
                      </Button>
                    </>
                  )}
                  {item.ballot_status === "open" && data.open_ballot !== null && (
                    <Button
                      variant="primary"
                      disabled={busy}
                      onClick={() => void act(() => api.closeBallot(setId, data.open_ballot!))}
                      className="inline-flex items-center gap-1.5"
                    >
                      <SquareStop aria-hidden className="h-4 w-4" />
                      {t("Close vote")}
                    </Button>
                  )}
                  {item.ballot_status === "closed" && (
                    <Button
                      variant="danger"
                      disabled={busy}
                      onClick={() => setResetting(item)}
                      className="inline-flex items-center gap-1.5 border border-red-200 dark:border-red-900"
                    >
                      <RotateCcw aria-hidden className="h-4 w-4" />
                      {t("Reset vote…")}
                    </Button>
                  )}
                </div>
              )}
              {texts && ballot && (
                <div className="grid gap-2 border-t border-slate-200 pt-2 text-sm dark:border-slate-700">
                  <h3 className="font-medium text-slate-700 dark:text-slate-300">{t("Answers")}</h3>
                  <TextList texts={texts} names={groupNames(ballot)} />
                  {ballot.texts === null && running && texts.length > 0 && (
                    <Button
                      disabled={busy}
                      onClick={() => void act(() => api.releaseTexts(setId, ballot.id))}
                      className="justify-self-start"
                    >
                      {t("Show answers on the beamer")}
                    </Button>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
      {resetting && (
        <ResetDialog
          onConfirm={(comment) => reset(resetting, comment)}
          onCancel={() => setResetting(null)}
        />
      )}
      {editing && (
        <EditTextDialog
          questionId={editing.id}
          onSaved={() => {
            setEditing(null);
            onRefresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
    </section>
  );
}
