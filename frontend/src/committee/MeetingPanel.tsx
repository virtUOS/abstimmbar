// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee meetings (Gremien-Raum): the meeting's date and chair-votes
 *  switch, its lifecycle (start/end), the personal links of the members and
 *  the substitutions. Shown on the set page above the agenda (the questions);
 *  an ended meeting is read-only. */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Copy, Download, KeyRound, Play, SquareStop, Trash2, UserRoundCheck } from "lucide-react";
import { localizedText, stripHtml } from "@basicbar/ui";
import {
  api,
  requestError,
  type CommitteeGroup,
  type CommitteeMember,
  type InviteState,
  type MeetingInvite,
  type MeetingSummary,
  type Question,
  type QuestionSet,
} from "../api";
import { Button, ConfirmDialog, Field, Select, ToggleSwitch } from "../components/ui";
import { STATE_BADGE, STATE_LABEL } from "./MeetingList";

const INVITE_STATE_LABEL: Record<InviteState, string> = {
  waiting: "waiting",
  active: "active",
  ended: "ended",
  replaced: "substituted",
  inactive: "no seat",
  removed: "removed",
};

const INVITE_STATE_BADGE: Record<InviteState, string> = {
  waiting: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  active: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  ended: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
  replaced: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  inactive: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  removed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

/** ISO timestamp → `datetime-local` value in the browser's time zone. */
function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}`
  );
}

function ErrorText({ text }: { text: string }) {
  if (!text) return null;
  return <p role="alert" className="text-sm text-danger">{text}</p>;
}

export default function MeetingPanel({
  set,
  questions,
  onSetChange,
}: {
  set: QuestionSet;
  /** The meeting's agenda items (for "from/after item"). */
  questions: Question[];
  onSetChange: (set: QuestionSet) => void;
}) {
  const { t } = useTranslation();
  const [meeting, setMeeting] = useState<MeetingSummary | null>(null);
  const [groups, setGroups] = useState<CommitteeGroup[]>([]);
  const [members, setMembers] = useState<CommitteeMember[]>([]);
  const [loadError, setLoadError] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [stateError, setStateError] = useState("");
  const [linksError, setLinksError] = useState("");
  const [subError, setSubError] = useState("");
  const [dateDraft, setDateDraft] = useState(toLocalInput(set.scheduled_at));
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDateDraft(toLocalInput(set.scheduled_at));
  }, [set.scheduled_at]);

  useEffect(() => {
    Promise.all([
      api.getMeeting(set.id),
      api.listCommitteeGroups(set.room),
      api.listCommitteeMembers(set.room),
    ])
      .then(([summary, groupList, memberList]) => {
        setMeeting(summary);
        setGroups(groupList);
        setMembers(memberList);
      })
      .catch((err) => setLoadError(t(requestError(err))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set.id, set.room]);

  if (loadError) return <div className="mb-8"><ErrorText text={loadError} /></div>;
  if (!meeting) return null;

  const state = meeting.meeting_state;
  const ended = state === "ended";
  const groupById = new Map(groups.map((group) => [group.id, group]));
  const memberById = new Map(members.map((member) => [member.id, member]));
  const agenda = [...questions].sort((a, b) => a.position - b.position);
  const itemNumber = (questionId: number | null) =>
    questionId === null ? null : agenda.findIndex((q) => q.id === questionId) + 1 || null;
  const itemLabel = (question: Question, index: number) => {
    const text = stripHtml(localizedText(question.text)).trim();
    const label = t("Item {{number}}", { number: index + 1 });
    return text ? `${label}: ${text.length > 60 ? `${text.slice(0, 60)}…` : text}` : label;
  };

  /** Run a meeting action; refresh the summary (and the set's state). */
  async function run(
    action: () => Promise<unknown>,
    setError: (text: string) => void,
  ): Promise<boolean> {
    setError("");
    setBusy(true);
    try {
      const result = await action();
      const summary =
        result && typeof result === "object" && "invites" in result
          ? (result as MeetingSummary)
          : await api.getMeeting(set.id);
      setMeeting(summary);
      if (summary.meeting_state !== set.meeting_state)
        onSetChange({ ...set, meeting_state: summary.meeting_state });
      return true;
    } catch (err) {
      setError(t(requestError(err)));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings(patch: Partial<QuestionSet>) {
    setSettingsError("");
    try {
      const updated = await api.updateQuestionSet(set.id, patch);
      onSetChange(updated);
      setMeeting((current) =>
        current && {
          ...current,
          scheduled_at: updated.scheduled_at,
          chair_votes: updated.chair_votes,
        },
      );
    } catch (err) {
      setSettingsError(t(requestError(err)));
    }
  }

  function saveDate() {
    if (!dateDraft) {
      setSettingsError(t("Please enter the date of the meeting."));
      return;
    }
    if (dateDraft === toLocalInput(set.scheduled_at)) return;
    void saveSettings({ scheduled_at: new Date(dateDraft).toISOString() });
  }

  return (
    <section
      aria-labelledby="meeting-panel-heading"
      className="mb-8 grid min-w-0 gap-6 rounded-2xl border border-slate-200 p-4 dark:border-slate-800"
    >
      <h2
        id="meeting-panel-heading"
        className="font-semibold text-slate-900 dark:text-slate-100"
      >
        {t("Meeting")}
      </h2>

      {confirmEnd && (
        <ConfirmDialog
          message={t("End the meeting? All personal links become invalid afterwards.")}
          confirmLabel={t("End meeting")}
          onConfirm={() => {
            setConfirmEnd(false);
            void run(() => api.endMeeting(set.id), setStateError);
          }}
          onCancel={() => setConfirmEnd(false)}
        />
      )}

      {/* Date and chair-votes switch: only before the meeting starts. */}
      <div className="grid gap-3">
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
            {t("Date and time")}
          </span>
          <input
            type="datetime-local"
            required
            value={dateDraft}
            disabled={state !== "draft"}
            onChange={(event) => setDateDraft(event.target.value)}
            onBlur={saveDate}
            className="w-full max-w-xs rounded-lg border border-field bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2 focus:ring-offset-white disabled:opacity-60 dark:bg-slate-900 dark:text-slate-100 dark:[color-scheme:dark] dark:focus:ring-offset-slate-950"
          />
        </label>
        <div>
          <ToggleSwitch
            checked={meeting.chair_votes}
            disabled={state !== "draft"}
            onChange={(checked) => void saveSettings({ chair_votes: checked })}
            label={t("Chair votes too")}
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {t("The chair then needs their own member entry and votes on their own device.")}
          </p>
        </div>
        <ErrorText text={settingsError} />
      </div>

      {/* Status and lifecycle. */}
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-slate-700 dark:text-slate-300">
            {t("Status")}:{" "}
            <span
              data-testid="meeting-state"
              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATE_BADGE[state]}`}
            >
              {t(STATE_LABEL[state])}
            </span>
          </span>
          {state === "draft" && (
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => void run(() => api.startMeeting(set.id), setStateError)}
              className="inline-flex items-center gap-1.5"
            >
              <Play aria-hidden className="h-4 w-4" />
              {t("Start meeting")}
            </Button>
          )}
          {state === "started" && (
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => setConfirmEnd(true)}
              className="inline-flex items-center gap-1.5 border border-red-200 dark:border-red-900"
            >
              <SquareStop aria-hidden className="h-4 w-4" />
              {t("End meeting")}
            </Button>
          )}
        </div>
        <ErrorText text={stateError} />
      </div>

      <InviteSection
        meeting={meeting}
        groupById={groupById}
        agenda={agenda}
        itemLabel={itemLabel}
        busy={busy}
        error={linksError}
        onGenerate={() => void run(() => api.ensureMeetingInvites(set.id), setLinksError)}
        onRemove={(invite, after) =>
          run(() => api.removeInvite(set.id, invite.id, after), setLinksError)
        }
        onReadmit={(invite) =>
          void run(() => api.readmitInvite(set.id, invite.id), setLinksError)
        }
        csvUrl={api.meetingInvitesCsvUrl(set.id)}
      />

      <SubstitutionSection
        meeting={meeting}
        setId={set.id}
        members={members}
        groupById={groupById}
        memberById={memberById}
        agenda={agenda}
        itemLabel={itemLabel}
        itemNumber={itemNumber}
        readOnly={ended}
        busy={busy}
        error={subError}
        onAdd={(data) => run(() => api.addSubstitution(set.id, data), setSubError)}
        onDelete={(subId) =>
          void run(() => api.deleteSubstitution(set.id, subId), setSubError)
        }
        setError={setSubError}
      />
    </section>
  );
}

function roleLabel(member: MeetingInvite["member"], group: CommitteeGroup | undefined) {
  if (group?.is_observer) return "Observer";
  return member.role === "deputy" ? "Deputy" : "Voting member";
}

function InviteSection({
  meeting,
  groupById,
  agenda,
  itemLabel,
  busy,
  error,
  onGenerate,
  onRemove,
  onReadmit,
  csvUrl,
}: {
  meeting: MeetingSummary;
  groupById: Map<number, CommitteeGroup>;
  agenda: Question[];
  itemLabel: (question: Question, index: number) => string;
  busy: boolean;
  error: string;
  onGenerate: () => void;
  onRemove: (invite: MeetingInvite, after: number | null) => Promise<boolean>;
  onReadmit: (invite: MeetingInvite) => void;
  csvUrl: string;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState<number | null>(null);
  const [removing, setRemoving] = useState<number | null>(null);
  const [removeAfter, setRemoveAfter] = useState("");
  const ended = meeting.meeting_state === "ended";
  const invites = meeting.invites;
  const hasValid = invites.some((invite) => invite.state === "waiting" || invite.state === "active");

  async function copy(invite: MeetingInvite) {
    await navigator.clipboard.writeText(invite.url);
    setCopied(invite.id);
    window.setTimeout(() => setCopied((current) => (current === invite.id ? null : current)), 2000);
  }

  return (
    <div className="grid min-w-0 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
      <h3 className="flex items-center gap-1.5 font-medium text-slate-900 dark:text-slate-100">
        <KeyRound aria-hidden className="h-4 w-4" />
        {t("Personal links")}
      </h3>
      {!ended && (
        <div className="flex flex-wrap items-center gap-2">
          <Button disabled={busy} onClick={onGenerate}>
            {t("Generate links")}
          </Button>
          {hasValid && (
            <a
              href={csvUrl}
              download
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900/60"
            >
              <Download aria-hidden className="h-4 w-4" />
              {t("All links as CSV")}
            </a>
          )}
        </div>
      )}
      {invites.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t("No personal links yet.")}
        </p>
      ) : (
        // The table may scroll in itself on narrow screens; the page must not.
        <div className="min-w-0 overflow-x-auto">
          <table className="w-full min-w-[36rem] text-left text-sm">
            <thead className="text-xs text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-3 font-medium">{t("Name")}</th>
                <th className="py-1 pr-3 font-medium">{t("Group")}</th>
                <th className="py-1 pr-3 font-medium">{t("Role")}</th>
                <th className="py-1 pr-3 font-medium">{t("Status")}</th>
                <th className="py-1 font-medium">
                  <span className="sr-only">{t("Actions")}</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {invites.map((invite) => {
                const group = groupById.get(invite.member.group);
                const valid = invite.state === "waiting" || invite.state === "active";
                return (
                  <tr key={invite.id} data-testid="invite-row" className="align-top">
                    <td className="py-2 pr-3">
                      <span className="block font-medium text-slate-800 dark:text-slate-200">
                        {invite.member.name}
                      </span>
                      {invite.member.email && (
                        <span className="block text-xs text-slate-500 dark:text-slate-400">
                          {invite.member.email}
                        </span>
                      )}
                    </td>
                    <td className="py-2 pr-3 text-slate-600 dark:text-slate-300">
                      {group ? localizedText(group.name) : ""}
                    </td>
                    <td className="py-2 pr-3 text-slate-600 dark:text-slate-300">
                      {t(roleLabel(invite.member, group))}
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ${INVITE_STATE_BADGE[invite.state]}`}
                      >
                        {t(INVITE_STATE_LABEL[invite.state])}
                      </span>
                    </td>
                    <td className="py-2">
                      {removing === invite.id ? (
                        <div className="grid gap-2">
                          {meeting.meeting_state === "started" && agenda.length > 0 && (
                            <Field label={t("Remove from the meeting")}>
                              <Select
                                value={removeAfter}
                                onChange={(event) => setRemoveAfter(event.target.value)}
                              >
                                <option value="">{t("Right away")}</option>
                                {agenda.map((question, index) => (
                                  <option key={question.id} value={question.id}>
                                    {t("after {{item}}", { item: itemLabel(question, index) })}
                                  </option>
                                ))}
                              </Select>
                            </Field>
                          )}
                          <span className="flex gap-1">
                            <Button
                              variant="danger"
                              disabled={busy}
                              onClick={() =>
                                void onRemove(
                                  invite,
                                  removeAfter ? Number(removeAfter) : null,
                                ).then((ok) => ok && setRemoving(null))
                              }
                            >
                              {t("Remove")}
                            </Button>
                            <Button variant="ghost" onClick={() => setRemoving(null)}>
                              {t("Cancel")}
                            </Button>
                          </span>
                        </div>
                      ) : (
                        <span className="flex items-center justify-end gap-1">
                          {valid && (
                            <Button
                              variant="ghost"
                              aria-label={t("Copy link of {{name}}", { name: invite.member.name })}
                              title={t("Copy link")}
                              onClick={() => void copy(invite)}
                              className="inline-flex items-center gap-1"
                            >
                              {copied === invite.id ? (
                                <Check aria-hidden className="h-4 w-4" />
                              ) : (
                                <Copy aria-hidden className="h-4 w-4" />
                              )}
                              <span className="text-xs">
                                {copied === invite.id ? t("Copied") : t("Copy link")}
                              </span>
                            </Button>
                          )}
                          {!ended && valid && (
                            <Button
                              variant="ghost"
                              aria-label={t("Remove {{name}}", { name: invite.member.name })}
                              title={t("Remove")}
                              onClick={() => {
                                setRemoveAfter("");
                                setRemoving(invite.id);
                              }}
                            >
                              <Trash2 aria-hidden className="h-4 w-4" />
                            </Button>
                          )}
                          {!ended && invite.state === "removed" && (
                            <Button
                              variant="ghost"
                              disabled={busy}
                              onClick={() => onReadmit(invite)}
                              className="inline-flex items-center gap-1"
                            >
                              <UserRoundCheck aria-hidden className="h-4 w-4" />
                              <span className="text-xs">{t("Readmit")}</span>
                            </Button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <ErrorText text={error} />
    </div>
  );
}

function SubstitutionSection({
  meeting,
  setId,
  members,
  groupById,
  memberById,
  agenda,
  itemLabel,
  itemNumber,
  readOnly,
  busy,
  error,
  onAdd,
  onDelete,
  setError,
}: {
  meeting: MeetingSummary;
  setId: number;
  members: CommitteeMember[];
  groupById: Map<number, CommitteeGroup>;
  memberById: Map<number, CommitteeMember>;
  agenda: Question[];
  itemLabel: (question: Question, index: number) => string;
  itemNumber: (questionId: number | null) => number | null;
  readOnly: boolean;
  busy: boolean;
  error: string;
  onAdd: (data: { absent: number; deputy: number; from_question: number | null }) => Promise<boolean>;
  onDelete: (subId: number) => void;
  setError: (text: string) => void;
}) {
  const { t } = useTranslation();
  const [absentId, setAbsentId] = useState("");
  const [deputyId, setDeputyId] = useState("");
  const [fromItem, setFromItem] = useState("");
  // Latest picked absent member: a slow suggestion for an earlier pick must
  // not overwrite the deputy of the current one.
  const pickedRef = useRef("");
  const subs = meeting.substitutions;
  const usedAbsent = new Set(subs.map((sub) => sub.absent));
  const usedDeputy = new Set(subs.map((sub) => sub.deputy));

  const absentOptions = members.filter(
    (member) =>
      member.role === "voting" &&
      !groupById.get(member.group)?.is_observer &&
      !usedAbsent.has(member.id),
  );
  const absent = absentId ? memberById.get(Number(absentId)) : undefined;
  const deputyOptions = absent
    ? members.filter(
        (member) =>
          member.role === "deputy" &&
          member.group === absent.group &&
          !usedDeputy.has(member.id),
      )
    : [];

  async function pickAbsent(value: string) {
    pickedRef.current = value;
    setAbsentId(value);
    setDeputyId("");
    setError("");
    if (!value) return;
    try {
      const { deputy } = await api.suggestDeputy(setId, Number(value));
      if (pickedRef.current === value) setDeputyId(deputy ? String(deputy.id) : "");
    } catch (err) {
      if (pickedRef.current === value) setError(t(requestError(err)));
    }
  }

  async function add() {
    if (!absentId || !deputyId) return;
    const ok = await onAdd({
      absent: Number(absentId),
      deputy: Number(deputyId),
      from_question: fromItem ? Number(fromItem) : null,
    });
    if (ok) {
      pickedRef.current = "";
      setAbsentId("");
      setDeputyId("");
      setFromItem("");
    }
  }

  return (
    <div className="grid min-w-0 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
      <h3 className="font-medium text-slate-900 dark:text-slate-100">{t("Substitution")}</h3>
      {subs.length === 0 ? (
        <p className="text-sm text-slate-500 dark:text-slate-400">{t("No substitutions.")}</p>
      ) : (
        <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {subs.map((sub) => {
            const number = itemNumber(sub.from_question);
            const deputyName = memberById.get(sub.deputy)?.name ?? "?";
            const absentName = memberById.get(sub.absent)?.name ?? "?";
            return (
              <li
                key={sub.id}
                data-testid="substitution"
                className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
              >
                <span className="min-w-0 flex-1 break-words text-slate-700 dark:text-slate-300">
                  {t("{{deputy}} substitutes for {{absent}}", {
                    deputy: deputyName,
                    absent: absentName,
                  })}
                  {number !== null && t(" (from item {{number}})", { number })}
                </span>
                {!readOnly && (
                  <Button
                    variant="ghost"
                    disabled={busy}
                    aria-label={t("Delete substitution for {{name}}", { name: absentName })}
                    title={t("Delete")}
                    onClick={() => onDelete(sub.id)}
                  >
                    <Trash2 aria-hidden className="h-4 w-4" />
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {!readOnly && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("Absent member")}>
            <Select value={absentId} onChange={(event) => void pickAbsent(event.target.value)}>
              <option value="">{t("Choose …")}</option>
              {absentOptions.map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </Select>
          </Field>
          {absent && deputyOptions.length > 0 && (
            <>
              <Field label={t("Deputy")}>
                <Select value={deputyId} onChange={(event) => setDeputyId(event.target.value)}>
                  <option value="">{t("Choose …")}</option>
                  {deputyOptions.map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label={t("From agenda item")}>
                <Select value={fromItem} onChange={(event) => setFromItem(event.target.value)}>
                  <option value="">{t("Whole meeting")}</option>
                  {agenda.map((question, index) => (
                    <option key={question.id} value={question.id}>
                      {itemLabel(question, index)}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          )}
        </div>
      )}
      {!readOnly && absent && deputyOptions.length === 0 && (
        <p className="text-sm text-amber-700 dark:text-amber-400">
          {t("No deputy is set up for this group. Add the person to the room as a deputy.")}
        </p>
      )}
      {!readOnly && absent && deputyOptions.length > 0 && (
        <div>
          <Button
            variant="primary"
            disabled={busy || !deputyId}
            onClick={() => void add()}
          >
            {t("Add substitution")}
          </Button>
        </div>
      )}
      <ErrorText text={error} />
    </div>
  );
}
