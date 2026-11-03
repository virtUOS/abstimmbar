// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee rooms (Gremien-Raum): the room's groups and members. Without
 *  groups (only the automatic observer group) the managers pick a template
 *  or create their own group; afterwards every group is a section with its
 *  member list. Members are added by searching people from the manager's
 *  own rooms or by pasting an e-mail list. */
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ClipboardList, Pencil, Search, Trash2, UsersRound } from "lucide-react";
import { localizedText, type LocalizedText } from "@basicbar/ui";
import {
  api,
  requestError,
  type BulkMemberResult,
  type BulkSkipReason,
  type CommitteeGroup,
  type CommitteeMember,
  type CommitteeRole,
  type CommitteeTemplate,
  type KnownPerson,
  type Room,
} from "../api";
import { Button, ConfirmDialog, Field, SegmentedControl, Select, TextInput } from "../components/ui";
import TranslatableField from "../components/TranslatableField";

const SKIP_REASON: Record<BulkSkipReason, string> = {
  invalid_email: "invalid e-mail address",
  duplicate: "duplicate in the list",
  exists: "already a member",
};

function sortGroups(groups: CommitteeGroup[]): CommitteeGroup[] {
  // The observer group always comes last.
  return [...groups].sort(
    (a, b) =>
      Number(a.is_observer) - Number(b.is_observer) ||
      a.position - b.position ||
      a.id - b.id,
  );
}

function roleLabel(member: CommitteeMember, group: CommitteeGroup | undefined) {
  if (group?.is_observer) return "Observer";
  return member.role === "deputy" ? "Deputy" : "Voting member";
}

export default function CommitteePanel({ room }: { room: Room }) {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<CommitteeGroup[] | null>(null);
  const [members, setMembers] = useState<CommitteeMember[]>([]);
  const [templates, setTemplates] = useState<CommitteeTemplate[]>([]);
  const [error, setError] = useState("");
  const [newGroup, setNewGroup] = useState<LocalizedText | null>(null);
  const [confirmGroup, setConfirmGroup] = useState<CommitteeGroup | null>(null);
  const [confirmMember, setConfirmMember] = useState<CommitteeMember | null>(null);
  // Rarely touched once set up: starts collapsed when the room has members.
  const [open, setOpen] = useState(true);

  const reload = () =>
    Promise.all([
      api.listCommitteeGroups(room.id),
      api.listCommitteeMembers(room.id),
    ]).then(([groupList, memberList]) => {
      setGroups(sortGroups(groupList));
      setMembers(memberList);
      return memberList;
    });

  useEffect(() => {
    void reload()
      .then((memberList) => setOpen(memberList.length === 0))
      .catch((err) => {
      setGroups((current) => current ?? []);
      setError(t(requestError(err)));
    });
    void api.listCommitteeTemplates().then(setTemplates).catch(() => setTemplates([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [room.id]);

  if (!groups) return null;

  const regular = groups.filter((group) => !group.is_observer);
  const groupById = new Map(groups.map((group) => [group.id, group]));

  async function run(action: () => Promise<unknown>) {
    setError("");
    try {
      await action();
      await reload();
      return true;
    } catch (err) {
      setError(t(requestError(err)));
      return false;
    }
  }

  async function createGroup() {
    if (!newGroup) return;
    const position = Math.max(0, ...regular.map((group) => group.position)) + 1;
    if (await run(() => api.createCommitteeGroup({ room: room.id, name: newGroup, position })))
      setNewGroup(null);
  }

  const newGroupForm = newGroup !== null && (
    <div className="grid gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <TranslatableField
        label={t("Group name")}
        value={newGroup}
        onChange={setNewGroup}
        placeholder={t("e.g. “Students”")}
      />
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => void createGroup()}>
          {t("Save")}
        </Button>
        <Button variant="ghost" onClick={() => setNewGroup(null)}>
          {t("Cancel")}
        </Button>
      </div>
    </div>
  );

  return (
    <section
      aria-labelledby="committee-groups-heading"
      className="mb-8 grid min-w-0 gap-4 rounded-2xl border border-slate-200 p-4 dark:border-slate-800"
    >
      <h2 id="committee-groups-heading" className="font-semibold text-slate-900 dark:text-slate-100">
        <button
          type="button"
          aria-expanded={open}
          aria-controls="committee-groups-body"
          onClick={() => setOpen((value) => !value)}
          className="flex w-full flex-wrap items-center gap-x-1.5 text-left"
        >
          <UsersRound aria-hidden className="h-4 w-4" />
          {t("Groups and members")}
          {!open && (
            // Phones: the summary takes its own line under the title.
            <span className="ml-1 text-sm font-normal text-slate-500 max-sm:order-last max-sm:ml-[1.375rem] max-sm:w-full dark:text-slate-400">
              {t("Groups: {{groups}} · Members: {{members}}", {
                groups: regular.length,
                members: members.length,
              })}
            </span>
          )}
          <ChevronDown
            aria-hidden
            className={`ml-auto h-4 w-4 shrink-0 text-slate-400 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
          />
        </button>
      </h2>
      {open && (
        <div id="committee-groups-body" className="grid min-w-0 gap-4">
          {/* Results are broken down per group, so this applies to every group,
              not just the currently small ones. */}
          <p className="-mt-2 text-xs text-slate-500 dark:text-slate-400">
            {t("Results are shown per group. With very small groups, this breakdown may allow conclusions about individual votes.")}
          </p>
          {/* Managers are the room's co-owners, not a group: a group would show
              up in the per-group results. */}
          <p className="-mt-2 text-xs text-slate-500 dark:text-slate-400">
            {t("The chair and their deputies manage the room via “Collaborative editing” in the ⋮ menu — they need no group. If the chair votes too, add them as a member of their status group.")}
          </p>

          {confirmGroup && (
            <ConfirmDialog
              message={t("Delete group “{{name}}”?", { name: localizedText(confirmGroup.name) })}
              onConfirm={() => {
                const group = confirmGroup;
                setConfirmGroup(null);
                void run(() => api.deleteCommitteeGroup(group.id));
              }}
              onCancel={() => setConfirmGroup(null)}
            />
          )}
          {confirmMember && (
            <ConfirmDialog
              message={t("Remove {{name}} from the committee?", { name: confirmMember.name })}
              confirmLabel={t("Remove")}
              onConfirm={() => {
                const member = confirmMember;
                setConfirmMember(null);
                void run(() => api.deleteCommitteeMember(member.id));
              }}
              onCancel={() => setConfirmMember(null)}
            />
          )}

          {regular.length === 0 && (
            <div className="grid gap-3">
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {t("Choose a template for the committee's groups — you can rename and add groups afterwards.")}
              </p>
              <ul className="grid gap-3 sm:grid-cols-3">
                {templates.map((template) => (
                  <li
                    key={template.id}
                    className="flex min-w-0 flex-col justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/50 p-3 dark:border-slate-800 dark:bg-slate-900/40"
                  >
                    <div className="min-w-0">
                      <h3 className="font-medium text-slate-900 dark:text-slate-100">
                        {localizedText(template.name)}
                      </h3>
                      <ul className="mt-1 list-disc pl-5 text-sm text-slate-500 dark:text-slate-400">
                        {template.groups.map((name, index) => (
                          <li key={index} className="break-words">{localizedText(name)}</li>
                        ))}
                      </ul>
                    </div>
                    <Button
                      aria-label={t("Apply template {{name}}", { name: localizedText(template.name) })}
                      onClick={() => void run(() => api.applyCommitteeTemplate(room.id, template.id))}
                      className="self-start"
                    >
                      {t("Apply")}
                    </Button>
                  </li>
                ))}
              </ul>
              {newGroup === null ? (
                <div>
                  <Button variant="ghost" onClick={() => setNewGroup("")}>
                    + {t("Create own group")}
                  </Button>
                </div>
              ) : (
                newGroupForm
              )}
            </div>
          )}

          {groups.map((group) => (
            <GroupSection
              key={group.id}
              group={group}
              members={members.filter((member) => member.group === group.id)}
              groups={groups}
              onRename={(name) => run(() => api.updateCommitteeGroup(group.id, { name }))}
              onDelete={() => setConfirmGroup(group)}
              onSaveMember={(id, data) => run(() => api.updateCommitteeMember(id, data))}
              onRemoveMember={setConfirmMember}
              groupById={groupById}
            />
          ))}

          {regular.length > 0 &&
            (newGroup === null ? (
              <div>
                <Button variant="ghost" onClick={() => setNewGroup("")}>
                  + {t("Add group")}
                </Button>
              </div>
            ) : (
              newGroupForm
            ))}

          {error && <p role="alert" className="text-sm text-danger">{error}</p>}

          {regular.length > 0 && (
            <BulkAddForm roomId={room.id} groups={groups} onAdded={async () => void (await reload())} />
          )}
        </div>
      )}
    </section>
  );
}

function GroupSection({
  group,
  members,
  groups,
  groupById,
  onRename,
  onDelete,
  onSaveMember,
  onRemoveMember,
}: {
  group: CommitteeGroup;
  members: CommitteeMember[];
  groups: CommitteeGroup[];
  groupById: Map<number, CommitteeGroup>;
  onRename: (name: LocalizedText) => Promise<boolean>;
  onDelete: () => void;
  onSaveMember: (id: number, data: Partial<CommitteeMember>) => Promise<boolean>;
  onRemoveMember: (member: CommitteeMember) => void;
}) {
  const { t } = useTranslation();
  const [nameDraft, setNameDraft] = useState<LocalizedText | null>(null);
  const [editing, setEditing] = useState<number | null>(null);
  const name = localizedText(group.name);

  return (
    <div className="min-w-0 border-t border-slate-100 pt-4 dark:border-slate-800">
      {nameDraft !== null ? (
        <div className="grid gap-3">
          <TranslatableField
            label={t("Group name")}
            value={nameDraft}
            onChange={setNameDraft}
          />
          <div className="flex gap-2">
            <Button
              variant="primary"
              onClick={() => void onRename(nameDraft).then((ok) => ok && setNameDraft(null))}
            >
              {t("Save")}
            </Button>
            <Button variant="ghost" onClick={() => setNameDraft(null)}>
              {t("Cancel")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="min-w-0 break-words font-medium text-slate-900 dark:text-slate-100">
            {name}
          </h3>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {t("{{count}} member", { count: group.member_count })}
          </span>
          <span className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              aria-label={t("Rename group {{name}}", { name })}
              title={t("Rename")}
              onClick={() => setNameDraft(group.name)}
            >
              <Pencil aria-hidden className="h-4 w-4" />
            </Button>
            {!group.is_observer && (
              <Button
                variant="ghost"
                aria-label={t("Delete group {{name}}", { name })}
                title={t("Delete")}
                onClick={onDelete}
              >
                <Trash2 aria-hidden className="h-4 w-4" />
              </Button>
            )}
          </span>
        </div>
      )}

      {group.is_observer && (
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          {t("Observers see the beamer view but do not vote.")}
        </p>
      )}

      {members.length > 0 && (
        <ul className="mt-2 divide-y divide-slate-100 text-sm dark:divide-slate-800">
          {members.map((member) =>
            editing === member.id ? (
              <li key={member.id} className="py-2">
                <MemberEditForm
                  member={member}
                  groups={groups}
                  onSave={(data) =>
                    onSaveMember(member.id, data).then((ok) => {
                      if (ok) setEditing(null);
                      return ok;
                    })
                  }
                  onCancel={() => setEditing(null)}
                />
              </li>
            ) : (
              <li key={member.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <span className="w-full min-w-0 sm:w-auto sm:flex-1">
                  <span className="block break-words font-medium text-slate-800 dark:text-slate-200">
                    {member.name}
                  </span>
                  {member.email && (
                    <span className="block break-all text-slate-500 dark:text-slate-400">
                      {member.email}
                    </span>
                  )}
                </span>
                <span className="flex-1 text-xs text-slate-500 sm:flex-none dark:text-slate-400">
                  {t(roleLabel(member, groupById.get(member.group)))}
                  {member.role === "deputy" && member.deputy_rank !== null && (
                    <> · {t("Rank {{rank}}", { rank: member.deputy_rank })}</>
                  )}
                  {" · "}
                  <span title={t("Language")}>{member.language.toUpperCase()}</span>
                </span>
                <span className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    aria-label={t("Edit {{name}}", { name: member.name })}
                    title={t("Edit")}
                    onClick={() => setEditing(member.id)}
                  >
                    <Pencil aria-hidden className="h-4 w-4" />
                  </Button>
                  <Button
                    variant="ghost"
                    aria-label={t("Remove {{name}}", { name: member.name })}
                    title={t("Remove")}
                    onClick={() => onRemoveMember(member)}
                  >
                    <Trash2 aria-hidden className="h-4 w-4" />
                  </Button>
                </span>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}

function MemberEditForm({
  member,
  groups,
  onSave,
  onCancel,
}: {
  member: CommitteeMember;
  groups: CommitteeGroup[];
  onSave: (data: Partial<CommitteeMember>) => Promise<boolean>;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState(member);
  const observer = groups.find((group) => group.id === draft.group)?.is_observer ?? false;

  function submit(event: FormEvent) {
    event.preventDefault();
    const role: CommitteeRole = observer ? "voting" : draft.role;
    void onSave({
      name: draft.name,
      email: draft.email,
      group: draft.group,
      role,
      deputy_rank: role === "deputy" ? draft.deputy_rank : null,
      language: draft.language,
    });
  }

  return (
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
      <Field label={t("Name")}>
        <TextInput
          value={draft.name}
          required
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
        />
      </Field>
      <Field label={t("E-mail")}>
        <TextInput
          type="email"
          value={draft.email}
          onChange={(event) => setDraft({ ...draft, email: event.target.value })}
        />
      </Field>
      <Field label={t("Group")}>
        <Select
          value={draft.group}
          onChange={(event) => setDraft({ ...draft, group: Number(event.target.value) })}
        >
          {groups.map((group) => (
            <option key={group.id} value={group.id}>
              {localizedText(group.name)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={t("Role")}>
        <Select
          value={observer ? "voting" : draft.role}
          disabled={observer}
          onChange={(event) =>
            setDraft({ ...draft, role: event.target.value as CommitteeRole })
          }
        >
          {observer ? (
            <option value="voting">{t("Observer")}</option>
          ) : (
            <>
              <option value="voting">{t("Voting member")}</option>
              <option value="deputy">{t("Deputy")}</option>
            </>
          )}
        </Select>
      </Field>
      {!observer && draft.role === "deputy" && (
        <Field label={t("Rank")}>
          <TextInput
            type="number"
            min={1}
            value={draft.deputy_rank ?? ""}
            onChange={(event) =>
              setDraft({
                ...draft,
                deputy_rank: event.target.value === "" ? null : Number(event.target.value),
              })
            }
          />
        </Field>
      )}
      <Field label={t("Language")}>
        <Select
          value={draft.language}
          onChange={(event) =>
            setDraft({ ...draft, language: event.target.value as "de" | "en" })
          }
        >
          <option value="de">{t("German")}</option>
          <option value="en">{t("English")}</option>
        </Select>
      </Field>
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" variant="primary">
          {t("Save")}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel}>
          {t("Cancel")}
        </Button>
      </div>
    </form>
  );
}

function BulkAddForm({
  roomId,
  groups,
  onAdded,
}: {
  roomId: number;
  groups: CommitteeGroup[];
  onAdded: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [groupId, setGroupId] = useState<number>(
    groups.find((group) => !group.is_observer)?.id ?? groups[0].id,
  );
  const [role, setRole] = useState<CommitteeRole>("voting");
  const [mode, setMode] = useState<"search" | "list">("search");
  const [result, setResult] = useState<BulkMemberResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // The chosen group may have been deleted meanwhile.
  const group = groups.find((g) => g.id === groupId) ?? groups[0];
  const observer = group.is_observer;

  /** Both the search pick and the pasted list go through the bulk import,
   *  so validation and the created/skipped report are the same. */
  async function add(lines: string): Promise<boolean> {
    setError("");
    setResult(null);
    setBusy(true);
    try {
      const data = await api.bulkAddCommitteeMembers({
        room: roomId,
        group: group.id,
        role: observer ? "voting" : role,
        text: lines,
      });
      setResult(data);
      await onAdded();
      return true;
    } catch (err) {
      setError(t(requestError(err)));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (await add(text)) setText("");
  }

  function pick(person: KnownPerson) {
    // Quoted, so a "Last, First" name is not split at its comma.
    void add(`"${person.name.replace(/"/g, "")}" <${person.email}>`);
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="grid gap-3 border-t border-slate-100 pt-4 dark:border-slate-800"
    >
      <h3 className="font-medium text-slate-900 dark:text-slate-100">{t("Add members")}</h3>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("Group")}>
          <Select value={group.id} onChange={(event) => setGroupId(Number(event.target.value))}>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>
                {localizedText(g.name)}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t("Role")}>
          <Select
            value={observer ? "voting" : role}
            disabled={observer}
            onChange={(event) => setRole(event.target.value as CommitteeRole)}
          >
            {observer ? (
              <option value="voting">{t("Observer")}</option>
            ) : (
              <>
                <option value="voting">{t("Voting member")}</option>
                <option value="deputy">{t("Deputy")}</option>
              </>
            )}
          </Select>
        </Field>
      </div>
      {/* Two alternative ways in: pick known people, or paste a list. The
          chosen way's fields sit in one box below the switch. */}
      <div className="grid gap-2">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
          {t("Add people via")}
        </span>
        <SegmentedControl
          className="w-full sm:w-max"
          ariaLabel={t("Add people via")}
          value={mode}
          onChange={setMode}
          options={[
            {
              value: "search",
              label: (
                <span className="inline-flex items-center gap-1.5">
                  <Search aria-hidden className="h-4 w-4 shrink-0" />
                  {t("Search")}
                </span>
              ),
              title: t("Search known people"),
            },
            {
              value: "list",
              label: (
                <span className="inline-flex items-center gap-1.5">
                  <ClipboardList aria-hidden className="h-4 w-4 shrink-0" />
                  {t("E-mail list")}
                </span>
              ),
              title: t("Paste an e-mail list"),
            },
          ]}
        />
        <div className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3 dark:border-slate-800 dark:bg-slate-900/40">
          {mode === "search" ? (
            <KnownPeopleSearch roomId={roomId} disabled={busy} onPick={pick} />
          ) : (
            <>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                  {t("E-mail list")}
                </span>
                <textarea
                  value={text}
                  required
                  rows={4}
                  onChange={(event) => setText(event.target.value)}
                  placeholder={"Anna Muster <anna@example.org>\nbert@example.org"}
                  className="w-full rounded-lg border border-field bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2 focus:ring-offset-white dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-offset-slate-950"
                />
                <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
                  {t("One person per line, or separated by commas or semicolons: “Name <e-mail>” or just the e-mail address.")}
                </span>
              </label>
              <div>
                <Button type="submit" variant="primary" disabled={busy}>
                  {t("Add members")}
                </Button>
              </div>
            </>
          )}
        </div>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {result && (
        <div role="status" className="rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-900/60">
          <p className="font-medium text-slate-800 dark:text-slate-200">
            {t("{{created}} created, {{skipped}} skipped", {
              created: result.created.length,
              skipped: result.skipped.length,
            })}
          </p>
          {result.skipped.length > 0 && (
            <ul className="mt-1 grid gap-0.5 text-slate-600 dark:text-slate-400">
              {result.skipped.map((skip, index) => (
                <li key={index} className="break-all">
                  <span className="font-mono">{skip.line}</span>
                  {" — "}
                  {t(SKIP_REASON[skip.reason])}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </form>
  );
}

/** Autocomplete over people from my own rooms (committee members and
 *  co-owners; the backend never searches other accounts). Picking a person
 *  adds them right away with the chosen group and role. */
function KnownPeopleSearch({
  roomId,
  disabled,
  onPick,
}: {
  roomId: number;
  disabled: boolean;
  onPick: (person: KnownPerson) => void;
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<KnownPerson[]>([]);
  const trimmed = query.trim();

  function choose(person: KnownPerson) {
    onPick(person);
    setQuery("");
  }

  useEffect(() => {
    if (trimmed.length < 2) {
      setPeople([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .searchKnownPeople(roomId, trimmed)
        .then((found) => !cancelled && setPeople(found))
        .catch(() => !cancelled && setPeople([]));
    }, 250);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [roomId, trimmed]);

  return (
    <div>
      <Field label={t("Name or e-mail address")}>
        <TextInput
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            // Enter picks the first hit instead of submitting the list form.
            if (event.key !== "Enter") return;
            event.preventDefault();
            if (people[0] && !disabled) choose(people[0]);
          }}
          autoComplete="off"
        />
      </Field>
      <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
        {t("Finds people from your own committees and the co-owners of your rooms.")}
      </span>
      {trimmed.length >= 2 && (
        <ul aria-label={t("Search results")} className="mt-2 grid gap-1">
          {people.length === 0 && (
            <li className="text-sm text-slate-500 dark:text-slate-400">{t("Nobody found")}</li>
          )}
          {people.map((person) => (
            <li key={person.email}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => choose(person)}
                className="flex w-full items-baseline gap-2 rounded-lg px-3 py-1.5 text-left text-sm hover:bg-slate-50 disabled:opacity-50 dark:hover:bg-slate-800"
              >
                <span className="font-medium text-slate-900 dark:text-slate-100">+ {person.name}</span>
                <span className="min-w-0 truncate text-slate-500 dark:text-slate-400">{person.email}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
