// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Check, Eye, FolderInput, ImageOff, ImagePlus, Link2, Pencil, Shuffle, X } from "lucide-react";
import {
  API_BASE_URL,
  api,
  type AnswerOption,
  type Question,
  type QuestionSet,
  type RevealAnswers,
} from "../api";
import { useApp, useEasyMode } from "../App";
import {
  getDefaultContentLang,
  localizedMap,
  localizedText,
  setLocalizedLang,
  type LocalizedText,
} from "@basicbar/ui";
import AiAssistPanel from "../components/AiAssistPanel";
import RichText from "../components/RichText";
import SortableList from "../components/SortableList";
import TranslatableField from "../components/TranslatableField";
import { Button, Field, SegmentedControl, TextInput } from "../components/ui";
import { REVEAL_LABEL } from "./SetPage";

function aiErrorText(err: unknown): string {
  try {
    return JSON.parse((err as Error).message).detail ?? String(err);
  } catch {
    return String(err);
  }
}

function stripHtml(html: string) {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent?.trim() ?? "";
}

/** Options get a stable client-side id for drag-and-drop before they have a
 * server id (negative values never collide with real primary keys). Text is
 * kept as the full `{de, en}` map so each option can be edited bilingually
 * via TranslatableField (#33 MR2 Task 9). */
type EditableOption = Omit<AnswerOption, "text"> & { text: LocalizedText; clientId: number };
let nextClientId = -1;

// Mirrors backend Question.kind choices; used to validate the `?kind=`
// query param on a new (unsaved) question.
const QUESTION_KINDS = [
  "single_choice", "multiple_choice", "word_cloud", "likert",
  "open_text", "priorities", "ordering",
] as const;

/** Per-kind default options for a brand-new question, moved out of
 * `SetPage.addQuestion` now that creation is deferred to the first save. */
function defaultOptions(kind: string, template?: string | null): EditableOption[] {
  if (kind === "word_cloud" || kind === "open_text" || kind === "likert") return [];
  // The binary preset starts as Ja/Nein; the editor's template quick-fill
  // lets the author switch to Wahr/Falsch or type their own (#79).
  const texts = template === "binary" ? ["Ja", "Nein"] : ["", "", ""];
  return texts.map((text) => ({ clientId: nextClientId--, text, is_correct: false }));
}

/** Likert scales are fixed presets — freely editable items would make the
 * question plain single choice and break ordinal analyses (review feedback).
 * The only extra is an optional abstention. */
const ABSTENTION = "Enthaltung";
// Labels are English source strings, translated with t() at the render site
// (same pattern as TIME_PRESETS below).
const LIKERT_PRESETS: { key: string; label: string; options: string[] }[] = [
  {
    key: "agree5",
    label: "Agreement — 5 levels",
    options: [
      "Stimme voll zu",
      "Stimme eher zu",
      "Teils-teils",
      "Stimme eher nicht zu",
      "Stimme gar nicht zu",
    ],
  },
  {
    key: "agree4",
    label: "Agreement — 4 levels (no middle)",
    options: [
      "Stimme voll zu",
      "Stimme eher zu",
      "Stimme eher nicht zu",
      "Stimme gar nicht zu",
    ],
  },
  {
    key: "freq5",
    label: "Frequency — 5 levels",
    options: ["Immer", "Oft", "Manchmal", "Selten", "Nie"],
  },
  {
    key: "rating5",
    label: "Rating — 5 levels",
    options: ["Sehr gut", "Eher gut", "Mittel", "Eher schlecht", "Sehr schlecht"],
  },
];

/** Typical time limits as one-click presets that fill the always-visible
 * seconds field; "keine" (empty) is the default, any other value can be
 * typed directly (#5). */
// Labels are English source strings, translated with t() at the render site.
const TIME_PRESETS: { label: string; value: string }[] = [
  { label: "none", value: "" },
  { label: "30 s", value: "30" },
  { label: "60 s", value: "60" },
  { label: "2 min", value: "120" },
  { label: "5 min", value: "300" },
];

// Free-text AI evaluation scales: two presets plus free categories.
// Labels are English source strings, translated with t() at the render site
// (same pattern as TIME_PRESETS below). The category VALUES stay German —
// they are authored content inserted into the question, not UI chrome.
const EVAL_PRESETS: { value: string; label: string; categories: string[] }[] = [
  { value: "correctness", label: "Correctness (correct · unclear · wrong)", categories: ["korrekt", "unklar", "falsch"] },
  { value: "sentiment", label: "Sentiment (positive · neutral · negative)", categories: ["positiv", "neutral", "negativ"] },
  { value: "custom", label: "Custom categories …", categories: [] },
];

function detectEvalPreset(categories: string[]): string {
  const eq = (a: string[], b: string[]) =>
    a.length === b.length && a.every((x, i) => x.toLowerCase() === b[i].toLowerCase());
  const preset = EVAL_PRESETS.find((p) => p.categories.length && eq(categories, p.categories));
  return preset?.value ?? "custom";
}

function detectPreset(options: { text: LocalizedText; is_abstention?: boolean }[]): string {
  const scale = options.filter((o) => !o.is_abstention).map((o) => localizedText(o.text));
  const match = LIKERT_PRESETS.find(
    (preset) =>
      preset.options.length === scale.length &&
      preset.options.every((text, index) => text === scale[index]),
  );
  return match ? match.key : "custom";
}

/** Question editor: rich text, kind-specific options, save on demand. */
export default function QuestionPage() {
  const { t } = useTranslation();
  const { setId, questionId } = useParams();
  const [searchParams] = useSearchParams();
  const isNew = questionId === "new";
  const navigate = useNavigate();
  const [question, setQuestion] = useState<Question | null>(null);
  const [set, setSet] = useState<QuestionSet | null>(null);
  const [text, setText] = useState<LocalizedText>("");
  const [shuffle, setShuffle] = useState(false);
  const [binaryChoice, setBinaryChoice] = useState(false);
  const [reveal, setReveal] = useState<"inherit" | RevealAnswers>("inherit");
  const [options, setOptions] = useState<EditableOption[]>([]);
  const [timeLimit, setTimeLimit] = useState("");
  const [likertPreset, setLikertPreset] = useState("agree5");
  const [abstention, setAbstention] = useState(false);
  const [aiEvaluate, setAiEvaluate] = useState(false);
  const [evaluationHint, setEvaluationHint] = useState("");
  const [evalCategories, setEvalCategories] = useState<string[]>(["korrekt", "unklar", "falsch"]);
  const [evalScale, setEvalScale] = useState<string>("correctness");
  const [evalChart, setEvalChart] = useState(false);
  const [modelSolution, setModelSolution] = useState("");
  const [participantFeedback, setParticipantFeedback] = useState(false);
  const [allowMultiple, setAllowMultiple] = useState(false);
  const [wordcloudMaxAnswers, setWordcloudMaxAnswers] = useState(0);
  const [wordcloudLive, setWordcloudLive] = useState(true);
  const [wordcloudAiEnabled, setWordcloudAiEnabled] = useState(false);
  const [wordcloudGrouping, setWordcloudGrouping] = useState("");
  const [saving, setSaving] = useState(false);
  // #74: switch between editing and an interactive participant preview (iframe).
  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const [previewNonce, setPreviewNonce] = useState(0);
  const [error, setError] = useState("");
  const [moveTargets, setMoveTargets] = useState<QuestionSet[] | null>(null);
  const [moveRooms, setMoveRooms] = useState<{ id: number; title: string }[]>([]);
  const [moveRoom, setMoveRoom] = useState<number | null>(null);
  const [moveTarget, setMoveTarget] = useState<number | null>(null);
  const [moveError, setMoveError] = useState("");
  const { whoami } = useApp();
  const easyMode = useEasyMode();
  const aiEnabled = !!whoami?.ai_enabled && !easyMode;
  const [aiBusy, setAiBusy] = useState<"" | "distractors" | "rephrase">("");
  const [aiError, setAiError] = useState("");
  const [aiDistractorError, setAiDistractorError] = useState("");
  const [aiDistractors, setAiDistractors] = useState<string[]>([]);
  const [aiVariants, setAiVariants] = useState<string[]>([]);

  useEffect(() => {
    void api.getQuestionSet(Number(setId)).then(setSet);
    if (isNew) {
      const raw = searchParams.get("kind") ?? "single_choice";
      const kind = (QUESTION_KINDS as readonly string[]).includes(raw)
        ? (raw as Question["kind"])
        : "single_choice";
      const template = searchParams.get("template");
      // Synthetic question so kind-based derivations and the `!question`
      // render guard work; id 0 until the first save creates the real row.
      setQuestion({ id: 0, kind, is_after: false } as Question);
      setText("");
      setBinaryChoice(template === "binary");
      setOptions(defaultOptions(kind, template));
      return;
    }
    // Already have this question in state (e.g. just created via save →
    // URL replaced to the real id) — don't refetch and clobber live edits.
    if (question && question.id === Number(questionId)) return;
    void api.getQuestion(Number(questionId)).then((data) => {
      setQuestion(data);
      setText(data.text);
      setShuffle(data.shuffle_options);
      setBinaryChoice(data.binary_choice ?? false);
      setReveal(data.reveal_answers);
      setAiEvaluate(data.ai_evaluate);
      setEvaluationHint(data.evaluation_hint);
      const cats = data.evaluation_categories?.length
        ? data.evaluation_categories
        : ["korrekt", "unklar", "falsch"];
      setEvalCategories(cats);
      setEvalScale(detectEvalPreset(cats));
      setEvalChart(data.evaluation_chart);
      setModelSolution(data.model_solution ?? "");
      setParticipantFeedback(data.participant_feedback ?? false);
      setAllowMultiple(data.allow_multiple);
      setWordcloudMaxAnswers(data.wordcloud_max_answers ?? 0);
      setWordcloudLive(data.wordcloud_live);
      setWordcloudAiEnabled(data.wordcloud_ai_enabled);
      setWordcloudGrouping(data.wordcloud_grouping);
      setTimeLimit(data.time_limit ? String(data.time_limit) : "");
      // Options keep the full {de, en} map so each can be edited bilingually
      // (#33 MR2 Task 9).
      const editableOptions = data.options.map((option) => ({
        ...option,
        clientId: option.id ?? nextClientId--,
      }));
      if (data.kind === "likert") {
        setLikertPreset(detectPreset(editableOptions));
        setAbstention(editableOptions.some((option) => option.is_abstention));
      }
      setOptions(editableOptions);
    });
  }, [questionId]);

  // Clear the stale error banner (validation guard or a prior save's server
  // error) as soon as the user edits the text or the options — otherwise it
  // lingers even after the field that triggered it is fixed (#90/#100).
  useEffect(() => {
    setError("");
  }, [text, options]);

  function updateOption(clientId: number, patch: Partial<EditableOption>) {
    setOptions((current) =>
      current.map((option) => {
        if (option.clientId !== clientId) return option;
        const updated = { ...option, ...patch };
        return updated;
      }),
    );
  }

  async function uploadOptionImage(clientId: number, file: File) {
    const uploaded = await api.uploadImage(file);
    updateOption(clientId, { image: uploaded.url });
  }

  function setCorrect(clientId: number, checked: boolean) {
    setOptions((current) =>
      current.map((option) => {
        if (option.clientId === clientId) return { ...option, is_correct: checked };
        // Single choice: at most one correct answer.
        if (checked && question?.kind === "single_choice")
          return { ...option, is_correct: false };
        return option;
      }),
    );
  }

  // Binary template quick-fill (#79): overwrite the two option texts with a
  // preset (Ja/Nein or Wahr/Falsch), keeping which one is marked correct.
  function applyBinaryTemplate(texts: [string, string]) {
    setOptions((current) =>
      texts.map((text, i) => ({
        clientId: current[i]?.clientId ?? nextClientId--,
        text,
        is_correct: current[i]?.is_correct ?? false,
      })),
    );
  }

  function likertOptions(): AnswerOption[] {
    const preset = LIKERT_PRESETS.find((entry) => entry.key === likertPreset);
    const scale = preset
      ? preset.options
      : options.filter((o) => !o.is_abstention).map((o) => o.text);
    const result: AnswerOption[] = scale.map((text) => ({
      text,
      is_correct: false,
    }));
    if (abstention) {
      result.push({ text: ABSTENTION, is_correct: false, is_abstention: true });
    }
    return result;
  }

  async function save({ stay = false }: { stay?: boolean } = {}) {
    if (!question) return false;
    if (invalid) {
      setError(
        textMissing
          ? t("Question text is required.")
          : t("Add at least two answer options, each with text."),
      );
      return false;
    }
    setSaving(true);
    setError("");
    try {
      const parsedLimit = parseInt(timeLimit, 10);
      const payload = {
        kind: question.kind,
        text,
        shuffle_options: shuffle,
        binary_choice: question.kind === "single_choice" && binaryChoice,
        reveal_answers:
          question.kind === "single_choice" || question.kind === "multiple_choice"
            ? reveal
            : "inherit",
        ai_evaluate: question.kind === "open_text" && aiEvaluate,
        evaluation_hint: question.kind === "open_text" ? evaluationHint : "",
        evaluation_categories:
          question.kind === "open_text"
            ? evalCategories.map((c) => c.trim()).filter(Boolean)
            : ["korrekt", "unklar", "falsch"],
        evaluation_chart: question.kind === "open_text" && evalChart,
        model_solution: question.kind === "open_text" ? modelSolution : "",
        participant_feedback: question.kind === "open_text" && participantFeedback,
        allow_multiple: question.kind === "word_cloud" && allowMultiple,
        wordcloud_max_answers:
          question.kind === "word_cloud" && allowMultiple ? wordcloudMaxAnswers : 0,
        wordcloud_live: question.kind !== "word_cloud" || wordcloudLive,
        wordcloud_ai_enabled: question.kind === "word_cloud" && wordcloudAiEnabled,
        wordcloud_grouping: question.kind === "word_cloud" ? wordcloudGrouping : "",
        time_limit: Number.isFinite(parsedLimit) && parsedLimit > 0 ? parsedLimit : null,
        options:
          question.kind === "word_cloud" || question.kind === "open_text"
            ? []
            : question.kind === "likert"
              ? likertOptions()
              : filledOptions.map(({ clientId, id, ...option }) => ({
                  ...(id ? { id } : {}),
                  ...option,
                })),
      };
      if (isNew) {
        const created = await api.createQuestion({
          question_set: Number(setId),
          ...payload,
        });
        setQuestion(created);
        if (stay) {
          // Adopt the real id so the editor leaves new mode; the effect
          // re-runs once on the new questionId and reloads the saved data.
          navigate(`/sets/${setId}/questions/${created.id}`, { replace: true });
        } else {
          navigate(`/sets/${setId}`);
        }
        return true;
      }
      await api.updateQuestion(question.id, payload);
      if (!stay) navigate(`/sets/${setId}`);
      return true;
    } catch (err) {
      setError(String(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  // #74: save first (so the preview reflects the stored state), then show the
  // interactive participant preview in an iframe. The nonce reloads the iframe.
  async function showPreview() {
    if (await save({ stay: true })) {
      setPreviewNonce((n) => n + 1);
      setTab("preview");
    }
  }

  async function openMove() {
    // Two-stage picker (review feedback): choose the room first, then one
    // of its sets. Defaults to the room the question currently lives in.
    const [page, currentSet] = await Promise.all([
      api.listAllQuestionSets(),
      api.getQuestionSet(Number(setId)),
    ]);
    const targets = page.results.filter((entry) => entry.id !== Number(setId));
    const rooms = [
      ...new Map(targets.map((entry) => [entry.room, entry.room_title])),
    ].map(([id, title]) => ({ id, title }));
    const startRoom = rooms.some((room) => room.id === currentSet.room)
      ? currentSet.room
      : (rooms[0]?.id ?? null);
    setMoveTargets(targets);
    setMoveRooms(rooms);
    setMoveRoom(startRoom);
    setMoveTarget(targets.find((entry) => entry.room === startRoom)?.id ?? null);
    setMoveError("");
  }

  function pickMoveRoom(roomId: number) {
    setMoveRoom(roomId);
    setMoveTarget(
      moveTargets?.find((entry) => entry.room === roomId)?.id ?? null,
    );
  }

  async function handleMove() {
    if (!question || moveTarget === null) return;
    setMoveError("");
    try {
      await api.moveQuestion(question.id, moveTarget);
      navigate(`/sets/${moveTarget}`);
    } catch (err) {
      try {
        setMoveError(JSON.parse((err as Error).message).detail ?? String(err));
      } catch {
        setMoveError(String(err));
      }
    }
  }

  async function runDistractors() {
    if (!question) return;
    setAiBusy("distractors");
    setAiDistractorError("");
    setAiDistractors([]);
    try {
      const payload = {
        text: localizedText(text),
        options: options.map((o) => ({ text: localizedText(o.text), is_correct: o.is_correct })),
        count: 3,
      };
      // Not saved yet — no question id to scope the endpoint to, so use the
      // set-scoped variant instead (same logic, reads the draft body).
      const { distractors } = isNew
        ? await api.aiDistractorsForSet(Number(setId), payload)
        : await api.aiDistractors(question.id, payload);
      setAiDistractors(distractors);
      if (distractors.length === 0) setAiDistractorError(t("No suggestions received."));
    } catch (err) {
      setAiDistractorError(aiErrorText(err));
    } finally {
      setAiBusy("");
    }
  }

  async function runRephrase() {
    if (!question) return;
    setAiBusy("rephrase");
    setAiError("");
    setAiVariants([]);
    try {
      // Not saved yet — use the set-scoped variant (see runDistractors above).
      const { variants } = isNew
        ? await api.aiRephraseForSet(Number(setId), localizedText(text))
        : await api.aiRephrase(question.id, localizedText(text));
      setAiVariants(variants);
      if (variants.length === 0) setAiError(t("No suggestions received."));
    } catch (err) {
      setAiError(aiErrorText(err));
    } finally {
      setAiBusy("");
    }
  }

  function applyDistractor(value: string) {
    // Binary (Ja/Nein, Wahr/Falsch) must stay exactly two options — never add
    // a third one here (#101; the AI panel is also hidden for binary above,
    // this is defense-in-depth).
    if (binaryChoice) return;
    setOptions((current) => {
      // Fill the first empty option before adding a new row (review feedback).
      const emptyIndex = current.findIndex(
        (option) => !localizedText(option.text).trim() && !option.image,
      );
      const canonical = getDefaultContentLang() as "de" | "en";
      if (emptyIndex >= 0) {
        return current.map((option, index) =>
          index === emptyIndex
            ? { ...option, text: setLocalizedLang(option.text, canonical, value) }
            : option,
        );
      }
      return [...current, { clientId: nextClientId--, text: value, is_correct: false }];
    });
    setAiDistractors((current) => current.filter((item) => item !== value));
  }

  if (!question) return null;
  const isLikert = question.kind === "likert";
  const isChoice =
    question.kind !== "word_cloud" &&
    question.kind !== "open_text" &&
    !isLikert;
  const isPriorities = question.kind === "priorities";
  const isOrdering = question.kind === "ordering";
  // Kinds with a "correct answer" concept. Priorities, Ordering and Likert
  // use the option list but have no correct answer (#58, #72).
  const hasCorrect =
    question.kind === "single_choice" || question.kind === "multiple_choice";

  // Content validity (#32/#23): canonical-language question text required
  // (image-only text counts); option-bearing kinds need >=2 filled options
  // (text or image). Mirrors the backend QuestionSerializer.validate rule.
  const canonicalLang = getDefaultContentLang() as "de" | "en";
  const canonicalHtml = localizedMap(text)[canonicalLang] ?? "";
  const textMissing = !stripHtml(canonicalHtml) && !/<img/i.test(canonicalHtml);
  // Ignore unfilled trailing options (e.g. a freshly-added blank row) rather
  // than failing validation on their account — only options that actually
  // carry text or an image count, and only those are sent to the backend
  // (#90, #100; applies to single/multiple choice, priorities and ordering
  // alike, since they all share this option list).
  const filledOptions = options.filter(
    (o) => (localizedMap(o.text)[canonicalLang] ?? "").trim() !== "" || !!o.image,
  );
  const optionsMissing = isChoice && filledOptions.length < 2;
  const invalid = textMissing || optionsMissing;

  const breadcrumb = (leaf: string) => (
    <nav className="mb-4 text-sm text-slate-500 dark:text-slate-400">
      <Link to="/" className="hover:text-brand-700 dark:hover:text-brand-300">
        {t("My rooms")}
      </Link>{" "}
      /{" "}
      {set && (
        <>
          <Link
            to={`/rooms/${set.room}`}
            className="hover:text-brand-700 dark:hover:text-brand-300"
          >
            {set.room_title}
          </Link>{" "}
          /{" "}
        </>
      )}
      <Link to={`/sets/${setId}`} className="hover:text-brand-700 dark:hover:text-brand-300">
        {set ? localizedText(set.title) : t("Question set")}
      </Link>{" "}
      / {leaf}
    </nav>
  );

  // Locked after-question (#54): content mirrors the before-question and is
  // edited there — show a read-only preview + a link, no editable fields.
  if (question.is_after) {
    return (
      <div className="max-w-2xl">
        {breadcrumb(t("After-question"))}
        <div className="mb-4 rounded-xl border border-brand-200 bg-brand-50/60 px-4 py-3 dark:border-brand-900 dark:bg-brand-950/40">
          <p className="text-sm font-medium text-slate-800 dark:text-slate-100">
            {t("This is an after-question. Its content mirrors the before-question and is edited there.")}
          </p>
          <Link
            to={`/sets/${setId}/questions/${question.before_question}`}
            className="mt-1 inline-flex items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline dark:text-brand-300"
          >
            <Link2 aria-hidden className="h-4 w-4" />
            {t("Open before-question")}
          </Link>
        </div>
        <div className="grid gap-4">
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
              {t("Question text")}
            </span>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm dark:border-slate-800 dark:bg-slate-900/60">
              {localizedText(text) ? (
                <RichText html={localizedText(text)} />
              ) : (
                <span className="italic text-slate-400">{t("No question text")}</span>
              )}
            </div>
          </div>
          {(isChoice || isLikert) && (
            <div>
              <span className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
                {isLikert ? t("Scale") : t("Answer options")}
              </span>
              <ul className="grid gap-1.5">
                {options.map((option) => (
                  <li
                    key={option.clientId}
                    className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800"
                  >
                    {option.is_correct && (
                      <Check aria-label={t("Correct")} className="h-4 w-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                    )}
                    <span className="text-slate-700 dark:text-slate-200">
                      {localizedText(option.text) || <span className="italic text-slate-400">—</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <div className="mt-5">
          <Button variant="ghost" onClick={() => navigate(`/sets/${setId}`)}>
            {t("Back")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl">
      {breadcrumb(t("Edit question"))}

      {question.after_question != null && (
        <div className="mb-4 flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
          <Link2 aria-hidden className="h-3.5 w-3.5" />
          {t("This question has an after-question — its content follows this one.")}{" "}
          <Link
            to={`/sets/${setId}/questions/${question.after_question}`}
            className="font-semibold text-brand-700 hover:underline dark:text-brand-300"
          >
            {t("Open after-question")}
          </Link>
        </div>
      )}

      <div className="mb-4 flex justify-end">
        <SegmentedControl
          ariaLabel={t("View")}
          value={tab}
          disabled={saving}
          onChange={(v) => (v === "preview" ? void showPreview() : setTab("edit"))}
          options={[
            {
              value: "edit",
              label: (
                <>
                  <Pencil aria-hidden className="h-3.5 w-3.5" />
                  {t("Edit")}
                </>
              ),
            },
            {
              value: "preview",
              label: (
                <>
                  <Eye aria-hidden className="h-3.5 w-3.5" />
                  {t("Preview")}
                </>
              ),
            },
          ]}
        />
      </div>

      {tab === "preview" && (
        <div className="mx-auto max-w-sm overflow-hidden rounded-2xl border border-slate-200 shadow-sm dark:border-slate-700">
          <iframe
            key={previewNonce}
            title={t("Preview")}
            src={`${API_BASE_URL}/question-preview/${question.id}/`}
            className="h-[640px] w-full bg-white"
          />
        </div>
      )}

      {tab === "edit" && (
      <div className="grid gap-5">
        <TranslatableField variant="rich" label={t("Question text")} value={text} onChange={setText} />
        {textMissing && (
          <p className="mt-1 text-sm text-red-600 dark:text-red-400">
            {t("Question text is required.")}
          </p>
        )}

        {aiEnabled && (
          <AiAssistPanel title={t("Rephrase question")}>
            <Button onClick={() => void runRephrase()} disabled={aiBusy === "rephrase"}>
              {aiBusy === "rephrase" ? t("Generating …") : t("Generate suggestions")}
            </Button>
            {aiVariants.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {aiVariants.map((variant, index) => (
                  <li key={index}>
                    <button
                      type="button"
                      onClick={() => {
                        // Rephrasing is generated from (and replaces) the
                        // canonical language only — any existing translation
                        // in the other language is left in place.
                        setText((current) => setLocalizedLang(current, getDefaultContentLang() as "de" | "en", variant));
                        setAiVariants([]);
                      }}
                      className="w-full rounded-lg border border-slate-200 px-3 py-2 text-left text-sm hover:border-brand-500 dark:border-slate-700"
                    >
                      {variant}
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {aiError && <p className="mt-1 text-sm text-red-600">{aiError}</p>}
          </AiAssistPanel>
        )}

        {isChoice && (
          <>
            <div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  {t("Answer options")}
                </span>
                {hasCorrect && (
                  <span className="text-xs text-slate-400">
                    {t("Checkbox = correct answer")}
                  </span>
                )}
                {isPriorities && (
                  <span className="text-xs text-slate-400">
                    {t("Participants distribute up to 100 points")}
                  </span>
                )}
              </div>
              {isOrdering && (
                <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                  {t("The option order is the correct solution — participants see it shuffled.")}
                </p>
              )}
              {binaryChoice && (
                <div className="mb-2 flex items-center gap-2 text-sm">
                  <span className="text-slate-500 dark:text-slate-400">{t("Template")}</span>
                  <button
                    type="button"
                    onClick={() => applyBinaryTemplate(["Ja", "Nein"])}
                    className="rounded-full border border-slate-300 px-3 py-1 text-slate-600 transition-colors hover:border-brand-500 hover:text-brand-700 dark:border-slate-700 dark:text-slate-300 dark:hover:text-brand-300"
                  >
                    {t("Yes/No")}
                  </button>
                  <button
                    type="button"
                    onClick={() => applyBinaryTemplate(["Wahr", "Falsch"])}
                    className="rounded-full border border-slate-300 px-3 py-1 text-slate-600 transition-colors hover:border-brand-500 hover:text-brand-700 dark:border-slate-700 dark:text-slate-300 dark:hover:text-brand-300"
                  >
                    {t("True/False")}
                  </button>
                </div>
              )}
              <SortableList
                items={options.map((option) => ({ ...option, id: option.clientId }))}
                onReorder={(items) =>
                  setOptions(
                    items.map(
                      (item) =>
                        options.find((option) => option.clientId === item.id)!,
                    ),
                  )
                }
                renderItem={(item) => (
                  <>
                    {hasCorrect && (
                      <input
                        type="checkbox"
                        aria-label={t("Mark as correct")}
                        checked={item.is_correct}
                        onChange={(event) => setCorrect(item.id, event.target.checked)}
                        className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
                      />
                    )}
                    <TranslatableField
                      value={item.text}
                      placeholder={t("Answer text")}
                      ariaLabel={t("Answer text")}
                      onChange={(text) => updateOption(item.id, { text })}
                      className="min-w-0 flex-1"
                    />
                    {!isLikert && (
                      <label
                        title={item.image ? t("Replace image") : t("Add image")}
                        className="shrink-0 cursor-pointer rounded-lg px-1.5 py-1 hover:bg-slate-100 dark:hover:bg-slate-800"
                      >
                        {item.image ? (
                          <img
                            src={`${API_BASE_URL}${item.image}`}
                            alt={t("Answer image")}
                            className="h-9 w-9 rounded-lg border border-slate-200 object-cover dark:border-slate-700"
                          />
                        ) : (
                          <ImagePlus aria-hidden className="h-5 w-5 opacity-60" />
                        )}
                        <input
                          type="file"
                          accept="image/*"
                          className="sr-only"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) void uploadOptionImage(item.id, file);
                            event.target.value = "";
                          }}
                        />
                      </label>
                    )}
                    {!isLikert && item.image && (
                      <Button
                        variant="ghost"
                        aria-label={t("Remove image")}
                        title={t("Remove image")}
                        onClick={() => updateOption(item.id, { image: "" })}
                      >
                        <ImageOff aria-hidden className="h-4 w-4" />
                      </Button>
                    )}
                    {!binaryChoice && (
                      <Button
                        variant="ghost"
                        aria-label={t("Delete answer")}
                        onClick={() =>
                          setOptions((current) =>
                            current.filter((option) => option.clientId !== item.id),
                          )
                        }
                      >
                        <X aria-hidden className="h-4 w-4" />
                      </Button>
                    )}
                  </>
                )}
              />
              <div className="mt-2 flex flex-wrap items-center gap-2">
                {!binaryChoice && (
                  <Button
                    onClick={() =>
                      setOptions((current) => [
                        ...current,
                        { clientId: nextClientId--, text: "", is_correct: false },
                      ])
                    }
                  >
                    + {t("Add answer")}
                  </Button>
                )}
                {/* Random order is meaningless for priorities (sliders, order
                    irrelevant) and for ordering (the server always shuffles —
                    that's the task), so hide the toggle for those kinds. */}
                {!isPriorities && !isOrdering && (
                  <button
                    type="button"
                    onClick={() => setShuffle((value) => !value)}
                    aria-pressed={shuffle}
                    title={t("Show answer options to participants in random order")}
                    className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm transition-colors ${
                      shuffle
                        ? "border-brand-600 bg-brand-50 text-brand-800 dark:border-brand-500 dark:bg-brand-950 dark:text-brand-200"
                        : "border-slate-300 text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                    }`}
                  >
                    <Shuffle aria-hidden className="h-4 w-4" />
                    {shuffle ? t("Random order on") : t("Random order off")}
                  </button>
                )}
              </div>
              {optionsMissing && (
                <p className="mt-2 text-sm text-red-600 dark:text-red-400">
                  {t("Add at least two answer options, each with text.")}
                </p>
              )}

              {/* Per-question reveal of the correct answer (#28); only for
                  kinds that have a correct answer. */}
              {hasCorrect && (
                <label className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  {t("Reveal correct answer:")}
                  <select
                    value={reveal}
                    onChange={(event) =>
                      setReveal(event.target.value as "inherit" | RevealAnswers)
                    }
                    className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
                  >
                    <option value="inherit">
                      {t("As in the set")}
                      {set ? ` (${t(REVEAL_LABEL[set.reveal_answers])})` : ""}
                    </option>
                    <option value="immediately">{t(REVEAL_LABEL.immediately)}</option>
                    <option value="after_close">{t(REVEAL_LABEL.after_close)}</option>
                    <option value="never">{t(REVEAL_LABEL.never)}</option>
                  </select>
                </label>
              )}

              {aiEnabled && hasCorrect && !binaryChoice && (
                <div className="mt-3">
                  <AiAssistPanel title={t("Suggest distractors")}>
                    <Button
                      onClick={() => void runDistractors()}
                      disabled={aiBusy === "distractors"}
                    >
                      {aiBusy === "distractors" ? t("Generating …") : t("Suggest wrong answers")}
                    </Button>
                    {aiDistractors.length > 0 && (
                      <ul className="mt-2 space-y-1.5">
                        {aiDistractors.map((distractor, index) => (
                          <li key={index} className="flex items-center gap-2">
                            <span className="min-w-0 flex-1 truncate text-sm text-slate-700 dark:text-slate-300">
                              {distractor}
                            </span>
                            <Button onClick={() => applyDistractor(distractor)}>
                              + {t("Use")}
                            </Button>
                          </li>
                        ))}
                      </ul>
                    )}
                    {aiDistractorError && (
                      <p className="mt-1 text-sm text-red-600">{aiDistractorError}</p>
                    )}
                  </AiAssistPanel>
                </div>
              )}
            </div>

          </>
        )}

        {isLikert && (
          <div className="grid gap-3">
            <Field label={t("Scale")}>
              <select
                value={likertPreset}
                onChange={(event) => setLikertPreset(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
              >
                {LIKERT_PRESETS.map((preset) => (
                  <option key={preset.key} value={preset.key}>
                    {t(preset.label)}
                  </option>
                ))}
                {likertPreset === "custom" && (
                  <option value="custom">{t("Custom scale (imported)")}</option>
                )}
              </select>
            </Field>
            <ol className="flex flex-wrap gap-2 text-sm">
              {(LIKERT_PRESETS.find((p) => p.key === likertPreset)?.options ??
                options.filter((o) => !o.is_abstention).map((o) => o.text)
              ).map((text, index) => (
                <li
                  key={index}
                  className="rounded-lg bg-slate-100 px-2.5 py-1 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                >
                  {localizedText(text)}
                </li>
              ))}
              {abstention && (
                <li className="rounded-lg border border-dashed border-slate-300 px-2.5 py-1 text-slate-500 dark:border-slate-700 dark:text-slate-400">
                  {ABSTENTION}
                </li>
              )}
            </ol>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={abstention}
                onChange={(event) => setAbstention(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Offer “{{abstention}}” as an additional option", {
                abstention: ABSTENTION,
              })}
            </label>
            <p className="text-xs text-slate-400">
              {t(
                "The scale steps are fixed — this keeps Likert evaluations comparable across questions and semesters.",
              )}
            </p>
          </div>
        )}

        {question.kind === "word_cloud" && (
          <div className="grid gap-3">
            <p className="rounded-xl bg-brand-50 dark:bg-brand-950 px-4 py-3 text-sm text-slate-700 dark:text-slate-300">
              <strong>{t("Word cloud:")}</strong>{" "}
              {t(
                "Participants enter free-form terms; spelling variants (upper/lower case) are merged. There are no answer options here.",
              )}
            </p>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={allowMultiple}
                onChange={(event) => setAllowMultiple(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Allow multiple answers per person (with “+” and “Done”)")}
            </label>
            {allowMultiple && (
              <label className="ml-6 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                {t("Maximum contributions per person")}
                <input
                  type="number"
                  min={0}
                  value={wordcloudMaxAnswers || ""}
                  onChange={(event) =>
                    setWordcloudMaxAnswers(Math.max(0, Number(event.target.value) || 0))
                  }
                  className="w-20 rounded-lg border border-slate-300 dark:border-slate-700 bg-white px-2 py-1 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
                />
                <span className="text-slate-400">{t("(0 = no limit)")}</span>
              </label>
            )}
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={wordcloudLive}
                onChange={(event) => setWordcloudLive(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Show the word cloud on the projector while voting is still open")}
              <span className="text-slate-400">{t("(otherwise only after closing)")}</span>
            </label>
          </div>
        )}
        {question.kind === "word_cloud" && aiEnabled && (
          <AiAssistPanel title={t("Clean up word cloud with AI (presentation)")}>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={wordcloudAiEnabled}
                onChange={(event) => setWordcloudAiEnabled(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Merge similar terms, synonyms and typos")}
            </label>
            <p className="mt-1 text-xs text-slate-400">
              {t(
                "In addition to the automatic upper/lower case correction. In presentation mode, switch between Original, Cleaned up and Grouped with the “a” key / “View” button.",
              )}
            </p>
            {/* Independent of the merge checkbox above — grouping can be
                enabled/edited on its own (#34). */}
            <label className="mt-3 grid gap-1 text-sm text-slate-700 dark:text-slate-300">
              {t("Group by … (optional)")}
              <input
                type="text"
                value={wordcloudGrouping}
                onChange={(event) => setWordcloudGrouping(event.target.value)}
                placeholder={t("e.g. “by topic area” — empty = automatic topics")}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
              <span className="text-xs text-slate-400">
                {t("Controls the “Grouped” AI view — works independently of merging above.")}
              </span>
            </label>
          </AiAssistPanel>
        )}
        {question.kind === "open_text" && (
          <p className="rounded-xl bg-brand-50 dark:bg-brand-950 px-4 py-3 text-sm text-slate-700 dark:text-slate-300">
            <strong>{t("Free text:")}</strong>{" "}
            {t(
              "Participants write a free-form answer (max. 500 characters); the answers are shown as a list.",
            )}
          </p>
        )}
        {question.kind === "open_text" && aiEnabled && (
          <AiAssistPanel title={t("AI evaluation (live)")}>
            <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
              <input
                type="checkbox"
                checked={aiEvaluate}
                onChange={(event) => setAiEvaluate(event.target.checked)}
                className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
              />
              {t("Have the AI assign answers to a scale live")}
            </label>
            {aiEvaluate && (
              <div className="mt-2">
                <textarea
                  value={evaluationHint}
                  onChange={(event) => setEvaluationHint(event.target.value)}
                  rows={2}
                  placeholder={t(
                    "Hints for evaluation – e.g. the expected answer or a rating criterion (optional)",
                  )}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                />
                <p className="mt-1 text-xs text-slate-400">
                  {t(
                    "Each incoming answer is automatically assigned to a category during the run and grouped live in presentation mode.",
                  )}
                </p>

                <div className="mt-2">
                  <textarea
                    value={modelSolution}
                    onChange={(event) => setModelSolution(event.target.value)}
                    rows={2}
                    placeholder={t("Model solution (optional)")}
                    className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                  />
                  <p className="mt-1 text-xs text-slate-400">
                    {t("The AI scores answers against this reference.")}
                  </p>
                </div>

                <label className="mt-3 grid gap-1 text-sm text-slate-700 dark:text-slate-300">
                  {t("Scale")}
                  <select
                    value={evalScale}
                    onChange={(event) => {
                      const value = event.target.value;
                      setEvalScale(value);
                      const preset = EVAL_PRESETS.find((p) => p.value === value);
                      if (preset && preset.categories.length) {
                        setEvalCategories(preset.categories);
                      } else if (evalCategories.length < 2) {
                        // Switching to custom: seed two blank category inputs.
                        setEvalCategories(["", ""]);
                      }
                    }}
                    className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 focus:border-brand-600 focus:outline-none"
                  >
                    {EVAL_PRESETS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {t(p.label)}
                      </option>
                    ))}
                  </select>
                </label>

                {evalScale === "custom" && (
                  <div className="mt-2 grid gap-1.5">
                    {evalCategories.map((cat, i) => (
                      <div key={i} className="flex items-center gap-2">
                        <input
                          type="text"
                          value={cat}
                          onChange={(event) =>
                            setEvalCategories((cs) =>
                              cs.map((c, j) => (j === i ? event.target.value : c)),
                            )
                          }
                          placeholder={t("Category {{n}}", { n: i + 1 })}
                          className="w-56 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none focus:ring-1 focus:ring-brand-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                        />
                        {evalCategories.length > 2 && (
                          <button
                            type="button"
                            aria-label={t("Remove category {{n}}", { n: i + 1 })}
                            onClick={() =>
                              setEvalCategories((cs) => cs.filter((_, j) => j !== i))
                            }
                            className="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
                          >
                            <X aria-hidden className="h-4 w-4" />
                          </button>
                        )}
                      </div>
                    ))}
                    {evalCategories.length < 5 && (
                      <button
                        type="button"
                        onClick={() => setEvalCategories((cs) => [...cs, ""])}
                        className="justify-self-start rounded-lg border border-slate-300 px-3 py-1 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        + {t("Category")}
                      </button>
                    )}
                    <p className="text-xs text-slate-400">
                      {t("2–5 categories; the AI assigns each answer to one of them.")}
                    </p>
                  </div>
                )}

                <label className="mt-3 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={evalChart}
                    onChange={(event) => setEvalChart(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
                  />
                  {t("Show distribution as bar chart")}
                </label>

                <label className="mt-3 flex items-center gap-2 text-sm text-slate-700 dark:text-slate-300">
                  <input
                    type="checkbox"
                    checked={participantFeedback}
                    onChange={(event) => setParticipantFeedback(event.target.checked)}
                    className="h-4 w-4 rounded border-slate-300 dark:border-slate-700 accent-brand-600"
                  />
                  {t("Show each participant the evaluation of their own answer")}
                </label>
              </div>
            )}
          </AiAssistPanel>
        )}

        <Field label={t("Time limit")}>
          <div className="flex flex-wrap items-center gap-1.5">
            {TIME_PRESETS.map((preset) => {
              const active = timeLimit === preset.value;
              return (
                <button
                  key={preset.label}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setTimeLimit(preset.value)}
                  className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                    active
                      ? "border-brand-400 bg-brand-400 font-semibold text-slate-900"
                      : "border-slate-300 text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-900/60"
                  }`}
                >
                  {t(preset.label)}
                </button>
              );
            })}
            <span className="ml-1 text-sm text-slate-500 dark:text-slate-400">
              {t("or")}
            </span>
            <TextInput
              type="number"
              min={1}
              max={3600}
              value={timeLimit}
              onChange={(event) => setTimeLimit(event.target.value)}
              placeholder={t("e.g. 90")}
              aria-label={t("Time limit in seconds")}
              className="!w-28"
            />
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {t("Seconds")}
            </span>
          </div>
        </Field>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-2">
          <Button variant="primary" disabled={saving || invalid} onClick={() => void save()}>
            {saving ? t("Saving …") : t("Save")}
          </Button>
          <Button onClick={() => navigate(`/sets/${setId}`)}>{t("Cancel")}</Button>
        </div>

        {!isNew && (
        <div className="border-t border-slate-100 pt-4 dark:border-slate-800">
          {moveTargets === null ? (
            <button
              type="button"
              onClick={() => void openMove()}
              className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-brand-700 dark:text-slate-400 dark:hover:text-brand-300"
            >
              <FolderInput aria-hidden className="h-4 w-4" /> {t("Move to another question set …")}
            </button>
          ) : moveTargets.length === 0 ? (
            <p className="text-sm text-slate-400">
              {t("There is no other question set to move this to.")}
            </p>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t("Room")}>
                <select
                  value={moveRoom ?? undefined}
                  onChange={(event) => pickMoveRoom(Number(event.target.value))}
                  className="w-56 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                >
                  {moveRooms.map((room) => (
                    <option key={room.id} value={room.id}>
                      {room.title}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={t("Question set")}>
                <select
                  value={moveTarget ?? undefined}
                  onChange={(event) => setMoveTarget(Number(event.target.value))}
                  className="w-72 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                >
                  {moveTargets
                    .filter((entry) => entry.room === moveRoom)
                    .map((entry) => (
                      <option key={entry.id} value={entry.id}>
                        {localizedText(entry.title)}
                      </option>
                    ))}
                </select>
              </Field>
              <Button
                disabled={moveTarget === null}
                onClick={() => void handleMove()}
              >
                {t("Move")}
              </Button>
              <Button variant="ghost" onClick={() => setMoveTargets(null)}>
                {t("Cancel")}
              </Button>
              {moveTarget === null && (
                <p className="w-full text-sm text-slate-400">
                  {t("There is no other question set in this room.")}
                </p>
              )}
              {moveError && (
                <p className="w-full text-sm text-red-600">{moveError}</p>
              )}
            </div>
          )}
        </div>
        )}
      </div>
      )}
    </div>
  );
}
