// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Guided-tour step data (#onboarding). One concept per step. Titles/bodies are
 *  English source strings used directly as i18next keys (German is added in a
 *  later task). Targets are `data-tour` values (Task 3 anchors); a null target
 *  renders a centered, element-less popover. */

export type TourMode = "easy" | "pro";
export type StepKind = "info" | "action";

/** A milestone is resolved by the controller — route/present against the
 *  react-router location, element against the DOM. */
export type Milestone =
  | { type: "route"; pattern: string } // e.g. "/rooms/:id", "/sets/:id"
  | { type: "present" } // "/sets/:setId/present" reached
  | { type: "element"; anchor: string }; // a `[data-tour="<anchor>"]` element appears

/** Where the controller navigates before showing a guided step.
 *  - exampleSetPresent  → the resolved example set's /present view
 *  - exampleSetResults  → the resolved example set's /results view
 *  - roomsHome          → the rooms overview ("/")
 *  (The example targets fall back to roomsHome when no example set exists.) */
export type NavigateTarget = "exampleSetPresent" | "exampleSetResults" | "roomsHome";

export type TourPage = "rooms" | "room" | "set" | "question" | "present" | "results";

/** Exact route pattern per page (react-router `matchPath`, end=true). A tour
 *  can start in context on any of these; unknown routes start from "/". */
export const PAGE_PATTERNS: Record<TourPage, string> = {
  rooms: "/",
  room: "/rooms/:id",
  set: "/sets/:id",
  question: "/sets/:id/questions/:qid",
  present: "/sets/:id/present",
  results: "/sets/:id/results",
};

/** What "Weiter" does on an action step: achieve the step's outcome through the
 *  app's own APIs/navigation (never simulated clicks). The controller then
 *  re-syncs to the first step of the page it landed on. */
export type AutoPerform =
  | { kind: "createRoom" }
  | { kind: "createSet" }
  | { kind: "newQuestion" }
  | { kind: "navigate"; to: NavigateTarget };

export type PopoverSide = "top" | "right" | "bottom" | "left";

export interface TourStep {
  id: string;
  /** data-tour value to spotlight, or null for a centered modal-style step. */
  target: string | null;
  titleKey: string; // English source string (i18next key)
  bodyKey: string;
  kind: StepKind;
  /** action steps: advance when this milestone is met (Next stays disabled). */
  milestone?: Milestone;
  /** Only include this step in these modes (default: both). */
  modes?: TourMode[];
  /** Drop this step unless AI is enabled for the deployment/user — its target
   *  (e.g. the AI-generate shortcut) is only rendered when AI is on, so keeping
   *  it on an AI-off deployment would dead-end the tour at a missing element. */
  requiresAi?: boolean;
  /** Before showing, the controller navigates here (guided steps). */
  navigateTo?: NavigateTarget;
  /** The page this step lives on (context-aware start + post-autoPerform re-sync). */
  page?: TourPage;
  /** Action steps: what "Weiter" performs for the user. */
  autoPerform?: AutoPerform;
  /** Optional driver.js popover side, when the default would cover a control. */
  popoverSide?: PopoverSide;
}

// NOTE: the brief's step list references a `header.help` anchor for the "?" menu,
// but that anchor does not exist yet (it ships with the entry points in a later
// task). Its step is intentionally OMITTED here so no step targets a missing
// element; add it back alongside the "?" menu.

export const proTour: TourStep[] = [
  { id: "header.mode", page: "rooms", target: "header.mode", kind: "info",
    titleKey: "Simple or Expert", bodyKey: "Switch modes up here — Expert shows every option." },
  { id: "rooms.list", page: "rooms", target: "rooms.list", kind: "info",
    titleKey: "These are your rooms", bodyKey: "A room is a reusable space for a group or semester." },
  // Room creation: two coachmarks so the MANUAL path is guided (trigger → field);
  // both share autoPerform so "Weiter" on either creates an example room.
  { id: "rooms.new-room", page: "rooms", target: "rooms.new-room", kind: "action",
    milestone: { type: "element", anchor: "room.name" }, autoPerform: { kind: "createRoom" },
    titleKey: "Create your first room", bodyKey: "Click ‘New room’ to open the form." },
  { id: "room.create", page: "rooms", target: "room.name", kind: "action",
    milestone: { type: "route", pattern: "/rooms/:id" }, autoPerform: { kind: "createRoom" },
    titleKey: "Give it a title and save", bodyKey: "Type a title above, then click ‘Create’." },
  { id: "room.new-set", page: "room", target: "room.new-set", kind: "action",
    milestone: { type: "element", anchor: "set.title" }, autoPerform: { kind: "createSet" },
    titleKey: "Content lives in sets",
    bodyKey: "Each set has a type — Live poll (presenter-driven), Self-paced quiz (own pace in class) or Self-check (a standing self-study link). Click ‘New set’ to start one." },
  { id: "set.create", page: "room", target: "set.title", kind: "action",
    milestone: { type: "route", pattern: "/sets/:id" }, autoPerform: { kind: "createSet" },
    titleKey: "Give your set a title and save", bodyKey: "Pick a type, enter a title, then click ‘Save’." },
  { id: "set.editor", page: "set", target: "set.questions", kind: "info",
    titleKey: "The set editor", bodyKey: "This is the set editor: your questions live here, grouped into sections." },
  { id: "set.ai-generate", page: "set", target: "set.ai-generate", kind: "info", modes: ["pro"], requiresAi: true,
    titleKey: "Shortcuts", bodyKey: "Generate draft questions from your slides with AI, or copy from another set." },
  { id: "set.add-question", page: "set", target: "set.add-question", kind: "action", popoverSide: "left",
    milestone: { type: "route", pattern: "/sets/:id/questions/:qid" }, autoPerform: { kind: "newQuestion" },
    titleKey: "Add a question", bodyKey: "Click ‘New question’ and pick a type to open the editor." },
  { id: "question.editor", page: "question", target: "question.editor", kind: "info",
    titleKey: "The question editor",
    bodyKey: "Write the question text and answer options here; drag in images if you like. Save when you’re done." },
  { id: "question.lang-tabs", page: "question", target: "question.lang-tabs", kind: "info", modes: ["pro"],
    titleKey: "Author in two languages", bodyKey: "Rich text, options and images — with German/English tabs." },
  { id: "present.controls", page: "present", target: "present.controls", kind: "info",
    navigateTo: "exampleSetPresent", titleKey: "Now present",
    bodyKey: "We’ll present the ready-made Example room (every question type). Start and stop questions, and show the QR / join code." },
  { id: "results.export", page: "results", target: "results.view", kind: "info",
    navigateTo: "exampleSetResults", titleKey: "Results",
    bodyKey: "After a run, results are stored here — export CSV or delete a run." },
  { id: "final", target: null, kind: "info", navigateTo: "roomsHome",
    titleKey: "You’ve got it 🎉",
    bodyKey: "You know the whole loop. Anything the tour created is named ‘Rundgang…’ — keep or delete it. Restart this tour anytime from the ? menu." },
];

export const easyTour: TourStep[] = proTour
  .filter((s) => !s.modes || s.modes.includes("easy"))
  .filter((s) => !["set.ai-generate", "question.lang-tabs"].includes(s.id));

/** Steps for a mode, minus any that can't be shown for this user. `aiEnabled`
 *  gates `requiresAi` steps so a normal run never pauses on a missing target. */
export const tourFor = (
  mode: TourMode,
  opts: { aiEnabled?: boolean } = {},
): TourStep[] => {
  const base = mode === "easy" ? easyTour : proTour;
  return opts.aiEnabled ? base : base.filter((s) => !s.requiresAi);
};
