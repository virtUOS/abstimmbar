// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Enter a room code to join a live vote — available on every start page, for
 * signed-in staff and anonymous visitors alike (#15). Codes may be the
 * three-word or the legacy numeric form; the participant page (served by
 * Django at /p/<code>/) resolves them case-insensitively. */
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useTheme } from "@basicbar/ui";
import { live } from "../api";
import { Button, TextInput } from "./ui";

export default function JoinByCode({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  const { appearance } = useTheme();
  const [code, setCode] = useState("");

  function join(event: FormEvent) {
    event.preventDefault();
    const trimmed = code.trim();
    if (trimmed) {
      // The participant page is a separate (framework-free) Django page, so
      // this is a full navigation, not a client-side route. Carry the app's
      // resolved theme so the target page (incl. the "room not found" page,
      // #56) matches the app even cross-origin, where it can't read the app's
      // localStorage.
      const theme =
        appearance === "dark"
          ? "dark"
          : appearance === "light"
            ? "light"
            : window.matchMedia?.("(prefers-color-scheme: dark)").matches
              ? "dark"
              : "light";
      window.location.href = `${live.participantUrl(trimmed)}?theme=${theme}`;
    }
  }

  if (compact) {
    return (
      <form onSubmit={join} className="flex items-end gap-2">
        <TextInput
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder={t("Room code …")}
          aria-label={t("Join a vote — room code")}
          className="!w-48"
        />
        <Button type="submit" variant="primary" disabled={!code.trim()}>
          {t("Join")}
        </Button>
      </form>
    );
  }

  return (
    <form
      onSubmit={join}
      className="flex flex-col gap-3 rounded-2xl border border-brand-200 bg-brand-50/50 p-5 dark:border-brand-900 dark:bg-brand-950/30 sm:flex-row sm:items-end"
    >
      <div className="flex-1">
        <label className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
          {t("Join a vote")}
        </label>
        <TextInput
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder={t("Enter room code (three words or digits)")}
          aria-label={t("Room code", { context: "input" })}
        />
      </div>
      <Button type="submit" variant="primary" disabled={!code.trim()}>
        {t("Join")}
      </Button>
    </form>
  );
}
