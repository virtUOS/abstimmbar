// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee meetings (Gremien-Raum): status, date and lifecycle
 *  (start/end) on top, then the chair-votes switch, the personal links of
 *  the members and the substitutions (both collapsible). Shown on the set
 *  page above the agenda (the questions); an ended meeting is read-only. */
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import {
  CalendarClock,
  Check,
  ChevronDown,
  Copy,
  Download,
  KeyRound,
  Pencil,
  Play,
  Presentation,
  SquareStop,
  Trash2,
  UserRoundCheck,
} from "lucide-react";
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
import { MeetingDateInput, STATE_BADGE, STATE_LABEL } from "./MeetingList";

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

/** Starting this much earlier or later than scheduled asks first. */
const EARLY_MS = 15 * 60_000;
const LATE_MS = 60 * 60_000;

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

function offSchedule(iso: string | null): boolean {
  if (!iso) return false;
  const delta = Date.now() - new Date(iso).getTime();
  return delta < -EARLY_MS || delta > LATE_MS;
}

function ErrorText({ text }: { text: string }) {
  if (!text) return null;
  return <p role="alert" className="text-sm text-danger">{text}</p>;
}

/** Heading of a collapsible block; the summary shows while it is closed. */
function Collapsible({
  id,
  icon,
  title,
  summary,
  open,
  onToggle,
}: {
  id: string;
  icon?: React.ReactNode;
  title: string;
  summary: string;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <h3 className="font-medium text-slate-900 dark:text-slate-100">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-x-1.5 text-left"
      >
        {icon}
        {title}
        {!open && summary && (
          <span className="ml-1 text-sm font-normal text-slate-500 dark:text-slate-400">
            {summary}
          </span>
        )}
        <ChevronDown
          aria-hidden
          className={`ml-auto h-4 w-4 shrink-0 text-slate-400 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
      </button>
    </h3>
  );
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
  const { t, i18n } = useTranslation();
  const [meeting, setMeeting] = useState<MeetingSummary | null>(null);
  const [groups, setGroups] = useState<CommitteeGroup[]>([]);
  const [members, setMembers] = useState<CommitteeMember[]>([]);
  const [loadError, setLoadError] = useState("");
  const [settingsError, setSettingsError] = useState("");
  const [stateError, setStateError] = useState("");
  const [linksError, setLinksError] = useState("");
  const [subError, setSubError] = useState("");
  const [editingDate, setEditingDate] = useState(false);
  const [dateDraft, setDateDraft] = useState(toLocalInput(set.scheduled_at));
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [confirmStart, setConfirmStart] = useState(false);
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
  const longDate = (iso: string) =>
    new Intl.DateTimeFormat(i18n.language, { dateStyle: "full", timeStyle: "short" }).format(new Date(iso));
  const shortTime = (iso: string) =>
    new Intl.DateTimeFormat(i18n.language, { timeStyle: "short" }).format(new Date(iso));
  // The chair can only vote with a member entry of their own.
  const chairToggleBlocked = !meeting.chair_is_member && !meeting.chair_votes;

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

  /** Start the meeting and open the console in a new tab. The tab is
   *  opened right away (inside the click) so no popup blocker stops it. */
  async function begin() {
    const tab = window.open("", "_blank");
    const ok = await run(() => api.startMeeting(set.id), setStateError);
    if (!tab) return;
    if (ok) tab.location.href = `/sets/${set.id}/meeting`;
    else tab.close();
  }

  async function saveSettings(patch: Partial<QuestionSet>): Promise<boolean> {
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
      return true;
    } catch (err) {
      setSettingsError(t(requestError(err)));
      return false;
    }
  }

  async function saveDate() {
    if (!dateDraft) {
      setSettingsError(t("Please enter the date of the meeting."));
      return;
    }
    if (dateDraft === toLocalInput(set.scheduled_at)) {
      setEditingDate(false);
      return;
    }
    if (await saveSettings({ scheduled_at: new Date(dateDraft).toISOString() }))
      setEditingDate(false);
  }

  return (
    <section
      aria-labelledby="meeting-panel-heading"
      className="mb-8 grid min-w-0 gap-4 rounded-2xl border border-slate-200 p-4 dark:border-slate-800"
    >
      <h2 id="meeting-panel-heading" className="sr-only">
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
      {confirmStart && meeting.scheduled_at && (
        <ConfirmDialog
          message={t("The meeting is scheduled for {{date}}. Start it now anyway?", {
            date: longDate(meeting.scheduled_at),
          })}
          confirmLabel={t("Start now")}
          confirmVariant="primary"
          onConfirm={() => {
            setConfirmStart(false);
            void begin();
          }}
          onCancel={() => setConfirmStart(false)}
        />
      )}

      {/* Status, date and lifecycle first: what the chair needs at a glance. */}
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <span
              data-testid="meeting-state"
              className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATE_BADGE[state]}`}
            >
              {t(STATE_LABEL[state])}
            </span>
            <span className="inline-flex min-w-0 items-center gap-1.5 text-base font-semibold sm:text-lg text-slate-900 dark:text-slate-100">
              <CalendarClock aria-hidden className="h-5 w-5 shrink-0 text-slate-500 dark:text-slate-400" />
              <span data-testid="meeting-date" className="break-words">
                {meeting.scheduled_at ? longDate(meeting.scheduled_at) : t("No date yet")}
              </span>
            </span>
            {state === "draft" && !editingDate && (
              <Button
                variant="ghost"
                aria-label={t("Change date and time")}
                title={t("Change date and time")}
                onClick={() => {
                  setDateDraft(toLocalInput(set.scheduled_at));
                  setEditingDate(true);
                }}
              >
                <Pencil aria-hidden className="h-4 w-4" />
              </Button>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {state === "draft" && (
              <Button
                variant="primary"
                disabled={busy}
                onClick={() =>
                  offSchedule(meeting.scheduled_at) ? setConfirmStart(true) : void begin()
                }
                className="inline-flex items-center gap-1.5"
              >
                <Play aria-hidden className="h-4 w-4" />
                {t("Start meeting")}
              </Button>
            )}
            {state === "started" && (
              <Link
                to={`/sets/${set.id}/meeting`}
                className="inline-flex items-center gap-1.5 rounded-lg bg-brand-400 px-3 py-1.5 text-sm font-semibold text-slate-900 transition-colors hover:bg-brand-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-600"
              >
                <Presentation aria-hidden className="h-4 w-4" />
                {t("Lead meeting")}
              </Link>
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
        </div>
        {editingDate && (
          <div className="flex flex-wrap items-end gap-2">
            <MeetingDateInput value={dateDraft} onChange={setDateDraft} />
            <Button variant="primary" onClick={() => void saveDate()}>
              {t("Save")}
            </Button>
            <Button
              variant="ghost"
              onClick={() => {
                setEditingDate(false);
                setSettingsError("");
              }}
            >
              {t("Cancel")}
            </Button>
          </div>
        )}
        {state === "started" && meeting.started_at && (
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {t("Started at {{time}}.", { time: shortTime(meeting.started_at) })}
          </p>
        )}
        {ended && (
          <p
            data-testid="meeting-ended-note"
            className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-900 dark:text-slate-300"
          >
            {meeting.ended_at
              ? t("The meeting ended on {{date}}.", { date: longDate(meeting.ended_at) })
              : t("The meeting has ended.")}{" "}
            {t("The personal links are no longer valid; agenda, links and substitutions can no longer be changed.")}
          </p>
        )}
        <ErrorText text={stateError} />
      </div>

      {/* Chair-votes switch: only before the meeting starts. */}
      {state === "draft" ? (
        <div>
          <ToggleSwitch
            checked={meeting.chair_votes}
            disabled={chairToggleBlocked}
            onChange={(checked) => void saveSettings({ chair_votes: checked })}
            label={t("Chair votes too")}
          />
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {meeting.chair_is_member
              ? t("The chair then needs their own member entry and votes on their own device.")
              : t("Not available: you are not a voting member of any group in this room. Add yourself under “Groups and members” with your email address.")}
          </p>
        </div>
      ) : (
        meeting.chair_votes && (
          <p className="text-sm text-slate-600 dark:text-slate-400">{t("The chair votes too.")}</p>
        )
      )}
      <ErrorText text={settingsError} />

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
  const [copyError, setCopyError] = useState("");
  const [removing, setRemoving] = useState<number | null>(null);
  const [removeAfter, setRemoveAfter] = useState("");
  const ended = meeting.meeting_state === "ended";
  const invites = meeting.invites;
  const hasValid = invites.some((invite) => invite.state === "waiting" || invite.state === "active");
  // Closed once links exist: the table is long and the agenda below matters more.
  const [open, setOpen] = useState(invites.length === 0);
  const connected = invites.filter((invite) => invite.state === "active").length;

  async function copy(invite: MeetingInvite) {
    try {
      await navigator.clipboard.writeText(invite.url);
    } catch {
      setCopyError(t("The link could not be copied. Please copy it from the CSV export."));
      return;
    }
    setCopyError("");
    setCopied(invite.id);
    window.setTimeout(() => setCopied((current) => (current === invite.id ? null : current)), 2000);
  }

  return (
    <div className="grid min-w-0 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
      <Collapsible
        id="meeting-links-body"
        icon={<KeyRound aria-hidden className="h-4 w-4" />}
        title={t("Personal links")}
        summary={
          invites.length === 0
            ? ""
            : meeting.meeting_state === "started"
              ? t("Links: {{links}} · connected: {{connected}}", { links: invites.length, connected })
              : t("Links: {{links}}", { links: invites.length })
        }
        open={open}
        onToggle={() => setOpen((value) => !value)}
      />
      {open && (
      <div id="meeting-links-body" className="grid min-w-0 gap-3">
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
      </div>
      )}
      <ErrorText text={error || copyError} />
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
  const [adding, setAdding] = useState(false);
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
  const groupHasDeputies = absent
    ? members.some((member) => member.role === "deputy" && member.group === absent.group)
    : false;
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
    if (ok) cancel();
  }

  function cancel() {
    pickedRef.current = "";
    setAbsentId("");
    setDeputyId("");
    setFromItem("");
    setAdding(false);
    setError("");
  }

  // Nothing to show on an ended meeting without substitutions.
  if (readOnly && subs.length === 0) return null;

  return (
    <div className="grid min-w-0 gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-medium text-slate-900 dark:text-slate-100">
          {t("Substitution")}
          {subs.length === 0 && !adding && (
            <span className="ml-1.5 text-sm font-normal text-slate-500 dark:text-slate-400">
              {t("No substitutions.")}
            </span>
          )}
        </h3>
        {!readOnly && !adding && (
          <Button onClick={() => setAdding(true)} className="inline-flex items-center gap-1.5">
            <span className="text-base leading-none">+</span>
            {t("Substitution")}
          </Button>
        )}
      </div>
      {subs.length > 0 && (
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
      {!readOnly && adding && (
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
      {!readOnly && adding && absent && deputyOptions.length === 0 && (
        <p className="text-sm text-amber-700 dark:text-amber-400">
          {groupHasDeputies
            ? t("All deputies of this group are already assigned.")
            : t("No deputy is set up for this group. Add the person to the room as a deputy.")}
        </p>
      )}
      {!readOnly && adding && (
        <div className="flex gap-2">
          {absent && deputyOptions.length > 0 && (
            <Button
              variant="primary"
              disabled={busy || !deputyId}
              onClick={() => void add()}
            >
              {t("Add substitution")}
            </Button>
          )}
          <Button variant="ghost" onClick={cancel}>
            {t("Cancel")}
          </Button>
        </div>
      )}
      <ErrorText text={error} />
    </div>
  );
}
