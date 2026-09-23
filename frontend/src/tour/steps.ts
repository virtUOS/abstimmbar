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
}

// NOTE: the brief's step list references a `header.help` anchor for the "?" menu,
// but that anchor does not exist yet (it ships with the entry points in a later
// task). Its step is intentionally OMITTED here so no step targets a missing
// element; add it back alongside the "?" menu.

export const proTour: TourStep[] = [
  {
    id: "header.mode",
    target: "header.mode",
    kind: "info",
    titleKey: "Simple or Expert",
    bodyKey: "Switch modes up here — Expert shows every option.",
  },
  {
    id: "rooms.list",
    target: "rooms.list",
    kind: "info",
    titleKey: "These are your rooms",
    bodyKey: "A room is a reusable space for a group or semester.",
  },
  // Room creation is a multi-part task, so it's split across two coachmarks:
  // clicking ‘New room’ replaces the button with an inline form (advance on the
  // form's submit button appearing), then the form is saved (advance on route).
  {
    id: "rooms.new-room",
    target: "rooms.new-room",
    kind: "action",
    milestone: { type: "element", anchor: "room.create" },
    titleKey: "Create your first room",
    bodyKey: "Click ‘New room’ to open the form.",
  },
  {
    id: "room.create",
    target: "room.create",
    kind: "action",
    milestone: { type: "route", pattern: "/rooms/:id" },
    titleKey: "Give it a title and save",
    bodyKey: "Type a title above, then click ‘Create’.",
  },
  {
    id: "room.new-set",
    target: "room.new-set",
    kind: "info",
    titleKey: "Content lives in sets",
    bodyKey:
      "Each set has a type that fixes how it runs: Live poll (presenter-driven), Self-paced quiz (own pace in class) or Self-check (a standing self-study link).",
  },
  {
    id: "room.new-set.action",
    target: "room.new-set",
    kind: "action",
    milestone: { type: "route", pattern: "/sets/:id" },
    titleKey: "Add a set",
    bodyKey: "Create a set — pick ‘Live poll’ to follow along.",
  },
  {
    id: "set.editor",
    target: "set.add-question",
    kind: "info",
    titleKey: "The set editor",
    bodyKey: "Add questions and group them into sections.",
  },
  {
    id: "set.ai-generate",
    target: "set.ai-generate",
    kind: "info",
    modes: ["pro"],
    requiresAi: true, // anchor only mounts when AI is enabled (SetPage aiVisible)
    titleKey: "Shortcuts",
    bodyKey: "Generate draft questions from your slides with AI, or copy from another set.",
  },
  {
    id: "set.add-question",
    target: "set.add-question",
    kind: "action",
    milestone: { type: "route", pattern: "/sets/:id/questions/:qid" },
    titleKey: "Add a question",
    bodyKey: "Open the question editor to add your first one.",
  },
  {
    id: "question.lang-tabs",
    target: "question.lang-tabs",
    kind: "info",
    modes: ["pro"],
    titleKey: "Author in two languages",
    bodyKey: "Rich text, options and images — with German/English tabs.",
  },
  {
    id: "present.controls",
    target: "present.controls",
    kind: "info",
    navigateTo: "exampleSetPresent",
    titleKey: "Now present",
    bodyKey:
      "We’ll present the ready-made Example room (every question type). Start and stop questions, and show the QR / join code.",
  },
  {
    id: "results.export",
    // Anchored to the always-rendered results header (`results.view`), NOT the
    // export controls (`results.export`), which ResultsPage renders only when the
    // set has runs. The seeded example set has zero runs, so targeting the export
    // controls would dead-end the tour; the header is always present.
    target: "results.view",
    kind: "info",
    navigateTo: "exampleSetResults", // routes to the example set's /results page
    titleKey: "Results",
    bodyKey: "After a run, results are stored here — export CSV or delete a run.",
  },
  {
    id: "final",
    target: null,
    kind: "info",
    navigateTo: "roomsHome",
    titleKey: "You’ve got it 🎉",
    bodyKey:
      "You know the whole loop. Explore the Example room anytime — and restart this tour from the ? menu.",
  },
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
