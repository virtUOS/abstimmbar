// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Console section "Agenda": show an item on the beamer, open/close/reset
 *  its vote, edit its text while no vote holds it, and — for a closed free
 *  text vote — read the answers and release them to the beamer. Grouped by
 *  TOP (a TOP header shows the TOP itself); resolutions can be added during
 *  the meeting and several resolutions voted on en bloc. */
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Eye, Layers, Lock, Pencil, Play, Repeat, RotateCcw, SquareStop, UserRound } from "lucide-react";
import { stripHtml, type LocalizedText } from "@basicbar/ui";
import {
  api,
  requestBody,
  requestError,
  type MeetingAgendaItem,
  type MeetingBallot,
  type MeetingItem,
  type MeetingManager,
} from "../api";
import { Button, ToggleSwitch } from "../components/ui";
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

/** English source strings (translation keys) for ballot error codes whose
 *  backend detail is too technical for the chair. */
const OPEN_ERRORS: Record<string, string> = {
  no_candidates: "The election has no candidates.",
  too_many_votes: "There are fewer candidates than votes per person.",
};
const RUNOFF_ERRORS: Record<string, string> = {
  runoff_candidates: "Choose at least two candidates.",
  runoff_exists: "A runoff is already running for this election.",
};
const RESET_ERRORS: Record<string, string> = {
  runoff_exists: "Reset the runoff first.",
};

/** The error of a failed request as a translation key: `messages[code]`
 *  if listed, else the server's detail. */
function codedError(err: unknown, messages: Record<string, string>): string {
  const code = requestBody(err)?.code;
  return (typeof code === "string" && messages[code]) || requestError(err);
}

/** Pick the candidates of a runoff: preselected from the round's proposal,
 *  each with its total votes. Returns an error message or "". */
function RunoffDialog({
  item,
  ballot,
  onConfirm,
  onCancel,
}: {
  item: MeetingItem;
  ballot: MeetingBallot;
  onConfirm: (candidates: number[]) => Promise<string>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [picked, setPicked] = useState<number[]>(ballot.election?.proposal ?? []);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const counts = ballot.result?.total.counts ?? {};
  async function submit() {
    setBusy(true);
    const message = await onConfirm(item.options.map((o) => o.id).filter((id) => picked.includes(id)));
    setBusy(false);
    if (message) setError(message);
  }
  return (
    <Modal label={t("Start runoff")} onCancel={onCancel}>
      <div className="grid gap-3" data-testid="runoff-dialog">
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">{t("Start runoff")}</h2>
        <p className="text-sm text-slate-700 dark:text-slate-200">
          {t("Choose the candidates for the runoff. It opens immediately; each person has one vote.")}
        </p>
        <fieldset className="grid gap-1.5">
          <legend className="sr-only">{t("Candidates")}</legend>
          {item.options.map((option, index) => (
            <label
              key={option.id}
              className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700"
            >
              <input
                type="checkbox"
                data-testid="runoff-candidate"
                autoFocus={index === 0}
                checked={picked.includes(option.id)}
                onChange={(event) =>
                  setPicked(
                    event.target.checked
                      ? [...picked, option.id]
                      : picked.filter((id) => id !== option.id),
                  )
                }
                className="h-4 w-4 shrink-0 accent-brand-600"
              />
              <span className="min-w-0 flex-1 break-words text-slate-900 dark:text-slate-100">{option.text}</span>
              <span className="shrink-0 tabular-nums text-slate-600 dark:text-slate-300">
                {t("{{count}} votes", { count: counts[`opt:${option.id}`] ?? 0 })}
              </span>
            </label>
          ))}
        </fieldset>
        <ErrorText text={error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
          <Button
            variant="primary"
            data-testid="runoff-confirm"
            disabled={busy || picked.length < 2}
            onClick={() => void submit()}
          >
            {t("Start runoff")}
          </Button>
        </div>
      </div>
    </Modal>
  );
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

/** Inline form: a resolution added during the meeting. */
function ResolutionForm({
  busy,
  onSubmit,
  onCancel,
}: {
  busy: boolean;
  onSubmit: (text: string, named: boolean) => Promise<boolean>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [named, setNamed] = useState(false);
  return (
    <div data-testid="resolution-form" className="grid w-full gap-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
        {t("Resolution text")}
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={3}
          maxLength={1000}
          autoFocus
          className="w-full rounded-lg border border-field bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-600 dark:bg-slate-900 dark:text-slate-100"
        />
      </label>
      <ToggleSwitch checked={named} onChange={setNamed} label={t("Roll-call vote")} icon={UserRound} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          {t("Cancel")}
        </Button>
        <Button
          variant="primary"
          disabled={busy || !text.trim()}
          onClick={() => void onSubmit(text.trim(), named)}
        >
          {t("Add")}
        </Button>
      </div>
    </div>
  );
}

/** The chair's note on a TOP for the protocol: shown as text with a pencil
 *  to edit, or a "+ Note" button; saving empty text deletes it. */
export function TopNote({
  text,
  editable,
  busy,
  onSave,
  addExtra,
}: {
  text: string;
  editable: boolean;
  busy: boolean;
  onSave: (text: string) => Promise<boolean>;
  /** Rendered next to the "+ Note" button (the section's "+ Resolution"). */
  addExtra?: ReactNode;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(text);
  if (open)
    return (
      <div data-testid="note-form" className="grid gap-2 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
        <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
          {t("Note for the minutes")}
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={3}
            maxLength={2000}
            autoFocus
            className="w-full rounded-lg border border-field bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-600 dark:bg-slate-900 dark:text-slate-100"
          />
        </label>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setOpen(false)}>
            {t("Cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => void onSave(draft.trim()).then((ok) => ok && setOpen(false))}
          >
            {t("Save")}
          </Button>
        </div>
      </div>
    );
  function edit() {
    setDraft(text);
    setOpen(true);
  }
  return (
    <>
      {text && (
        <div data-testid="top-note" className="flex min-w-0 items-start gap-2 text-sm text-slate-700 dark:text-slate-300">
          <p className="min-w-0 flex-1 whitespace-pre-line break-words">
            <span className="font-semibold">{t("Note")}: </span>
            {text}
          </p>
          {editable && (
            <button
              type="button"
              disabled={busy}
              onClick={edit}
              aria-label={t("Edit note")}
              className="shrink-0 rounded p-1 text-slate-500 hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 dark:hover:text-slate-100"
            >
              <Pencil aria-hidden className="h-4 w-4" />
            </button>
          )}
        </div>
      )}
      {editable && (
        <div className="flex flex-wrap gap-1.5">
          {addExtra}
          {!text && (
            <Button variant="ghost" disabled={busy} onClick={edit} className="justify-self-start">
              {t("+ Note")}
            </Button>
          )}
        </div>
      )}
      {!editable && !text && addExtra}
    </>
  );
}

/** Where the inline resolution form is open: a TOP's section, or the end. */
type AddTarget = { section: number | null } | null;

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
  const [runoff, setRunoff] = useState(false);
  const [adding, setAdding] = useState<AddTarget>(null);
  const [selecting, setSelecting] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const running = data.meeting.state === "started";
  const shown = data.item;
  const voteOpen = data.open_ballot !== null;
  const byId = new Map(data.items.map((item) => [item.id, item]));
  // Resolutions not voted on yet and not part of an en bloc vote.
  const bundleable = (item: MeetingAgendaItem) =>
    item.kind === "resolution" && item.ballot_status === null && item.bundle_lead === null;
  const selected = picked.filter((id) => {
    const item = byId.get(id);
    return item !== undefined && bundleable(item);
  });

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
      return t(codedError(err, RESET_ERRORS));
    }
  }

  /** Open a runoff of the shown, closed election round. */
  async function startRunoff(ballotId: number, candidates: number[]): Promise<string> {
    try {
      apply(await api.openRunoff(setId, ballotId, candidates));
      setRunoff(false);
      return "";
    } catch (err) {
      return t(codedError(err, RUNOFF_ERRORS));
    }
  }

  async function addResolution(section: number | null, text: string, named: boolean) {
    const ok = await act(() => api.addMeetingResolution(setId, { text, section, named }));
    if (ok) setAdding(null);
    return ok;
  }

  async function voteEnBloc() {
    const ok = await act(() => api.openBundle(setId, selected));
    if (ok) {
      setSelecting(false);
      setPicked([]);
    }
  }

  function toggleSelecting() {
    setSelecting(!selecting);
    setPicked([]);
  }

  const noteText = (target: { section: number } | { question: number }) =>
    data.notes?.find((note) =>
      "section" in target ? note.section === target.section : note.question === target.question,
    )?.text ?? "";
  // Standalone-question TOPs: the note belongs to the question.
  const soloTop = new Set(data.tops.filter((top) => top.section === null).flatMap((top) => top.items));

  function saveNote(target: { section: number } | { question: number }) {
    return async (text: string) => act(() => api.setMeetingNote(setId, target, text));
  }

  function addButton(section: number | null) {
    const open = adding !== null && adding.section === section;
    if (open)
      return (
        <ResolutionForm
          busy={busy || !running}
          onSubmit={(text, named) => addResolution(section, text, named)}
          onCancel={() => setAdding(null)}
        />
      );
    return (
      <Button
        variant="ghost"
        disabled={busy || !running}
        onClick={() => setAdding({ section })}
        className="justify-self-start"
      >
        {section === null ? t("+ Resolution as new TOP") : t("+ Resolution")}
      </Button>
    );
  }

  const beamerBadge = (
    <span className="ml-auto inline-flex shrink-0 items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5 text-xs font-semibold text-brand-800 dark:bg-brand-900/50 dark:text-brand-300">
      <Eye aria-hidden className="h-3.5 w-3.5" />
      {t("On the beamer")}
    </span>
  );

  function renderItem(item: MeetingAgendaItem) {
    const current = shown?.id === item.id;
    const text = stripHtml(item.text).trim();
    const texts = current && item.kind === "open_text" ? data.texts : null;
    const ballot = current ? shown?.ballot ?? null : null;
    // The ballot pages follow the shown item: while a vote is open,
    // showing another item would hide it from every voter.
    const showBlocked = voteOpen && item.ballot_status !== "open";
    const lead = item.bundle_lead !== null ? byId.get(item.bundle_lead) : undefined;
    const pickable = selecting && bundleable(item);
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
        <div className="flex min-w-0 items-start gap-2">
          {pickable && (
            <input
              type="checkbox"
              checked={selected.includes(item.id)}
              onChange={(event) =>
                setPicked(
                  event.target.checked
                    ? [...selected, item.id]
                    : selected.filter((id) => id !== item.id),
                )
              }
              aria-label={t("TOP {{number}}", { number: item.label })}
              className="mt-1 h-4 w-4 shrink-0 accent-brand-600"
            />
          )}
          <button
            type="button"
            disabled={busy || !running || showBlocked}
            title={
              !running
                ? undefined
                : showBlocked
                  ? t("Another vote is still open.")
                  : current
                    ? undefined
                    : t("Show on the beamer")
            }
            aria-current={current ? "true" : undefined}
            onClick={() => void act(() => api.showItem(setId, item.id))}
            className="flex min-w-0 flex-1 flex-wrap items-start gap-2 rounded-lg text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600"
          >
            <span className="shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
              {t("TOP {{number}}", { number: item.label })}
            </span>
            <span className="line-clamp-2 min-w-[8rem] flex-1 break-words text-sm text-slate-800 dark:text-slate-200">
              {text}
            </span>
            {current && beamerBadge}
          </button>
        </div>
        {lead && (
          <p className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-600 dark:text-slate-400">
            <Layers aria-hidden className="h-3.5 w-3.5" />
            {t("en bloc with TOP {{label}}", { label: lead.label })}
          </p>
        )}
        {item.ballot_status === "open" && (
          <p className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
            {item.named ? <UserRound aria-hidden className="h-3.5 w-3.5" /> : <Lock aria-hidden className="h-3.5 w-3.5" />}
            {item.named ? t("Vote in progress · named") : t("Vote in progress · secret")}
          </p>
        )}
        {running && !lead && (
          <div className="flex flex-wrap gap-1.5">
            {item.ballot_status === null && (
              <>
                <Button
                  variant="primary"
                  disabled={busy || voteOpen}
                  onClick={() =>
                    void act(async () => {
                      try {
                        return await api.openBallot(setId, item.id);
                      } catch (err) {
                        // `act` shows the message (a translation key).
                        throw new Error(codedError(err, OPEN_ERRORS));
                      }
                    })
                  }
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
                onClick={() =>
                  void act(async () => {
                    try {
                      return await api.closeBallot(setId, data.open_ballot!);
                    } catch (err) {
                      // The last vote already closed it: nothing to report.
                      if (requestBody(err)?.code === "not_open") return undefined;
                      throw err;
                    }
                  })
                }
                className="inline-flex items-center gap-1.5"
              >
                <SquareStop aria-hidden className="h-4 w-4" />
                {t("Close vote")}
              </Button>
            )}
            {item.ballot_status === "closed" && (
              <Button
                variant="danger"
                disabled={busy || voteOpen}
                title={voteOpen ? t("Another vote is still open.") : undefined}
                onClick={() => setResetting(item)}
                className="inline-flex items-center gap-1.5 border border-red-200 dark:border-red-900"
              >
                <RotateCcw aria-hidden className="h-4 w-4" />
                {t("Reset vote…")}
              </Button>
            )}
          </div>
        )}
        {soloTop.has(item.id) && (running || noteText({ question: item.id })) && (
          <TopNote
            key={noteText({ question: item.id })}
            text={noteText({ question: item.id })}
            editable={running}
            busy={busy}
            onSave={saveNote({ question: item.id })}
          />
        )}
        {ballot && ballot.status === "closed" && (
          <div className="grid gap-2">
            {ballot.result &&
              ballot.result.voted !== null &&
              ballot.result.voted !== ballot.result.tally_sum && (
                <p role="alert" data-testid="count-check-warning" className="text-sm text-danger">
                  {t("Count check failed: {{voted}} marked as voted, {{tally}} ballots counted.", {
                    voted: ballot.result.voted,
                    tally: ballot.result.tally_sum,
                  })}
                </p>
              )}
            {running && ballot.election?.proposal && (
              <Button
                disabled={busy || voteOpen}
                title={voteOpen ? t("Another vote is still open.") : undefined}
                onClick={() => setRunoff(true)}
                data-testid="runoff-start"
                className="inline-flex items-center gap-1.5 justify-self-start"
              >
                <Repeat aria-hidden className="h-4 w-4" />
                {t("Start runoff")}
              </Button>
            )}
            {/* A test run records no findings (backend code "trial"). */}
            {!data.trial && (
              <div role="group" aria-label={t("Finding")} className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                  {t("Finding")}
                </span>
                {(
                  [
                    ["adopted", t("Adopted")],
                    ["rejected", t("Rejected")],
                    ["", t("Leave open")],
                  ] as const
                ).map(([value, label]) => (
                  <Button
                    key={value || "open"}
                    variant={ballot.finding === value ? "primary" : "ghost"}
                    aria-pressed={ballot.finding === value}
                    disabled={busy}
                    onClick={() => void act(() => api.setBallotFinding(setId, ballot.id, value))}
                  >
                    {label}
                  </Button>
                ))}
              </div>
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
  }

  // Items outside every TOP (should not happen) still get listed.
  const grouped = new Set(data.tops.flatMap((top) => top.items));
  const loose = data.items.filter((item) => !grouped.has(item.id));

  return (
    <section aria-labelledby="console-agenda" className="grid gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="console-agenda" className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          {t("Agenda")}
        </h2>
        <div className="flex flex-wrap gap-1.5">
          <Button
            variant="ghost"
            disabled={busy || !running}
            aria-pressed={selecting}
            onClick={toggleSelecting}
            className="inline-flex items-center gap-1.5"
          >
            <Layers aria-hidden className="h-4 w-4" />
            {t("Combine votes …")}
          </Button>
          {selecting && (
            <Button
              variant="primary"
              disabled={busy || !running || voteOpen || selected.length < 2}
              title={voteOpen ? t("Another vote is still open.") : undefined}
              onClick={() => void voteEnBloc()}
            >
              {t("Vote en bloc ({{count}})", { count: selected.length })}
            </Button>
          )}
        </div>
      </div>
      <ol className="grid gap-3">
        {data.tops.map((top) => {
          const items = top.items
            .map((id) => byId.get(id))
            .filter((item): item is MeetingAgendaItem => item !== undefined);
          // A vote before the first section is its own TOP: its card is the TOP.
          if (top.section === null)
            return <Fragment key={`q${top.items[0] ?? top.number}`}>{items.map(renderItem)}</Fragment>;
          const section = top.section;
          const topShown = shown === null && data.top?.number === top.number;
          const title = stripHtml(top.title).trim();
          return (
            <li key={`s${section}`} data-testid="console-top" className="grid gap-2">
              <button
                type="button"
                disabled={busy || !running || voteOpen}
                title={
                  !running
                    ? undefined
                    : voteOpen
                      ? t("Another vote is still open.")
                      : topShown
                        ? undefined
                        : t("Show on the beamer")
                }
                aria-current={topShown ? "true" : undefined}
                onClick={() => void act(() => api.showTop(setId, section))}
                className={`flex min-w-0 flex-wrap items-start gap-2 rounded-lg px-2 py-1 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600 ${
                  topShown ? "bg-brand-50 dark:bg-brand-950/40" : ""
                }`}
              >
                <span className="min-w-[8rem] flex-1 break-words text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {title
                    ? `${t("TOP {{number}}", { number: top.number })} · ${title}`
                    : t("TOP {{number}}", { number: top.number })}
                </span>
                {topShown && beamerBadge}
              </button>
              {items.length > 0 && <ol className="grid gap-2 pl-2">{items.map(renderItem)}</ol>}
              <div className="grid gap-2 pl-2">
                <TopNote
                  key={noteText({ section })}
                  text={noteText({ section })}
                  editable={running}
                  busy={busy}
                  onSave={saveNote({ section })}
                  addExtra={addButton(section)}
                />
              </div>
            </li>
          );
        })}
        {loose.map(renderItem)}
      </ol>
      <div className="grid border-t border-slate-200 pt-2 dark:border-slate-800">{addButton(null)}</div>
      {resetting && (
        <ResetDialog
          onConfirm={(comment) => reset(resetting, comment)}
          onCancel={() => setResetting(null)}
        />
      )}
      {runoff && shown?.ballot?.status === "closed" && shown.ballot.election?.proposal && (
        <RunoffDialog
          item={shown}
          ballot={shown.ballot}
          onConfirm={(candidates) => startRunoff(shown.ballot!.id, candidates)}
          onCancel={() => setRunoff(false)}
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
