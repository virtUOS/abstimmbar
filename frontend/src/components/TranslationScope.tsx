// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Translation controls ("DE · EN · Translate all fields") for one form.
 *
 * The app-wide `TranslationFormProvider` (main.tsx) renders them as a pill
 * floating over the page. On phones that pill covers the form it belongs to
 * (#179, T4). A form wraps its fields in this nested provider instead: its
 * fields register here, and the controls render as the form's first grid
 * item on narrow screens (in the flow, never on top of content) and float
 * bottom-right as before from `md` up. The wrapping container must be a grid
 * or flex column. Use it only where it is the page's sole set of translatable
 * fields — two scopes on one page would stack two pills on desktop. */
import type { ReactNode } from "react";
import { TranslationFormProvider, type TranslateFn } from "@basicbar/ui";
import { api } from "../api";

export const translateContent: TranslateFn = (text, source, target, format) =>
  api.translate(text, source, target, format).then((r) => r.translated);

/** `translation-controls` is an unstyled hook for the e2e tests. */
export const TRANSLATION_CONTROLS_HOOK = "translation-controls";

export default function TranslationScope({ children }: { children: ReactNode }) {
  return (
    <TranslationFormProvider
      translate={translateContent}
      controlsClassName={`${TRANSLATION_CONTROLS_HOOK} max-md:order-first max-md:self-end max-md:justify-self-end md:fixed md:bottom-6 md:right-6 md:z-40`}
    >
      {children}
    </TranslationFormProvider>
  );
}
