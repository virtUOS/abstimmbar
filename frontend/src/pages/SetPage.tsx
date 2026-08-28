// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Archive, BarChart3, Check, ChevronDown, CircleHelp, Copy, CopyPlus, Download, Files, FolderInput, GraduationCap, Languages, ListTree, Play, Settings, Share2, Sparkles, Timer, Trash2 } from "lucide-react";
import {
  api,
  results,
  type Question,
  type QuestionKind,
  type QuestionSet,
  type RevealAnswers,
  type Room,
  type Section as SectionType,
} from "../api";
import { useEasyMode } from "../App";
import AiGeneratePanel from "../components/AiGeneratePanel";
import HomeCrumb from "../components/HomeCrumb";
import RichText from "../components/RichText";
import SortableOutline from "../components/SortableOutline";
import TranslatableField from "../components/TranslatableField";
import { allowedKindsFor, CREATABLE_SET_TYPES, SET_TYPES, type SetType } from "../setTypes";
import { localizedText, type LocalizedText } from "@basicbar/ui";
import {
  Button,
  ConfirmInline,
  EmptyState,
  Field,
  InfoHint,
  MenuItem,
  MoreMenu,
  Select,
  TextInput,
} from "../components/ui";
import { LICENSE_OPTIONS, licenseNeedsHolder } from "../licenses";

// Values are English source strings, translated with t() at each render site
// (this Record lives at module scope, outside any component).
export const KIND_LABEL: Record<QuestionKind, string> = {
  single_choice: "Single Choice",
  multiple_choice: "Multiple Choice",
  word_cloud: "Word cloud",
  likert: "Likert scale",
  open_text: "Free text",
  priorities: "Priorities",
  ordering: "Ordering",
};

// Kinds whose answers are options (mirror of backend Question.CHOICE_KINDS) —
// the only kinds that can get an after-question (#54).
const CHOICE_KINDS: QuestionKind[] = ["single_choice", "multiple_choice", "likert"];

// Labels are English source strings, translated with t() at each render site.
export const REVEAL_OPTIONS: { value: RevealAnswers; label: string }[] = [
  { value: "immediately", label: "immediately, with the results" },
  { value: "after_close", label: "only when triggered" },
  { value: "never", label: "never" },
];

export const REVEAL_LABEL: Record<RevealAnswers, string> = {
  immediately: "immediately, with the results",
  after_close: "only when triggered",
  never: "never",
};

function stripHtml(html: string) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent?.trim() ?? "";
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** Editable settings while creating or editing a set. */
export interface SetSettings {
  type: SetType;
  title: LocalizedText;
  description: LocalizedText;
  reveal_answers: RevealAnswers;
  open_on_show: boolean;
  show_results_to_participants: boolean;
}

/** The settings form, shared by the create panel (RoomPage) and the edit
 * mode here. Controlled: the parent owns the draft and the Save/Cancel. */
export function SetSettingsForm({
  draft,
  onChange,
  easyMode = false,
  isNew = false,
}: {
  draft: SetSettings;
  onChange: (patch: Partial<SetSettings>) => void;
  /** Easy mode (#52): only title + description; hide reveal/answer-flow
   * options. Existing values stay stored. */
  easyMode?: boolean;
  /** #75: the set type is picked once, at creation, and immutable after —
   * shown as selectable cards only here; the edit form shows it read-only. */
  isNew?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="grid max-w-2xl gap-8">
      {isNew ? (
        <div>
          <p className="mb-1 text-sm font-medium text-slate-700 dark:text-slate-300">
            {t("Set type")}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {CREATABLE_SET_TYPES.map((st) => (
              <button
                key={st}
                type="button"
                onClick={() => onChange({ type: st })}
                className={`rounded-xl border p-3 text-left text-sm ${
                  draft.type === st
                    ? "border-brand-500 bg-brand-50 dark:border-brand-500 dark:bg-brand-950/40"
                    : "border-slate-200 hover:border-brand-400 dark:border-slate-700"
                }`}
              >
                <span className="font-semibold text-slate-900 dark:text-slate-100">
                  {t(SET_TYPES[st].label)}
                </span>
                <span className="mt-0.5 block text-xs text-slate-500 dark:text-slate-400">
                  {t(SET_TYPES[st].description)}
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          {t("Set type")}:{" "}
          <span className="font-medium">{t(SET_TYPES[draft.type].label)}</span>
        </p>
      )}
      <TranslatableField
        label={t("Title")}
        value={draft.title}
        onChange={(title) => onChange({ title })}
        placeholder={t("Question set title")}
      />
      <TranslatableField
        variant="rich"
        label={t("Description")}
        value={draft.description}
        onChange={(description) => onChange({ description })}
      />
      {!easyMode && (
        <fieldset>
          <legend className="mb-1 text-sm font-medium text-slate-700 dark:text-slate-300">
            {t("Answers & results")}
          </legend>
          <div className="grid gap-2">
            <Field label={t("Reveal correct answers")}>
              <Select
                value={draft.reveal_answers}
                onChange={(event) =>
                  onChange({ reveal_answers: event.target.value as RevealAnswers })
                }
              >
                {REVEAL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.label)}
                  </option>
                ))}
              </Select>
              <p className="mt-1 text-xs text-slate-400">
                {t(
                  "Default for all questions with correct answers; individual questions can deviate from this.",
                )}
              </p>
            </Field>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={draft.open_on_show}
                onChange={(event) => onChange({ open_on_show: event.target.checked })}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Questions can be answered immediately on open (no separate start)")}
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={draft.show_results_to_participants}
                onChange={(event) =>
                  onChange({ show_results_to_participants: event.target.checked })
                }
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Participants also see the results on their own device")}
            </label>
          </div>
        </fieldset>
      )}
    </div>
  );
}

/** One entry in the inline outline (SortableOutline needs a string id). */
type OutlineRow =
  | { kind: "section"; id: string; section: SectionType }
  | { kind: "question"; id: string; question: Question };

/** Merge sections and questions into the single ordered outline. */
function buildRows(questions: Question[], sections: SectionType[]): OutlineRow[] {
  const merged = [
    ...sections.map((section) => ({
      pos: section.position,
      row: { kind: "section" as const, id: `s-${section.id}`, section },
    })),
    ...questions.map((question) => ({
      pos: question.position,
      row: { kind: "question" as const, id: `q-${question.id}`, question },
    })),
  ];
  merged.sort((a, b) => a.pos - b.pos);
  return merged.map((entry) => entry.row);
}

// Label/description are English source strings, translated with t() at the
// NewQuestionMenu render site (this array lives at module scope).
const QUESTION_TYPES: {
  kind: QuestionKind;
  template?: "binary";
  label: string;
  description: string;
}[] = [
  {
    kind: "single_choice",
    label: "Single Choice",
    description: "One answer selectable; a correct answer can be marked.",
  },
  {
    kind: "multiple_choice",
    label: "Multiple Choice",
    description: "Multiple answers selectable at the same time.",
  },
  {
    kind: "single_choice",
    template: "binary",
    label: "Yes/No",
    description: "Two options — pick a Yes/No or True/False template, or type your own.",
  },
  {
    kind: "likert",
    label: "Likert scale",
    description: "Fixed rating scale (e.g. agreement), optionally with an abstain option.",
  },
  {
    kind: "word_cloud",
    label: "Word cloud",
    description: "Short free-form terms, live as a growing word cloud.",
  },
  {
    kind: "open_text",
    label: "Free text",
    description: "Free-form text answer (max. 500 characters), shown as a list.",
  },
  {
    kind: "priorities",
    label: "Priorities",
    description: "Distribute up to 100 points across the options; evaluated as the average per option.",
  },
  {
    kind: "ordering",
    label: "Ordering",
    description: "Participants sort items into the correct order (drag & drop).",
  },
];

/** "+ Neue Frage" dropdown: question type with a one-line explanation.
 * `allowedKinds` gates the list to what the set's type permits (#75). */
function NewQuestionMenu({
  onPick,
  allowedKinds,
}: {
  onPick: (kind: QuestionKind, template?: "binary") => void;
  allowedKinds: QuestionKind[];
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <Button
        variant="primary"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-2"
      >
        <span className="text-base leading-none">+</span>
        {t("New question")}
        <ChevronDown
          aria-hidden
          className={`h-4 w-4 transition-transform duration-150 ${open ? "rotate-180" : ""}`}
        />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-30 mt-2 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white py-1 shadow-lg shadow-slate-900/5 dark:border-slate-700 dark:bg-slate-900"
        >
          {QUESTION_TYPES.filter((type) => allowedKinds.includes(type.kind)).map((type) => (
            <button
              key={type.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                onPick(type.kind, type.template);
              }}
              className="block w-full px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <span className="block text-sm font-semibold text-slate-900 dark:text-slate-100">
                {t(type.label)}
              </span>
              <span className="block text-xs text-slate-500 dark:text-slate-400">
                {t(type.description)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Section-name editor inside the outline: bilingual (title tabs), committed
 * onBlur like the previous plain-string input — local state so keystrokes
 * don't round-trip to the server, synced back in if the section changes
 * from under it (e.g. after a reorder reload). */
function SectionTitleField({
  section,
  onRename,
}: {
  section: SectionType;
  onRename: (id: number, title: LocalizedText) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState<LocalizedText>(section.title);
  useEffect(() => setTitle(section.title), [section.id, section.title]);
  return (
    <TranslatableField
      value={title}
      onChange={setTitle}
      ariaLabel={t("Section name")}
      className="!w-72 font-semibold"
      onBlur={() => {
        if (JSON.stringify(title) !== JSON.stringify(section.title)) {
          onRename(section.id, title);
        }
      }}
    />
  );
}

/** Question-set editor: summarized settings (editable behind a pencil),
 * sortable question list, and a ⋮ menu for duplicate/export/share. */
export default function SetPage() {
  const { t } = useTranslation();
  const { setId } = useParams();
  const id = Number(setId);
  const navigate = useNavigate();
  const [set, setSet] = useState<QuestionSet | null>(null);
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [copyOpen, setCopyOpen] = useState(false);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [copyTarget, setCopyTarget] = useState<number | null>(null);
  const [copyTitle, setCopyTitle] = useState("");
  const [linkCopied, setLinkCopied] = useState(false);
  const [metaError, setMetaError] = useState("");
  const [sections, setSections] = useState<SectionType[]>([]);
  const [editingSections, setEditingSections] = useState(false);
  const [editingMeta, setEditingMeta] = useState(false);
  const [draft, setDraft] = useState<SetSettings | null>(null);
  const [sharePanelOpen, setSharePanelOpen] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [archivedNotice, setArchivedNotice] = useState(false);
  const [whoamiName, setWhoamiName] = useState("");
  const [aiEnabled, setAiEnabled] = useState(false);
  const [generateOpen, setGenerateOpen] = useState(false);
  // Move/copy a single question to another set (#87) — shared target-set
  // picker, ported from QuestionPage's move modal.
  const [xfer, setXfer] = useState<{ id: number; mode: "move" | "copy" } | null>(null);
  const [xferTargets, setXferTargets] = useState<QuestionSet[] | null>(null);
  const [xferRooms, setXferRooms] = useState<{ id: number; title: string }[]>([]);
  const [xferRoom, setXferRoom] = useState<number | null>(null);
  const [xferTarget, setXferTarget] = useState<number | null>(null);
  const [xferError, setXferError] = useState("");
  // Pull picker (#87): copy several questions from a chosen source set into
  // this one. `pullTargets` doubles as the dialog's open/closed gate.
  const [pullTargets, setPullTargets] = useState<QuestionSet[] | null>(null);
  const [pullRooms, setPullRooms] = useState<{ id: number; title: string }[]>([]);
  const [pullRoom, setPullRoom] = useState<number | null>(null);
  const [pullSourceSet, setPullSourceSet] = useState<number | null>(null);
  const [pullQuestions, setPullQuestions] = useState<Question[] | null>(null);
  const [pullSelected, setPullSelected] = useState<Set<number>>(new Set());
  const [pullError, setPullError] = useState("");
  const [pullBusy, setPullBusy] = useState(false);
  // Small bottom toast, shared by "copy link" and the new copy actions.
  const [toastMessage, setToastMessage] = useState("");
  const easyMode = useEasyMode();
  const aiVisible = aiEnabled && !easyMode;
  // Recording mode (#53): opt-in before presenting; carried to the beamer via
  // the present URL. Pro feature (hidden in easy mode).
  const [recordMode, setRecordMode] = useState(false);

  useEffect(() => {
    void Promise.all([
      api.getQuestionSet(id),
      api.listQuestions(id),
      api.listSections(id),
      api.whoami(),
    ]).then(([setData, page, sectionPage, who]) => {
      setSet(setData);
      setQuestions(page.results);
      setSections(sectionPage.results);
      setWhoamiName(
        [who.first_name, who.last_name].filter(Boolean).join(" ") ||
          who.username ||
          "",
      );
      setAiEnabled(!!who.ai_enabled);
    });
  }, [id]);

  const rows = buildRows(questions ?? [], sections);

  async function persistOutline(newRows: OutlineRow[]) {
    const newSections: SectionType[] = [];
    const newQuestions: Question[] = [];
    let current: number | null = null;
    newRows.forEach((row, index) => {
      if (row.kind === "section") {
        newSections.push({ ...row.section, position: index });
        current = row.section.id;
      } else {
        newQuestions.push({ ...row.question, position: index, section: current });
      }
    });
    setSections(newSections);
    setQuestions(newQuestions);
    await api.reorderOutline(
      id,
      newRows.map((row) =>
        row.kind === "section"
          ? { type: "section" as const, id: row.section.id }
          : { type: "question" as const, id: row.question.id },
      ),
    );
  }

  async function insertSectionAt(index: number) {
    const created = await api.createSection(id);
    const next = [...rows];
    next.splice(index, 0, { kind: "section", id: `s-${created.id}`, section: created });
    await persistOutline(next);
  }

  async function renameSection(sectionId: number, title: LocalizedText) {
    const updated = await api.updateSection(sectionId, title);
    setSections((current) =>
      current.map((s) => (s.id === sectionId ? { ...s, title: updated.title } : s)),
    );
  }

  async function deleteSection(sectionId: number) {
    await api.deleteSection(sectionId);
    await persistOutline(
      rows.filter((row) => !(row.kind === "section" && row.section.id === sectionId)),
    );
  }

  async function reloadQuestions() {
    const page = await api.listQuestions(id);
    setQuestions(page.results);
  }

  /** Archive current results & prepare a fresh run (#27/#56) — same action as
   * the room's set table, surfaced here in the set's ⋮ menu. Reloads the set
   * so the status line / archive-availability reflect the fresh run. */
  async function handleArchiveResults() {
    setConfirmArchive(false);
    await results.archive(id);
    const updated = await api.getQuestionSet(id);
    setSet(updated);
    // Confirm success — archiving only changes the *next* presentation, so
    // without feedback it looks like nothing happened (#70).
    setArchivedNotice(true);
  }

  /** Persist an arbitrary patch (share panel: license/holder, sharing). */
  async function saveMeta(patch: Partial<QuestionSet>) {
    if (!set) return;
    setMetaError("");
    try {
      const updated = await api.updateQuestionSet(set.id, patch);
      setSet(updated);
    } catch (err) {
      try {
        const data = JSON.parse((err as Error).message);
        const value = data.detail ?? Object.values(data)[0];
        setMetaError(Array.isArray(value) ? value[0] : String(value));
      } catch {
        setMetaError(String(err));
      }
    }
  }

  function startMetaEdit() {
    if (!set) return;
    setMetaError("");
    setDraft({
      type: set.type,
      title: set.title,
      description: set.description,
      reveal_answers: set.reveal_answers,
      open_on_show: set.open_on_show,
      show_results_to_participants: set.show_results_to_participants,
    });
    setEditingMeta(true);
  }

  async function saveMetaEdit() {
    if (!set || !draft) return;
    setMetaError("");
    try {
      const updated = await api.updateQuestionSet(set.id, draft);
      setSet(updated);
      setEditingMeta(false);
    } catch (err) {
      try {
        const data = JSON.parse((err as Error).message);
        const value = data.detail ?? Object.values(data)[0];
        setMetaError(Array.isArray(value) ? value[0] : String(value));
      } catch {
        setMetaError(String(err));
      }
    }
  }

  const shareUrl = set?.share_token
    ? `${window.location.origin}/shared/${set.share_token}`
    : "";

  async function toggleShare(enabled: boolean) {
    if (!set) return;
    const { share_token } = await api.shareQuestionSet(set.id, enabled);
    setSet({ ...set, share_token });
    return share_token;
  }

  async function openSharePanel() {
    if (!set) return;
    if (!set.share_token) await toggleShare(true);
    setSharePanelOpen(true);
  }

  function changeLicense(value: string) {
    // Prefill the holder with the signed-in name when a license needs it.
    if (licenseNeedsHolder(value) && !set?.license_holder && whoamiName) {
      void saveMeta({ license: value, license_holder: whoamiName });
    } else {
      void saveMeta({ license: value });
    }
  }

  async function copyShareLink() {
    await navigator.clipboard.writeText(shareUrl);
    setLinkCopied(true);
    window.setTimeout(() => setLinkCopied(false), 1500);
  }

  const toastTimer = useRef<number | undefined>(undefined);
  function showToast(message: string) {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    setToastMessage(message);
    toastTimer.current = window.setTimeout(() => setToastMessage(""), 1500);
  }

  async function copyQuestionLink(questionId: number) {
    const url = `${window.location.origin}/sets/${id}/present?question=${questionId}`;
    await navigator.clipboard.writeText(url);
    showToast(t("Copied"));
  }

  /** Two-stage Room→Question-set picker, shared by the move/copy modal and
   * the pull picker: all of the user's sets minus the current one, grouped
   * by room, defaulting to the current set's room. */
  async function loadTransferTargets(filter?: (entry: QuestionSet) => boolean) {
    const page = await api.listAllQuestionSets();
    const targets = page.results.filter(
      (entry) => entry.id !== id && (filter ? filter(entry) : true),
    );
    const rooms = [
      ...new Map(targets.map((entry) => [entry.room, entry.room_title])),
    ].map(([roomId, title]) => ({ id: roomId, title }));
    const startRoom = rooms.some((room) => room.id === set?.room)
      ? (set?.room ?? null)
      : (rooms[0]?.id ?? null);
    return { targets, rooms, startRoom };
  }

  /** Open the shared move/copy picker for a single question (#87). */
  async function openXfer(questionId: number, mode: "move" | "copy") {
    const { targets, rooms, startRoom } = await loadTransferTargets();
    setXferTargets(targets);
    setXferRooms(rooms);
    setXferRoom(startRoom);
    setXferTarget(targets.find((entry) => entry.room === startRoom)?.id ?? null);
    setXferError("");
    setXfer({ id: questionId, mode });
  }

  function pickXferRoom(roomId: number) {
    setXferRoom(roomId);
    setXferTarget(xferTargets?.find((entry) => entry.room === roomId)?.id ?? null);
  }

  async function confirmXfer() {
    if (!xfer || xferTarget === null) return;
    setXferError("");
    try {
      if (xfer.mode === "move") {
        await api.moveQuestion(xfer.id, xferTarget);
      } else {
        await api.copyQuestions(xferTarget, [xfer.id]);
        showToast(t("Copied"));
      }
      setXfer(null);
      await reloadQuestions();
    } catch (err) {
      try {
        setXferError(JSON.parse((err as Error).message).detail ?? String(err));
      } catch {
        setXferError(String(err));
      }
    }
  }

  /** Open the pull picker: choose a source set, then check off questions to
   * copy into this one (#87). */
  async function openPull() {
    // Only sets that actually have questions can be pulled from.
    const { targets, rooms, startRoom } = await loadTransferTargets(
      (entry) => entry.question_count > 0,
    );
    const startSet = targets.find((entry) => entry.room === startRoom)?.id ?? null;
    setPullTargets(targets);
    setPullRooms(rooms);
    setPullRoom(startRoom);
    setPullSourceSet(startSet);
    setPullQuestions(null);
    setPullSelected(new Set());
    setPullError("");
    if (startSet !== null) await loadPullQuestions(startSet);
  }

  async function loadPullQuestions(sourceSetId: number) {
    const page = await api.listQuestions(sourceSetId);
    setPullQuestions(page.results);
    // Start with nothing selected: pulling in is deliberate cherry-picking,
    // not "copy the whole set" (that's what Duplicate is for). "Select all"
    // is one click away for the take-everything case.
    setPullSelected(new Set());
  }

  function pickPullRoom(roomId: number) {
    setPullRoom(roomId);
    const nextSet = pullTargets?.find((entry) => entry.room === roomId)?.id ?? null;
    setPullSourceSet(nextSet);
    if (nextSet !== null) void loadPullQuestions(nextSet);
    else {
      setPullQuestions(null);
      setPullSelected(new Set());
    }
  }

  function pickPullSourceSet(sourceSetId: number) {
    setPullSourceSet(sourceSetId);
    void loadPullQuestions(sourceSetId);
  }

  function togglePullQuestion(questionId: number) {
    setPullSelected((current) => {
      const next = new Set(current);
      if (next.has(questionId)) next.delete(questionId);
      else next.add(questionId);
      return next;
    });
  }

  function toggleSelectAllPull() {
    if (!pullQuestions) return;
    setPullSelected((current) =>
      current.size === pullQuestions.length
        ? new Set()
        : new Set(pullQuestions.map((q) => q.id)),
    );
  }

  async function confirmPull() {
    if (pullSelected.size === 0) return;
    setPullBusy(true);
    setPullError("");
    try {
      await api.copyQuestions(id, [...pullSelected]);
      setPullTargets(null);
      showToast(t("Copied"));
      await reloadQuestions();
    } catch (err) {
      try {
        setPullError(JSON.parse((err as Error).message).detail ?? String(err));
      } catch {
        setPullError(String(err));
      }
    } finally {
      setPullBusy(false);
    }
  }

  function doExport() {
    const a = document.createElement("a");
    a.href = results.exportUrl(id);
    a.click();
  }

  function addQuestion(kind: QuestionKind, template?: "binary") {
    const query = new URLSearchParams({ kind });
    if (template) query.set("template", template);
    navigate(`/sets/${id}/questions/new?${query.toString()}`);
  }

  async function handleDelete(questionId: number) {
    await api.deleteQuestion(questionId);
    setConfirmDelete(null);
    await reloadQuestions();
  }

  /** Add a locked after-question mirroring this one (#54). */
  async function handleAddAfter(questionId: number) {
    await api.addAfterQuestion(questionId);
    await reloadQuestions();
  }

  async function openCopyDialog() {
    const page = await api.listRooms();
    setRooms(page.results);
    setCopyTarget(set?.room ?? null);
    setCopyTitle("");
    setCopyOpen(true);
  }

  async function handleCopy() {
    if (!set || copyTarget === null) return;
    const clone = await api.duplicateQuestionSet(set.id, {
      room: copyTarget,
      ...(copyTitle.trim() ? { title: copyTitle.trim() } : {}),
    });
    setCopyOpen(false);
    navigate(`/sets/${clone.id}`);
  }

  if (!set || !questions) return null;

  return (
    <div>
      <nav className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        <HomeCrumb />{" "}
        /{" "}
        <Link to={`/rooms/${set.room}`} className="hover:text-brand-700 dark:hover:text-brand-300">
          {set.room_title}
        </Link>{" "}
        / {t("Question set")}: {localizedText(set.title)}
      </nav>

      {/* Settings: summarized read-only, editable behind the pencil. */}
      {editingMeta && draft ? (
        <div className="mb-8">
          <SetSettingsForm
            draft={draft}
            onChange={(patch) => setDraft({ ...draft, ...patch })}
            easyMode={easyMode}
          />
          <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => void saveMetaEdit()}>
              {t("Save")}
            </Button>
            <Button variant="ghost" onClick={() => setEditingMeta(false)}>
              {t("Cancel")}
            </Button>
          </div>
          {metaError && <p className="mt-1 text-sm text-red-600">{metaError}</p>}
        </div>
      ) : (
        <div className="mb-8">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold">{localizedText(set.title)}</h1>
              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                {t(SET_TYPES[set.type].label)}
              </span>
            </div>
            <MoreMenu label={t("Set actions")}>
              <MenuItem onClick={startMetaEdit}><Settings aria-hidden className="h-4 w-4" />{t("Settings")}</MenuItem>
              {/* Pulling in questions is core authoring — available in both
                  modes, unlike the Pro-only actions below (#87). */}
              <MenuItem onClick={() => void openPull()}>
                <CopyPlus aria-hidden className="h-4 w-4" />
                {t("Add questions from another set …")}
              </MenuItem>
              {/* Easy mode (#52): hide duplicate / export / share / archive. */}
              {!easyMode && (
                <>
                  <MenuItem onClick={() => void openCopyDialog()}><Copy aria-hidden className="h-4 w-4" />{t("Duplicate")}</MenuItem>
                  <MenuItem onClick={doExport}><Download aria-hidden className="h-4 w-4" />{t("Export (JSON)")}</MenuItem>
                  <MenuItem onClick={() => void openSharePanel()}>
                    <Share2 aria-hidden className="h-4 w-4" />{t("Copy set (share link)")}
                  </MenuItem>
                  {/* Archive results & start fresh (#56) — same action as the
                      room's set table, only when there is something to archive. */}
                  {set.has_results && (
                    <MenuItem
                      onClick={() => {
                        setArchivedNotice(false);
                        setConfirmArchive(true);
                      }}
                    >
                      <Archive aria-hidden className="h-4 w-4" />{t("Archive results")}
                    </MenuItem>
                  )}
                </>
              )}
            </MoreMenu>
          </div>
          {confirmArchive && (
            <div
              role="alert"
              className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800/60 dark:bg-amber-950/40"
            >
              <div className="flex items-start gap-3">
                <Archive
                  aria-hidden
                  className="mt-0.5 h-5 w-5 shrink-0 text-amber-700 dark:text-amber-400"
                />
                <div className="flex-1">
                  <p className="font-semibold text-amber-900 dark:text-amber-200">
                    {t("Archive results?")}
                  </p>
                  <p className="mt-1 text-sm text-amber-800 dark:text-amber-100/90">
                    {t(
                      "The next presentation of this question set starts fresh — results from earlier sessions are shown neither to participants nor to you. Archived results stay available in the evaluation.",
                    )}
                  </p>
                  <div className="mt-3 flex gap-2">
                    <Button variant="primary" onClick={() => void handleArchiveResults()}>
                      {t("Archive results")}
                    </Button>
                    <Button variant="ghost" onClick={() => setConfirmArchive(false)}>
                      {t("Cancel")}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}
          {archivedNotice && (
            <div
              role="status"
              className="mt-4 rounded-xl border border-brand-300 bg-brand-50 p-4 dark:border-brand-800/60 dark:bg-brand-950/40"
            >
              <div className="flex items-start gap-3">
                <Check
                  aria-hidden
                  className="mt-0.5 h-5 w-5 shrink-0 text-brand-700 dark:text-brand-300"
                />
                <div className="flex-1">
                  <p className="font-semibold text-brand-900 dark:text-brand-200">
                    {t("Results archived.")}
                  </p>
                  <p className="mt-1 text-sm text-slate-700 dark:text-slate-300">
                    {t(
                      "The next presentation starts fresh. The archived session stays available under Results.",
                    )}
                  </p>
                  <div className="mt-3 flex gap-2">
                    <Link
                      to={`/sets/${id}/results`}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-brand-400 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-brand-500"
                    >
                      <BarChart3 aria-hidden className="h-4 w-4" />{t("View results")}
                    </Link>
                    <Button variant="ghost" onClick={() => setArchivedNotice(false)}>
                      {t("Dismiss")}
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}
          {/* Rendered as rich HTML from the WYSIWYG editor (#49). Nothing shown
              when empty — the "No description" placeholder was just noise (#78). */}
          {localizedText(set.description) && (
            <div className="mt-1 max-w-2xl text-sm">
              <RichText html={localizedText(set.description)} />
            </div>
          )}
          {/* Answer-flow summary reflects pro-only settings, so it is hidden in
              the decluttered simple mode (#78). */}
          {!easyMode && (
            <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
              {t("Correct answers:")}{" "}
              <strong className="font-semibold text-slate-700 dark:text-slate-200">
                {t(REVEAL_LABEL[set.reveal_answers])}
              </strong>{" "}
              · {t("Immediately answerable:")}{" "}
              <strong className="font-semibold text-slate-700 dark:text-slate-200">
                {set.open_on_show ? t("yes") : t("no")}
              </strong>{" "}
              · {t("Results for participants:")}{" "}
              <strong className="font-semibold text-slate-700 dark:text-slate-200">
                {set.show_results_to_participants ? t("yes") : t("no")}
              </strong>
            </p>
          )}
          {!easyMode && (
            <p className="mt-1 text-xs text-slate-400">
              {t("Created {{created}} · Updated {{updated}}", {
                created: formatDate(set.created_at),
                updated: formatDate(set.updated_at),
              })}
              {set.share_token && t(" · shareable via link")}
            </p>
          )}
          {metaError && <p className="mt-1 text-sm text-red-600">{metaError}</p>}
        </div>
      )}

      {copyOpen && (
        <div className="mb-8 flex max-w-xl flex-wrap items-end gap-3 rounded-2xl border border-brand-200 dark:border-brand-900 bg-brand-50/50 p-4 dark:bg-brand-950/40">
          <Field label={t("Copy to which room?")}>
            <select
              value={copyTarget ?? undefined}
              onChange={(event) => setCopyTarget(Number(event.target.value))}
              className="w-64 rounded-lg border border-slate-300 dark:border-slate-700 bg-white px-3 py-2 text-sm dark:bg-slate-900 dark:text-slate-100"
            >
              {rooms.map((room) => (
                <option key={room.id} value={room.id}>
                  {localizedText(room.title)}
                  {room.id === set.room ? t(" (this room)") : ""}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("New title (optional)")}>
            <TextInput
              value={copyTitle}
              onChange={(event) => setCopyTitle(event.target.value)}
              placeholder={localizedText(set.title)}
              className="!w-64"
            />
          </Field>
          <Button variant="primary" onClick={() => void handleCopy()}>
            {t("Copy")}
          </Button>
          <Button variant="ghost" onClick={() => setCopyOpen(false)}>
            {t("Cancel")}
          </Button>
        </div>
      )}

      {sharePanelOpen && set.share_token && (
        <div className="mb-8 grid max-w-2xl gap-3 rounded-2xl border border-brand-200 bg-brand-50/50 p-4 dark:border-brand-900 dark:bg-brand-950/40">
          <p className="text-sm text-slate-700 dark:text-slate-200">
            <Trans i18nKey="share_copy_hint">
              Anyone signed in with this link can <strong>copy</strong> the set into their own rooms (not edit it):
            </Trans>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <TextInput
              readOnly
              value={shareUrl}
              onFocus={(event) => event.target.select()}
              aria-label={t("Share link")}
              className="!w-96 font-mono !text-xs"
            />
            <Button onClick={() => void copyShareLink()} className="inline-flex items-center gap-1.5">
              {linkCopied ? (<><Check aria-hidden className="h-4 w-4" />{t("Copied")}</>) : t("Copy link")}
            </Button>
          </div>
          <Field label={t("License for sharing (optional)")}>
            <select
              value={set.license}
              onChange={(event) => changeLicense(event.target.value)}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
            >
              {LICENSE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>
          {licenseNeedsHolder(set.license) && (
            <Field label={t("Rights holder / attribution")}>
              <TextInput
                defaultValue={set.license_holder}
                key={set.license_holder}
                placeholder={whoamiName}
                onBlur={(event) => {
                  const holder = event.target.value.trim();
                  if (holder !== set.license_holder)
                    void saveMeta({ license_holder: holder });
                }}
              />
            </Field>
          )}
          <div className="flex gap-2">
            <Button
              variant="ghost"
              onClick={() => {
                void toggleShare(false);
                setSharePanelOpen(false);
              }}
            >
              {t("End sharing")}
            </Button>
            <Button onClick={() => setSharePanelOpen(false)}>{t("Close")}</Button>
          </div>
          {metaError && <p className="text-sm text-red-600">{metaError}</p>}
        </div>
      )}

      {generateOpen && (
        <div className="mb-4 border-t border-slate-100 pt-6 dark:border-slate-800">
          <AiGeneratePanel
            setId={id}
            onClose={() => setGenerateOpen(false)}
            onImported={reloadQuestions}
          />
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-6 dark:border-slate-800">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">{t("Questions")}</h2>
          {questions.length > 0 && (
            <>
              {/* #75: only the run action matching the set's type is offered. */}
              {SET_TYPES[set.type].runAction === "present" && (
                <Button
                  variant="primary"
                  onClick={() =>
                    navigate(`/sets/${id}/present${recordMode ? "?recording=1" : ""}`)
                  }
                  className="inline-flex items-center gap-1.5"
                >
                  <Play aria-hidden className="h-4 w-4" />{t("Present")}
                </Button>
              )}
              {/* Easy mode (#52): self-paced quiz is a Pro feature — always live. */}
              {!easyMode && SET_TYPES[set.type].runAction === "self_paced" && (
                <Button
                  title={t(
                    "Participants answer all questions at their own pace, with immediate feedback",
                  )}
                  onClick={() => navigate(`/sets/${id}/quiz`)}
                  className="inline-flex items-center gap-1.5"
                >
                  <GraduationCap aria-hidden className="h-4 w-4" />{t("Self-paced quiz")}
                </Button>
              )}
              <Button onClick={() => navigate(`/sets/${id}/results`)} className="inline-flex items-center gap-1.5">
                <BarChart3 aria-hidden className="h-4 w-4" />{t("Results")}
              </Button>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Authoring actions surfaced next to "Neue Frage" (#21, #23).
              Easy mode (#52): sections are a Pro feature. */}
          {!easyMode && (
            <Button
              variant={editingSections ? "primary" : "secondary"}
              aria-pressed={editingSections}
              disabled={questions.length === 0}
              title={
                questions.length === 0
                  ? t("Create a question first — sections group existing questions.")
                  : undefined
              }
              onClick={() => setEditingSections((value) => !value)}
              className="inline-flex items-center gap-1.5"
            >
              <ListTree aria-hidden className="h-4 w-4" />{t("Sections")}
            </Button>
          )}
          {aiVisible && (
            <Button
              onClick={() => {
                setGenerateOpen(true);
                setEditingSections(false);
              }}
              className="inline-flex items-center gap-1.5"
            >
              <Sparkles aria-hidden className="h-4 w-4" />{t("From document")}
            </Button>
          )}
          <NewQuestionMenu
            onPick={(kind, template) => void addQuestion(kind, template)}
            allowedKinds={allowedKindsFor(set.type)}
          />
        </div>
      </div>

      {/* Recording mode (#53): opt-in before presenting (Pro only). */}
      {!easyMode && questions.length > 0 && (
        <label className="mb-4 flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
          <input
            type="checkbox"
            checked={recordMode}
            onChange={(event) => setRecordMode(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
          />
          {t("Recording mode")}
          <InfoHint
            text={t(
              "If the presentation is recorded with an external tool, viewers of the recording can vote afterward: each question shows a unique QR code leading straight to that question.",
            )}
          />
        </label>
      )}

      {editingSections && (
        <p className="mb-3 rounded-xl bg-brand-50 px-4 py-2 text-sm text-slate-700 dark:bg-brand-950 dark:text-slate-300">
          {t(
            "Editing sections: use “+ Section” to insert a heading, click a name to rename it, drag by the handle to move it. Drag questions below the matching heading.",
          )}
        </p>
      )}

      {rows.length === 0 ? (
        <EmptyState icon={CircleHelp} title={t("No questions yet")}>
          {t(
            "Create the first question above — Single Choice starts with three empty answer fields.",
          )}
          <div className="mt-4">
            <Button
              variant="primary"
              onClick={() => void openPull()}
              className="inline-flex items-center gap-1.5"
            >
              <CopyPlus aria-hidden className="h-4 w-4" />
              {t("Add questions from another set …")}
            </Button>
          </div>
        </EmptyState>
      ) : (
        <>
          <SortableOutline
            items={rows.map((row) => ({
              ...row,
              disabled: row.kind === "section" ? !editingSections : false,
            }))}
            onReorder={(items) => void persistOutline(items)}
            renderItem={(row, { handle }) => {
              const index = rows.findIndex((r) => r.id === row.id);
              const insertBar = editingSections && (
                <button
                  type="button"
                  onClick={() => void insertSectionAt(index)}
                  className="mb-2 w-full rounded-lg border border-dashed border-slate-300 py-1 text-xs text-slate-400 hover:border-brand-500 hover:text-brand-700 dark:border-slate-700 dark:hover:text-brand-300"
                >
                  + {t("Section here")}
                </button>
              );
              if (row.kind === "section") {
                return (
                  <>
                    {insertBar}
                    <div className="flex items-center gap-2 pt-2">
                      {handle}
                      <span className="text-brand-700 dark:text-brand-300" aria-hidden>
                        §
                      </span>
                      {editingSections ? (
                        <>
                          <SectionTitleField
                            section={row.section}
                            onRename={(id, title) => void renameSection(id, title)}
                          />
                          <Button
                            variant="ghost"
                            aria-label={t("Delete section {{title}}", {
                              title: localizedText(row.section.title),
                            })}
                            onClick={() => void deleteSection(row.section.id)}
                          >
                            <Trash2 aria-hidden className="h-4 w-4" />
                          </Button>
                        </>
                      ) : (
                        <h3 className="text-base font-bold text-slate-800 dark:text-slate-200">
                          {localizedText(row.section.title)}
                        </h3>
                      )}
                    </div>
                  </>
                );
              }
              const question = row.question;
              // Before/after pair (#54): mark both rows, offer "add
              // after-question" only for an eligible, unpaired choice/likert.
              const hasAfter = question.after_question != null;
              const paired = question.is_after || hasAfter;
              // #91: a persisted stale translation (one language edited after
              // the last sync) — surfaced here so it's visible without opening
              // the question.
              const hasStaleTranslation = Object.values(
                question.translation_stale ?? {},
              ).some((langs) => langs.length > 0);
              // Easy mode (#52): before/after is a Pro feature — hide the
              // action (existing pairs still render/work).
              const canAddAfter =
                !easyMode && !paired && CHOICE_KINDS.includes(question.kind);
              return (
                <>
                  {insertBar}
                  <div
                    className={`flex items-center gap-2 rounded-xl border bg-white px-3 py-2 dark:bg-slate-900 ${
                      paired
                        ? "border-slate-200 border-l-4 border-l-brand-400 dark:border-slate-800"
                        : "border-slate-200 dark:border-slate-800"
                    }`}
                  >
                    {handle}
                    <Link
                      to={`/sets/${id}/questions/${question.id}`}
                      className="min-w-0 flex-1"
                    >
                      <span className="flex items-center gap-2">
                        {paired && (
                          <span className="shrink-0 rounded-full bg-brand-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                            {question.is_after ? t("After") : t("Before")}
                          </span>
                        )}
                        <span className="block truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                          {stripHtml(localizedText(question.text)) || (
                            <span className="italic text-slate-400">{t("No question text")}</span>
                          )}
                        </span>
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {t(KIND_LABEL[question.kind])}
                        {question.kind !== "word_cloud" &&
                          question.kind !== "open_text" &&
                          ` · ${t("{{count}} answers", { count: question.options.length })}`}
                        {question.time_limit ? (<span className="inline-flex items-center gap-1"> · <Timer aria-hidden className="h-3.5 w-3.5" />{question.time_limit} s</span>) : null}
                      </span>
                    </Link>
                    {confirmDelete === question.id ? (
                      <ConfirmInline
                        message={
                          hasAfter
                            ? t("Delete this question and its after-question?")
                            : t("Delete question?")
                        }
                        onConfirm={() => void handleDelete(question.id)}
                        onCancel={() => setConfirmDelete(null)}
                      />
                    ) : (
                      <>
                        {/* Pro only (#91): a persisted stale-translation flag,
                            sitting with the row actions. */}
                        {!easyMode && hasStaleTranslation && (
                          <span
                            title={t("translation may be outdated")}
                            className="inline-flex shrink-0 px-1 text-amber-500"
                          >
                            <Languages
                              aria-label={t("translation may be outdated")}
                              className="h-4 w-4"
                            />
                          </span>
                        )}
                        {!easyMode && (
                          <Button
                            variant="ghost"
                            aria-label={t("Present this question")}
                            onClick={() =>
                              window.open(
                                `/sets/${id}/present?question=${question.id}`,
                                "_blank",
                              )
                            }
                          >
                            <Play aria-hidden className="h-4 w-4" />
                          </Button>
                        )}
                        <MoreMenu label={t("Question actions")}>
                          {!easyMode && (
                            <MenuItem onClick={() => void copyQuestionLink(question.id)}>
                              <Copy aria-hidden className="h-4 w-4" />
                              {t("Copy link")}
                            </MenuItem>
                          )}
                          <MenuItem onClick={() => void openXfer(question.id, "move")}>
                            <FolderInput aria-hidden className="h-4 w-4" />
                            {t("Move to another set …")}
                          </MenuItem>
                          <MenuItem onClick={() => void openXfer(question.id, "copy")}>
                            <Files aria-hidden className="h-4 w-4" />
                            {t("Copy to another set …")}
                          </MenuItem>
                          {canAddAfter && (
                            <MenuItem onClick={() => void handleAddAfter(question.id)}>
                              <CopyPlus aria-hidden className="h-4 w-4" />
                              {t("Add after-question")}
                            </MenuItem>
                          )}
                          <MenuItem danger onClick={() => setConfirmDelete(question.id)}>
                            <Trash2 aria-hidden className="h-4 w-4" />
                            {t("Delete")}
                          </MenuItem>
                        </MoreMenu>
                      </>
                    )}
                  </div>
                </>
              );
            }}
          />
          {editingSections && (
            <button
              type="button"
              onClick={() => void insertSectionAt(rows.length)}
              className="mt-2 w-full rounded-lg border border-dashed border-slate-300 py-1.5 text-sm text-slate-400 hover:border-brand-500 hover:text-brand-700 dark:border-slate-700 dark:hover:text-brand-300"
            >
              + {t("Section at the end")}
            </button>
          )}
        </>
      )}
      {toastMessage && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900">
          {toastMessage}
        </div>
      )}

      {/* Shared move/copy picker for a single question (#87), ported from
          QuestionPage's move modal. */}
      {xfer !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-6"
          role="dialog"
          aria-modal="true"
          onClick={() => setXfer(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {xfer.mode === "move"
                ? t("Move to another question set …")
                : t("Copy to another question set …")}
            </h2>
            {xferTargets && xferTargets.length === 0 ? (
              <p className="text-sm text-slate-400">
                {xfer.mode === "move"
                  ? t("There is no other question set to move this to.")
                  : t("There is no other question set to copy this to.")}
              </p>
            ) : (
              <div className="flex flex-col gap-3">
                <Field label={t("Room")}>
                  <select
                    value={xferRoom ?? undefined}
                    onChange={(event) => pickXferRoom(Number(event.target.value))}
                    className="w-56 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                  >
                    {xferRooms.map((room) => (
                      <option key={room.id} value={room.id}>
                        {room.title}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("Question set")}>
                  <select
                    value={xferTarget ?? undefined}
                    onChange={(event) => setXferTarget(Number(event.target.value))}
                    className="w-72 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                  >
                    {xferTargets
                      ?.filter((entry) => entry.room === xferRoom)
                      .map((entry) => (
                        <option key={entry.id} value={entry.id}>
                          {localizedText(entry.title)}
                        </option>
                      ))}
                  </select>
                </Field>
              </div>
            )}
            {xferError && <p className="mt-3 text-sm text-red-600">{xferError}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setXfer(null)}>
                {t("Cancel")}
              </Button>
              {xferTargets && xferTargets.length > 0 && (
                <Button disabled={xferTarget === null} onClick={() => void confirmXfer()}>
                  {xfer.mode === "move" ? t("Move") : t("Copy")}
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Pull picker (#87): copy several questions from a chosen source set
          into this one. */}
      {pullTargets !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-6"
          role="dialog"
          aria-modal="true"
          onClick={() => setPullTargets(null)}
        >
          <div
            className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-xl dark:border-slate-700 dark:bg-slate-900"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="mb-4 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {t("Add questions from another set …")}
            </h2>
            {pullTargets.length === 0 ? (
              <p className="text-sm text-slate-400">
                {t("There is no other set to copy questions from.")}
              </p>
            ) : (
              <>
                <div className="flex flex-wrap gap-3">
                  <Field label={t("Room")}>
                    <select
                      value={pullRoom ?? undefined}
                      onChange={(event) => pickPullRoom(Number(event.target.value))}
                      className="w-56 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    >
                      {pullRooms.map((room) => (
                        <option key={room.id} value={room.id}>
                          {room.title}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label={t("Question set")}>
                    <select
                      value={pullSourceSet ?? undefined}
                      onChange={(event) => pickPullSourceSet(Number(event.target.value))}
                      className="w-64 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    >
                      {pullTargets
                        .filter((entry) => entry.room === pullRoom)
                        .map((entry) => (
                          <option key={entry.id} value={entry.id}>
                            {localizedText(entry.title)}
                          </option>
                        ))}
                    </select>
                  </Field>
                </div>

                {pullQuestions && (
                  <div className="mt-4 flex min-h-0 flex-1 flex-col">
                    <div className="mb-2 flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        {t("Questions")}
                      </span>
                      {pullQuestions.length > 0 && (
                        <button
                          type="button"
                          onClick={toggleSelectAllPull}
                          className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-300"
                        >
                          {pullSelected.size === pullQuestions.length
                            ? t("Deselect all")
                            : t("Select all")}
                        </button>
                      )}
                    </div>
                    <ul className="flex-1 overflow-y-auto rounded-lg border border-slate-200 dark:border-slate-800">
                      {pullQuestions.length === 0 ? (
                        <li className="px-3 py-4 text-sm text-slate-400">
                          {t("No questions yet")}
                        </li>
                      ) : (
                        pullQuestions.map((question) => (
                          <li
                            key={question.id}
                            className="border-b border-slate-100 last:border-b-0 dark:border-slate-800"
                          >
                            <label className="flex cursor-pointer items-start gap-2 px-3 py-2 hover:bg-slate-50 dark:hover:bg-slate-800/60">
                              <input
                                type="checkbox"
                                checked={pullSelected.has(question.id)}
                                onChange={() => togglePullQuestion(question.id)}
                                className="mt-0.5 h-4 w-4 shrink-0 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
                              />
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-sm text-slate-900 dark:text-slate-100">
                                  {stripHtml(localizedText(question.text)) || (
                                    <span className="italic text-slate-400">
                                      {t("No question text")}
                                    </span>
                                  )}
                                </span>
                                <span className="block text-xs text-slate-500 dark:text-slate-400">
                                  {t(KIND_LABEL[question.kind])}
                                </span>
                              </span>
                            </label>
                          </li>
                        ))
                      )}
                    </ul>
                  </div>
                )}
              </>
            )}
            {pullError && <p className="mt-3 text-sm text-red-600">{pullError}</p>}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setPullTargets(null)}>
                {t("Cancel")}
              </Button>
              {pullTargets.length > 0 && (
                <Button
                  variant="primary"
                  disabled={pullSelected.size === 0 || pullBusy}
                  onClick={() => void confirmPull()}
                >
                  {pullBusy
                    ? t("Saving …")
                    : t("Copy {{count}} questions", { count: pullSelected.size })}
                </Button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
