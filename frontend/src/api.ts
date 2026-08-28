// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import type { LocalizedText } from "@basicbar/ui";
import type { SetType } from "./setTypes";

/** Backend base URL. Defaults to "" (same-origin, relative URLs) — production
 * serves the SPA and API from one origin behind Caddy. Dev overrides this via
 * VITE_API_BASE_URL since the dev frontend and backend run cross-origin. */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export interface Whoami {
  authenticated: boolean;
  username?: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  is_staff?: boolean;
  easy_mode?: boolean;
  language?: string;
  csrf_token?: string;
  ai_enabled?: boolean;
  /** Content-i18n (#33 MR2): the deployment's canonical authoring language
   * and whether machine-translation pre-fill (LibreTranslate) is on. */
  content_default_language: string;
  content_translation_enabled: boolean;
}

export interface Room {
  id: number;
  code: string;
  title: LocalizedText;
  description: LocalizedText;
  show_logo_in_presentation: boolean;
  show_qr_in_presentation: boolean;
  show_code_in_presentation: boolean;
  presentation_corner: PresentationCorner;
  /** Sanitized HTML shown to participants once the vote is finished (#24). */
  closing_info: LocalizedText;
  is_favorite: boolean;
  is_archived: boolean;
  last_used_at: string | null;
  question_set_count: number;
  created_at: string;
  updated_at: string;
  created_by_name: string;
  updated_by_name: string;
  /** The Besitzer's display name; who may delete or hand over the room (#25). */
  owner_name: string;
  /** True when the current user is the room's Besitzer. */
  is_owner: boolean;
  /** True when the current user is a member (owner or added) of the room. */
  is_member: boolean;
  /** True when the room was created from an LMS via an LTI launch (M4). */
  is_lti: boolean;
  /** Number of owners — >1 means the room is shared. */
  owner_count: number;
}

export type PresentationCorner =
  | "top-left"
  | "top-right"
  | "bottom-left"
  | "bottom-right";

export type RevealAnswers = "immediately" | "after_close" | "never";

export interface QuestionSet {
  id: number;
  room: number;
  room_title: string;
  title: LocalizedText;
  description: LocalizedText;
  type: SetType;
  reveal_answers: RevealAnswers;
  open_on_show: boolean;
  show_results_to_participants: boolean;
  share_token: string | null;
  license: string;
  license_holder: string;
  question_count: number;
  has_results: boolean;
  created_at: string;
  updated_at: string;
}

export interface RoomOwner {
  id: number;
  username: string;
  name: string;
  is_self: boolean;
  /** True for the room's Besitzer (may delete / hand over). */
  is_owner: boolean;
}

/** A person the user already shares a room with — a re-add suggestion (#55). */
export interface Collaborator {
  id: number;
  username: string;
  name: string;
}

export interface SharedSet {
  title: string;
  description: string;
  license: string;
  license_holder: string;
  owners: string[];
  question_count: number;
  questions: { kind: QuestionKind; text: string }[];
}

export type QuestionKind =
  | "single_choice"
  | "multiple_choice"
  | "word_cloud"
  | "likert"
  | "open_text"
  | "priorities"
  | "ordering";

export interface AnswerOption {
  id?: number;
  text: LocalizedText;
  /** Relative /media/ URL of an optional option image (v2). */
  image?: string;
  is_correct: boolean;
  is_abstention?: boolean;
}

export interface Question {
  id: number;
  question_set: number;
  section: number | null;
  kind: QuestionKind;
  text: LocalizedText;
  shuffle_options: boolean;
  /** single_choice only: created via the binary Ja/Nein preset — the editor
   *  shows the Ja/Nein · Wahr/Falsch template quick-fill above two options (#79). */
  binary_choice: boolean;
  time_limit: number | null;
  position: number;
  options: AnswerOption[];
  /** open_text only: classify each answer live during the run. */
  ai_evaluate: boolean;
  evaluation_hint: string;
  /** open_text only: the scale the AI sorts answers into (2–5 labels). */
  evaluation_categories: string[];
  /** open_text only: show the category counts as a bar chart. */
  evaluation_chart: boolean;
  /** open_text only: optional model solution (Musterlösung) fed to the AI as
   *  the reference the answers are scored against. */
  model_solution: string;
  /** open_text only: also show each participant the AI verdict of their own
   *  answer on their device. */
  participant_feedback: boolean;
  /** word_cloud only: let each participant submit several terms (#14). */
  allow_multiple: boolean;
  /** word_cloud only: show the cloud on the beamer while the vote is open (#30). */
  wordcloud_live: boolean;
  /** word_cloud only: enable the AI cleanup/grouping views in the presenter. */
  wordcloud_ai_enabled: boolean;
  /** word_cloud only: optional AI grouping criteria (empty = auto themes). */
  wordcloud_grouping: string;
  /** word_cloud + allow_multiple: max terms per participant (0 = unlimited, #76). */
  wordcloud_max_answers: number;
  /** Per-question reveal override; "inherit" uses the set default (#28). */
  reveal_answers: "inherit" | RevealAnswers;
  /** Before/after pair (#54): the before-question this one mirrors (null if
   *  standalone); the linked after-question id; and a convenience flag. */
  before_question: number | null;
  after_question: number | null;
  is_after: boolean;
  created_at: string;
  updated_at: string;
  /** Read-only: per-field language codes whose translation is outdated
   *  relative to the canonical language (#91), e.g. `{"text": ["en"]}`. */
  translation_stale?: Record<string, string[]>;
  /** Write-only: field names to record as back-in-sync using the values
   *  saved in this request (#91). */
  synced_fields?: string[];
}

/** A draft question proposed by the AI from a document (not yet saved). */
export interface GeneratedQuestion {
  kind: "single_choice" | "multiple_choice" | "open_text";
  text: string;
  /** True/False drafts come back as single_choice + this flag (#79). */
  binary_choice?: boolean;
  options: { text: string; is_correct: boolean }[];
  /** open_text only: AI-generated reference answer to score against. */
  model_solution?: string;
}

/** Live free-text evaluation summary (presenter + stored results). The
 *  ``verdict`` is a category label from the question's chosen scale; groups
 *  come in the configured order. */
export interface FreeTextEvalSummary {
  groups: {
    verdict: string;
    count: number;
    items: { text: string; count: number }[];
  }[];
  categories: string[];
  chart: boolean;
  pending: number;
  total: number;
}

export interface Section {
  id: number;
  question_set: number;
  title: LocalizedText;
  position: number;
}

/** Diverging Likert aggregation (backend results.likert_summary). Percentages
 * are over the scale responses only; abstentions are reported separately. */
export interface LikertStep {
  id: number;
  text: LocalizedText;
  count: number;
  pct: number;
  polarity: "disagree" | "neutral" | "agree";
}

export interface LikertSummary {
  scale_total: number;
  abstentions: number;
  agree: number;
  agree_pct: number;
  neutral: number;
  neutral_pct: number;
  disagree: number;
  disagree_pct: number;
  /** Centre-line position as a percentage (0–100) of the scale width. */
  divider: number;
  steps: LikertStep[];
}

/** Start-page keyword search across the user's rooms, sets and questions. */
export interface SearchResults {
  rooms: { id: number; code: string; title: string }[];
  sets: { id: number; title: string; room: number; room_title: string }[];
  questions: {
    id: number;
    text: string;
    kind: QuestionKind;
    question_set: number;
    set_title: string;
    room: number;
    room_title: string;
  }[];
}

/** Admin-configurable site content (common app). */
export interface SitePublic {
  landing_text: LocalizedText;
  logo: string | null;
  /** AI privacy notice (#80): operator-authored, translatable; shown as a
   * one-time dismissible banner while AI is available. Empty = no banner. */
  ai_notice: LocalizedText;
  /** "More info" link: an internal content page (slug) takes precedence over
   * the external URL. */
  ai_notice_page: string | null;
  ai_notice_url: string;
}

export interface FooterPageLink {
  slug: string;
  title: LocalizedText;
}

export interface PageDetail {
  slug: string;
  title: LocalizedText;
  body: LocalizedText;
  updated_at: string;
}

export interface DataCollectionItem {
  category: string;
  data: string;
  purpose: string;
  legal_basis: string;
  retention: string;
}

export interface DataCollection {
  collected: DataCollectionItem[];
  not_collected: string[];
}

export interface ManageSite {
  landing_text: LocalizedText;
  /** Sanitized HTML shown to participants on every room's closing screen (#24). */
  closing_info: LocalizedText;
  logo: string | null;
  ai_notice: LocalizedText;
  ai_notice_page: string | null;
  ai_notice_url: string;
}

export interface ManagePage {
  id: number;
  slug: string;
  title: LocalizedText;
  body: LocalizedText;
  is_published: boolean;
  show_in_footer: boolean;
  footer_order: number;
  updated_at: string;
}

export type ManagePageInput = Omit<ManagePage, "id" | "footer_order" | "updated_at">;

/** LTI 1.3 platform registration (M4): one row per LMS instance/deployment
 * that may launch into abstimmbar. Staff-only (accounts.IsAdmin). */
export interface LtiPlatform {
  id: number;
  name: string;
  issuer: string;
  client_id: string;
  auth_login_url: string;
  auth_token_url: string;
  key_set_url: string;
  deployment_ids: string[];
  /** If true, an LTI launch may link to an existing account by e-mail —
   * the LMS becomes the authority for that account match. */
  link_by_email: boolean;
  is_active: boolean;
}

/** This deployment's endpoints, to be entered in the LMS's tool registration. */
export interface LtiToolInfo {
  login_url: string;
  launch_url: string;
  jwks_url: string;
  icon_url: string;
}

interface Paginated<T> {
  count: number;
  results: T[];
}

/** CSRF token. `whoami` returns an authoritative token in its body (see the
 * backend note); we prefer it because reading the cookie from JS is
 * unreliable cross-origin in dev. Falls back to the cookie. */
let serverCsrfToken = "";

function csrfToken(): string {
  if (serverCsrfToken) return serverCsrfToken;
  return document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/)?.[1] ?? "";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    headers: {
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      "X-CSRFToken": csrfToken(),
      ...init.headers,
    },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      detail = JSON.stringify(await response.json());
    } catch {
      /* keep status code */
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  whoami: async () => {
    const who = await request<Whoami>("/api/whoami/");
    if (who.csrf_token) serverCsrfToken = who.csrf_token;
    return who;
  },

  // Remember the signed-in user's UI language (best-effort).
  setLanguage: (language: string) =>
    request<{ language: string }>("/api/whoami/language/", {
      method: "POST",
      body: JSON.stringify({ language }),
    }),

  setMode: (easyMode: boolean) =>
    request<{ easy_mode: boolean }>("/api/whoami/mode/", {
      method: "POST",
      body: JSON.stringify({ easy_mode: easyMode }),
    }),

  // --- site content (public reads) ---
  getSite: () => request<SitePublic>("/api/site/"),
  getFooterPages: () => request<FooterPageLink[]>("/api/pages/"),
  getPage: (slug: string) => request<PageDetail>(`/api/pages/${slug}/`),
  getDataCollection: () => request<DataCollection>("/api/data-collection/"),

  // --- site content (staff management) ---
  getManageSite: () => request<ManageSite>("/api/manage/site/"),
  updateSite: (patch: {
    landing_text: LocalizedText;
    closing_info: LocalizedText;
    ai_notice: LocalizedText;
    ai_notice_page: string | null;
    ai_notice_url: string;
  }) =>
    request<ManageSite>("/api/manage/site/", {
      method: "PUT",
      body: JSON.stringify(patch),
    }),
  uploadLogo: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<ManageSite>("/api/manage/site/logo/", { method: "POST", body });
  },
  deleteLogo: () => request<void>("/api/manage/site/logo/", { method: "DELETE" }),
  listManagePages: () => request<ManagePage[]>("/api/manage/pages/"),
  createPage: (data: ManagePageInput) =>
    request<ManagePage>("/api/manage/pages/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updatePage: (id: number, data: Partial<ManagePageInput>) =>
    request<ManagePage>(`/api/manage/pages/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deletePage: (id: number) =>
    request<void>(`/api/manage/pages/${id}/`, { method: "DELETE" }),
  reorderPages: (order: number[]) =>
    request<void>("/api/manage/pages/reorder/", {
      method: "POST",
      body: JSON.stringify({ order }),
    }),

  // --- LTI 1.3 platforms (M4, staff management) ---
  listLtiPlatforms: () =>
    request<Paginated<LtiPlatform>>("/api/lti/platforms/?page_size=1000"),
  createLtiPlatform: (data: Omit<LtiPlatform, "id">) =>
    request<LtiPlatform>("/api/lti/platforms/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateLtiPlatform: (id: number, data: Partial<LtiPlatform>) =>
    request<LtiPlatform>(`/api/lti/platforms/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteLtiPlatform: (id: number) =>
    request<void>(`/api/lti/platforms/${id}/`, { method: "DELETE" }),
  getLtiToolInfo: () => request<LtiToolInfo>("/api/lti/tool-info/"),

  search: (query: string) =>
    request<SearchResults>(`/api/search/?q=${encodeURIComponent(query)}`),

  // The overview sorts + paginates client-side (favorites on top), so fetch
  // the full set in one go. `all` (staff only; ignored otherwise) requests
  // every room, not just the caller's own, for admin visibility.
  listRooms: (all?: boolean) =>
    request<Paginated<Room>>(`/api/rooms/?page_size=1000${all ? "&all=1" : ""}`),
  toggleRoomFavorite: (id: number, on: boolean) =>
    request<Room>(`/api/rooms/${id}/favorite/`, { method: on ? "POST" : "DELETE" }),
  listArchivedRooms: () =>
    request<Paginated<Room>>("/api/rooms/?archived=1&page_size=1000"),
  toggleRoomArchive: (id: number, on: boolean) =>
    request<Room>(`/api/rooms/${id}/archive/`, { method: on ? "POST" : "DELETE" }),
  getRoom: (id: number) => request<Room>(`/api/rooms/${id}/`),
  createRoom: (data: {
    title: LocalizedText;
    description?: LocalizedText;
    show_logo_in_presentation?: boolean;
    show_qr_in_presentation?: boolean;
    show_code_in_presentation?: boolean;
    presentation_corner?: PresentationCorner;
  }) =>
    request<Room>("/api/rooms/", { method: "POST", body: JSON.stringify(data) }),
  updateRoom: (id: number, data: Partial<Room>) =>
    request<Room>(`/api/rooms/${id}/`, { method: "PATCH", body: JSON.stringify(data) }),
  deleteRoom: (id: number) =>
    request<void>(`/api/rooms/${id}/`, { method: "DELETE" }),
  listRoomOwners: (id: number) =>
    request<{ owners: RoomOwner[] }>(`/api/rooms/${id}/owners/`),
  /** People I already share a room with, most-frequent first (#55). */
  listCollaborators: () =>
    request<{ collaborators: Collaborator[] }>(`/api/rooms/collaborators/`),
  addRoomOwner: (id: number, user: string) =>
    request<{ owners: RoomOwner[] }>(`/api/rooms/${id}/owners/`, {
      method: "POST",
      body: JSON.stringify({ user }),
    }),
  removeRoomOwner: (id: number, userId: number) =>
    request<{ owners: RoomOwner[] }>(`/api/rooms/${id}/owners/${userId}/`, {
      method: "DELETE",
    }),
  /** Hand the room over to another owner (#26). */
  transferRoomOwner: (id: number, userId: number) =>
    request<{ owners: RoomOwner[] }>(`/api/rooms/${id}/transfer-owner/`, {
      method: "POST",
      body: JSON.stringify({ user: userId }),
    }),
  /** Leave a room shared with me (#26). */
  leaveRoom: (id: number) =>
    request<void>(`/api/rooms/${id}/leave/`, { method: "POST" }),

  listQuestionSets: (roomId: number, search = "") =>
    request<Paginated<QuestionSet>>(
      `/api/question-sets/?room=${roomId}&search=${encodeURIComponent(search)}`,
    ),
  duplicateQuestionSet: (id: number, data: { room?: number; title?: string }) =>
    request<QuestionSet>(`/api/question-sets/${id}/duplicate/`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  importQuestionSet: (roomId: number, data: unknown) =>
    request<QuestionSet>(`/api/rooms/${roomId}/import-set/`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getQuestionSet: (id: number) => request<QuestionSet>(`/api/question-sets/${id}/`),
  createQuestionSet: (
    data: {
      room: number;
      title?: LocalizedText;
      description?: LocalizedText;
      type?: SetType;
      reveal_answers?: RevealAnswers;
      open_on_show?: boolean;
      show_results_to_participants?: boolean;
    },
  ) =>
    request<QuestionSet>("/api/question-sets/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  updateQuestionSet: (id: number, data: Partial<QuestionSet>) =>
    request<QuestionSet>(`/api/question-sets/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteQuestionSet: (id: number) =>
    request<void>(`/api/question-sets/${id}/`, { method: "DELETE" }),
  reorderQuestions: (setId: number, questionIds: number[]) =>
    request<void>(`/api/question-sets/${setId}/reorder/`, {
      method: "POST",
      body: JSON.stringify({ question_ids: questionIds }),
    }),

  listSections: (setId: number) =>
    request<Paginated<Section>>(`/api/sections/?question_set=${setId}`),
  createSection: (setId: number, title: LocalizedText = "") =>
    request<Section>("/api/sections/", {
      method: "POST",
      body: JSON.stringify({ question_set: setId, title }),
    }),
  updateSection: (id: number, title: LocalizedText) =>
    request<Section>(`/api/sections/${id}/`, {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }),
  deleteSection: (id: number) =>
    request<void>(`/api/sections/${id}/`, { method: "DELETE" }),
  /** Persist the inline outline: sections + questions in one order.
   * Each item is {type: "section"|"question", id}. Section membership
   * follows the nearest header above each question. */
  reorderOutline: (
    setId: number,
    items: { type: "section" | "question"; id: number }[],
  ) =>
    request<void>(`/api/question-sets/${setId}/reorder-outline/`, {
      method: "POST",
      body: JSON.stringify({ items }),
    }),

  listQuestions: (setId: number) =>
    request<Paginated<Question>>(`/api/questions/?question_set=${setId}`),
  getQuestion: (id: number) => request<Question>(`/api/questions/${id}/`),
  createQuestion: (data: Omit<Partial<Question>, "id">) =>
    request<Question>("/api/questions/", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Generate draft questions from an uploaded document or pasted text. */
  aiGenerateQuestions: (
    setId: number,
    opts: {
      file?: File;
      text?: string;
      count: number;
      kinds: string[];
      level: string;
      guidance?: string;
    },
  ) => {
    const body = new FormData();
    if (opts.file) body.append("file", opts.file);
    if (opts.text) body.append("text", opts.text);
    body.append("count", String(opts.count));
    body.append("kinds", opts.kinds.join(","));
    body.append("level", opts.level);
    if (opts.guidance?.trim()) body.append("guidance", opts.guidance.trim());
    return request<{ questions: GeneratedQuestion[]; notice?: string }>(
      `/api/question-sets/${setId}/ai-generate/`,
      { method: "POST", body },
    );
  },
  updateQuestion: (id: number, data: Partial<Question>) =>
    request<Question>(`/api/questions/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(data),
    }),
  deleteQuestion: (id: number) =>
    request<void>(`/api/questions/${id}/`, { method: "DELETE" }),
  /** Create a locked after-question mirroring this one (#54). */
  addAfterQuestion: (id: number) =>
    request<Question>(`/api/questions/${id}/add-after/`, { method: "POST" }),
  moveQuestion: (id: number, questionSet: number) =>
    request<{ status: string; question_set: number }>(
      `/api/questions/${id}/move/`,
      { method: "POST", body: JSON.stringify({ question_set: questionSet }) },
    ),
  /** Copy questions (from any set the user owns) into set `setId`, appended
   * at the end in the given order (#87). */
  copyQuestions: (setId: number, questionIds: number[]) =>
    request<{ copied: number }>(`/api/question-sets/${setId}/copy-questions/`, {
      method: "POST",
      body: JSON.stringify({ question_ids: questionIds }),
    }),
  aiDistractors: (
    id: number,
    payload: { text: string; options: { text: string; is_correct: boolean }[]; count?: number },
  ) =>
    request<{ distractors: string[] }>(`/api/questions/${id}/ai-distractors/`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  aiRephrase: (id: number, text: string) =>
    request<{ variants: string[] }>(`/api/questions/${id}/ai-rephrase/`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  /** Same as `aiDistractors`, but for a question still being created (no
   * saved id yet) — scoped to the question set instead. */
  aiDistractorsForSet: (
    setId: number,
    payload: { text: string; options: { text: string; is_correct: boolean }[]; count?: number },
  ) =>
    request<{ distractors: string[] }>(
      `/api/question-sets/${setId}/ai-distractors/`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  /** Same as `aiRephrase`, but for a question still being created (no saved
   * id yet) — scoped to the question set instead. */
  aiRephraseForSet: (setId: number, text: string) =>
    request<{ variants: string[] }>(
      `/api/question-sets/${setId}/ai-rephrase/`,
      { method: "POST", body: JSON.stringify({ text }) },
    ),
  /** All of the user's sets (move target picker) — no room filter. */
  listAllQuestionSets: () =>
    request<Paginated<QuestionSet>>("/api/question-sets/"),

  shareQuestionSet: (id: number, enabled: boolean) =>
    request<{ share_token: string | null }>(`/api/question-sets/${id}/share/`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  getSharedSet: (token: string) => request<SharedSet>(`/api/shared/${token}/`),
  copySharedSet: (token: string, room: number) =>
    request<{ id: number; room: number; title: string }>(
      `/api/shared/${token}/copy/`,
      { method: "POST", body: JSON.stringify({ room }) },
    ),

  uploadImage: (file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ id: number; url: string }>("/api/images/", {
      method: "POST",
      body,
    });
  },

  /** Optional machine-translation pre-fill (LibreTranslate, #33 MR2 Phase 4);
   * 503 if the backend has no provider configured (checked via
   * `isTranslationEnabled()` before offering this in the UI). */
  translate: (text: string, source: string, target: string, format: "text" | "html" = "text") =>
    request<{ translated: string }>("/api/translate/", {
      method: "POST",
      body: JSON.stringify({ text, source, target, format }),
    }),
};

// --- live / presenter -------------------------------------------------------

export interface LiveOption {
  id: number;
  text: LocalizedText;
  image?: string;
  is_correct?: boolean;
  is_abstention?: boolean;
  count?: number;
  /** Recording mode (#53): the on-site vs recording-viewer split. */
  onsite?: number;
  recording?: number;
}

export interface LiveState {
  room: {
    code: string;
    title: LocalizedText;
    show_logo?: boolean;
    show_qr?: boolean;
    show_code?: boolean;
    corner?: PresentationCorner;
  };
  phase: "idle" | "lobby" | "preview" | "open" | "closed" | "results" | "finished";
  mode?: "live" | "self_paced";
  set_title?: LocalizedText;
  run_id?: number;
  /** Self-paced dashboard: per-question vote counts. */
  progress?: { id: number; text: LocalizedText; votes: number }[];
  votes_total?: number;
  reveal_answers?: RevealAnswers;
  revealed?: boolean;
  ends_at?: string;
  participants?: number;
  /** Recording mode (#53): the run's deep-link token (present when recording
   *  is on), so the beamer can show the per-question QR. */
  recording_token?: string;
  votes?: number;
  question?: {
    id: number;
    kind: QuestionKind;
    text: LocalizedText;
    multiple: boolean;
    allow_multiple?: boolean;
    wordcloud_live?: boolean;
    wordcloud_ai_enabled?: boolean;
    options: LiveOption[];
  };
  results?: LiveOption[];
  /** Priorities (#58): per-option avg/min/max in the presenter snapshot. */
  priorities?: PriorityStat[];
  /** Ordering (#72): per-item correct-position rate in the presenter snapshot. */
  ordering?: OrderingResults;
  likert?: LikertSummary;
  /** Before/after pair (#54): for an after-question, the before-question's
   *  aggregates from the same run, so the beamer shows the comparison. */
  before?: {
    votes: number;
    results?: LiveOption[];
    likert?: LikertSummary;
  };
  words?: { text: string; count: number }[];
  evaluation?: FreeTextEvalSummary;
  /** Live AI word-cloud views (consolidated + grouped), while the presenter
   *  shows an AI view (#Wortwolke-KI). */
  wordcloud_ai?: WordCloudAI;
}

export interface WordCloudWord {
  text: string;
  count: number;
  variants: string[];
}

export interface WordCloudAI {
  merged: WordCloudWord[];
  clusters: { label: string; count: number; words: WordCloudWord[] }[];
  pending: boolean;
}

/** Priorities question aggregation (#58): per-option average/min/max points
 *  over all submissions, plus the number of submissions scoring it. */
export interface PriorityStat {
  id: number;
  text: LocalizedText;
  image?: string;
  avg: number;
  min: number;
  max: number;
  n: number;
}

/** Ordering question aggregation (#72): per-item correct-position rate over
 *  all submissions, plus the full-sequence-correct rate. */
export interface OrderingItem {
  id: number;
  text: LocalizedText;
  image?: string;
  correct_position: number;
  correct_rate: number;
  n: number;
}

export interface OrderingLink {
  from: number;
  to: number;
  rate: number;
}

export interface OrderingChain {
  start: number;
  end: number;
  rate: number;
}

export interface OrderingResults {
  items: OrderingItem[];
  full_correct_rate: number;
  n: number;
  links: OrderingLink[];
  chains: OrderingChain[];
}

export interface RunResults {
  run: number;
  phase: string;
  created_at: string;
  first_opened_at: string | null;
  ended_at: string | null;
  votes_total: number;
  /** Recording mode (#53): total async votes in the run; the split is shown
   *  only when > 0. */
  recording_votes: number;
  questions: {
    id: number;
    position: number;
    kind: QuestionKind;
    text: LocalizedText;
    votes: number;
    /** Recording mode (#53): how many of this question's votes are async. */
    votes_recording: number;
    /** Before/after pair (#54): the before-question id this one mirrors. */
    before_question: number | null;
    options?: LiveOption[];
    likert?: LikertSummary;
    words?: { text: string; count: number; onsite?: number; recording?: number }[];
    evaluation?: FreeTextEvalSummary;
    /** Priorities (#58): per-option avg/min/max/n. */
    priorities?: PriorityStat[];
    ordering?: OrderingResults;
  }[];
}

export interface WordCloudCluster {
  label: string;
  count: number;
  words: { text: string; count: number; variants: string[] }[];
}

export interface WordCloudOptimization {
  clusters: WordCloudCluster[];
  merged: { text: string; count: number; variants: string[] }[];
}

export interface FreeTextEvaluation {
  groups: {
    verdict: string;
    count: number;
    items: { text: string; count: number; note: string }[];
  }[];
  categories?: string[];
  chart?: boolean;
}

export const results = {
  list: (setId: number) =>
    request<{ results: RunResults[] }>(`/api/question-sets/${setId}/results/`),
  /** Optional AI short report (sanitized HTML) summarising one run's results. */
  summarize: (runId: number) =>
    request<{ report: string }>(`/api/runs/${runId}/ai-summary/`, {
      method: "POST",
    }),
  /** Optional AI cleanup of a word-cloud result (merge variants, cluster). */
  optimizeWordCloud: (runId: number, questionId: number) =>
    request<WordCloudOptimization>(
      `/api/runs/${runId}/questions/${questionId}/ai-wordcloud/`,
      { method: "POST" },
    ),
  /** Optional AI evaluation of free-text answers (korrekt/unklar/falsch). */
  evaluateFreeText: (runId: number, questionId: number, reference: string) =>
    request<FreeTextEvaluation>(
      `/api/runs/${runId}/questions/${questionId}/ai-freetext/`,
      { method: "POST", body: JSON.stringify({ reference }) },
    ),
  deleteRun: (runId: number) =>
    request<void>(`/api/runs/${runId}/`, { method: "DELETE" }),
  deleteAll: (setId: number) =>
    request<{ status: string }>(`/api/question-sets/${setId}/delete-results/`, {
      method: "POST",
    }),
  /** Archive current results and prepare a fresh run (#27). */
  archive: (setId: number) =>
    request<{ run: number }>(`/api/question-sets/${setId}/archive-results/`, {
      method: "POST",
    }),
  csvUrl: (setId: number, runId?: number) =>
    `${API_BASE_URL}/api/question-sets/${setId}/results.csv` +
    (runId ? `?run=${runId}` : ""),
  exportUrl: (setId: number) => `${API_BASE_URL}/api/question-sets/${setId}/export/`,
};

export const live = {
  status: (setId: number) =>
    request<{
      active_run: number | null;
      has_votes: boolean;
      active_run_has_votes: boolean;
      recently_started: boolean;
      room_code: string;
    }>(`/api/question-sets/${setId}/live-status/`),
  startRun: (
    setId: number,
    existing?: "continue" | "delete" | "archive",
    mode: "live" | "self_paced" = "live",
    recording = false,
  ) =>
    request<{ run: number; room_code: string; recording_token: string | null }>(
      `/api/question-sets/${setId}/start-run/`,
      {
        method: "POST",
        body: JSON.stringify({
          mode,
          ...(existing === undefined ? {} : { existing }),
          ...(recording ? { recording: true } : {}),
        }),
      },
    ),
  control: (
    runId: number,
    data: { phase?: string; question?: number | null; reveal?: boolean; recording?: boolean },
  ) =>
    request<{ status: string; phase?: string; recording_token?: string }>(
      `/api/runs/${runId}/control/`,
      { method: "POST", body: JSON.stringify(data) },
    ),
  /** Toggle the live AI word-cloud view (consolidate/group) for a question. */
  wordcloudAi: (runId: number, questionId: number, active: boolean) =>
    request<{ status: string; active: boolean }>(
      `/api/runs/${runId}/wordcloud-ai/`,
      { method: "POST", body: JSON.stringify({ question: questionId, active }) },
    ),
  streamUrl: (code: string) =>
    `${API_BASE_URL}/api/live/rooms/${code}/stream/?role=presenter`,
  participantUrl: (code: string) => `${API_BASE_URL}/p/${code}/`,
  /** Just the server name participants type into their browser (no /p/<code>
   *  path) — for the beamer join hint, where the room code is shown separately.
   *  Resolved against the current page so it works same-origin (prod) and
   *  cross-origin (dev). */
  participantHost: (code: string) =>
    new URL(live.participantUrl(code), window.location.href).host,
  qrUrl: (code: string) => `${API_BASE_URL}/p/${code}/qr.png`,
  /** Recording mode (#53): per-question deep-link QR for the beamer. */
  recordingQrUrl: (token: string, questionId: number) =>
    `${API_BASE_URL}/r/${token}/qr.png?q=${questionId}`,
};

export const loginUrl = `${API_BASE_URL}/oidc/authenticate/`;
/** Silent SSO (prompt=none): logs the visitor in automatically if the IdP
 * already has a session, otherwise bounces back to "/?sso=failed" (#19). */
export const silentLoginUrl = `${API_BASE_URL}/oidc/silent/`;
export const logoutUrl = `${API_BASE_URL}/oidc/logout-redirect/`;
