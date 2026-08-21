// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useRef, useState } from "react";
import { Trans, useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Archive, BarChart3, Check, ChevronDown, CircleHelp, Copy, CopyPlus, Download, GraduationCap, ListTree, Play, Settings, Share2, Sparkles, Timer, Trash2 } from "lucide-react";
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
import RichText from "../components/RichText";
import SortableOutline from "../components/SortableOutline";
import TranslatableField from "../components/TranslatableField";
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
const KIND_LABEL: Record<QuestionKind, string> = {
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
}: {
  draft: SetSettings;
  onChange: (patch: Partial<SetSettings>) => void;
  /** Easy mode (#52): only title + description; hide reveal/answer-flow
   * options. Existing values stay stored. */
  easyMode?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="grid max-w-2xl gap-8">
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
  template?: "yes_no";
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
    template: "yes_no",
    label: "Yes/No",
    description: "Single choice with the fixed answers Yes and No.",
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

/** "+ Neue Frage" dropdown: question type with a one-line explanation. */
function NewQuestionMenu({
  onPick,
}: {
  onPick: (kind: QuestionKind, template?: "yes_no") => void;
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
          {QUESTION_TYPES.map((type) => (
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

  const [questionLinkCopied, setQuestionLinkCopied] = useState(false);
  async function copyQuestionLink(questionId: number) {
    const url = `${window.location.origin}/sets/${id}/present?question=${questionId}`;
    await navigator.clipboard.writeText(url);
    setQuestionLinkCopied(true);
    window.setTimeout(() => setQuestionLinkCopied(false), 1500);
  }

  function doExport() {
    const a = document.createElement("a");
    a.href = results.exportUrl(id);
    a.click();
  }

  function addQuestion(kind: QuestionKind, template?: "yes_no") {
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
        <Link to="/" className="hover:text-brand-700 dark:hover:text-brand-300">
          {t("My rooms")}
        </Link>{" "}
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
            <h1 className="text-2xl font-bold">{localizedText(set.title)}</h1>
            <MoreMenu label={t("Set actions")}>
              <MenuItem onClick={startMetaEdit}><Settings aria-hidden className="h-4 w-4" />{t("Settings")}</MenuItem>
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
          {/* Rendered as rich HTML from the WYSIWYG editor (#49). */}
          <div className="mt-1 max-w-2xl text-sm">
            {localizedText(set.description) ? (
              <RichText html={localizedText(set.description)} />
            ) : (
              <span className="italic text-slate-400">{t("No description")}</span>
            )}
          </div>
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
          <p className="mt-1 text-xs text-slate-400">
            {t("Created {{created}} · Updated {{updated}}", {
              created: formatDate(set.created_at),
              updated: formatDate(set.updated_at),
            })}
            {set.share_token && t(" · shareable via link")}
          </p>
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
              <Button
                variant="primary"
                onClick={() =>
                  navigate(`/sets/${id}/present${recordMode ? "?recording=1" : ""}`)
                }
                className="inline-flex items-center gap-1.5"
              >
                <Play aria-hidden className="h-4 w-4" />{t("Present")}
              </Button>
              {/* Easy mode (#52): self-paced quiz is a Pro feature — always live. */}
              {!easyMode && (
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
          <NewQuestionMenu onPick={(kind, template) => void addQuestion(kind, template)} />
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
      {questionLinkCopied && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-slate-900 px-4 py-2 text-sm text-white shadow-lg dark:bg-slate-100 dark:text-slate-900">
          {t("Copied")}
        </div>
      )}
    </div>
  );
}
