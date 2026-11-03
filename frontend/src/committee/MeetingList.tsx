// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee rooms (Gremien-Raum): the room's meetings, split into upcoming
 *  ones (soonest first) and the archive of ended ones (latest first), plus
 *  the fields for creating a meeting (title + required date). */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";
import { CalendarClock, ChartColumnDecreasing, Trash2 } from "lucide-react";
import { localizedText, type LocalizedText } from "@basicbar/ui";
import type { MeetingState, QuestionSet } from "../api";
import { Button, Select } from "../components/ui";
import TranslatableField from "../components/TranslatableField";
import { SET_TYPES } from "../setTypes";

export const STATE_LABEL: Record<MeetingState, string> = {
  draft: "Planned",
  started: "In progress",
  ended: "Ended",
};

export const STATE_BADGE: Record<MeetingState, string> = {
  draft: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
  started: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  ended: "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400",
};

function scheduled(set: QuestionSet) {
  return set.scheduled_at ?? "";
}

/** Upcoming (not ended) by date ascending — undated last — and the archive
 *  (ended) by date descending. */
function splitMeetings(sets: QuestionSet[]) {
  const upcoming = sets
    .filter((set) => set.meeting_state !== "ended")
    .sort((a, b) => {
      const av = scheduled(a);
      const bv = scheduled(b);
      if (av && bv) return av.localeCompare(bv);
      if (av !== bv) return av ? -1 : 1;
      return a.created_at.localeCompare(b.created_at);
    });
  const archive = sets
    .filter((set) => set.meeting_state === "ended")
    .sort((a, b) => scheduled(b).localeCompare(scheduled(a)));
  return { upcoming, archive };
}

export function MeetingList({
  sets,
  onDelete,
}: {
  sets: QuestionSet[];
  onDelete: (setId: number) => void;
}) {
  const { t } = useTranslation();
  const { upcoming, archive } = splitMeetings(sets);
  return (
    <div className="grid gap-6">
      <section>
        <h3 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">
          {t("Upcoming meetings")}
        </h3>
        {upcoming.length === 0 ? (
          <p className="text-sm text-slate-400">{t("No upcoming meetings.")}</p>
        ) : (
          <MeetingCards sets={upcoming} onDelete={onDelete} />
        )}
      </section>
      {archive.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">
            {t("Archive")}
          </h3>
          <MeetingCards sets={archive} onDelete={onDelete} />
        </section>
      )}
    </div>
  );
}

function MeetingCards({
  sets,
  onDelete,
}: {
  sets: QuestionSet[];
  onDelete: (setId: number) => void;
}) {
  const { t, i18n } = useTranslation();
  const Icon = SET_TYPES.meeting.icon;
  const formatter = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {sets.map((set) => {
        const title = localizedText(set.title);
        return (
          <li
            key={set.id}
            className="relative min-w-0 rounded-2xl border border-slate-200 bg-slate-50/50 p-4 hover:border-brand-600 dark:border-slate-800 dark:bg-slate-900/40"
          >
            <div className="flex items-start gap-3">
              <span
                aria-hidden
                className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${SET_TYPES.meeting.accent.iconBox}`}
              >
                <Icon className="h-5 w-5" />
              </span>
              <Link
                to={`/sets/${set.id}`}
                className="min-w-0 flex-1 after:absolute after:inset-0 after:rounded-2xl"
              >
                <h4 className="truncate font-semibold text-slate-900 dark:text-slate-100">
                  {title}
                </h4>
                <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
                  <span className="inline-flex items-center gap-1">
                    <CalendarClock aria-hidden className="h-3.5 w-3.5" />
                    {set.scheduled_at ? formatter.format(new Date(set.scheduled_at)) : t("No date")}
                  </span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STATE_BADGE[set.meeting_state]}`}
                  >
                    {t(STATE_LABEL[set.meeting_state])}
                  </span>
                </p>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t("{{count}} agenda item", { count: set.question_count })}
                </p>
              </Link>
            </div>
            <div className="relative z-10 mt-3 flex items-center justify-end gap-1 border-t border-slate-100 pt-2 dark:border-slate-800">
              {set.has_results && (
                <Link
                  to={`/sets/${set.id}/results`}
                  aria-label={t("View results of {{title}}", { title })}
                  title={t("View results")}
                  className="inline-flex items-center rounded-lg px-2 py-1.5 text-brand-700 hover:bg-brand-50 dark:text-brand-300 dark:hover:bg-brand-950"
                >
                  <ChartColumnDecreasing aria-hidden className="h-4 w-4" />
                </Link>
              )}
              <Button
                variant="ghost"
                aria-label={t("Delete meeting {{title}}", { title })}
                title={t("Delete")}
                className="inline-flex items-center"
                onClick={() => onDelete(set.id)}
              >
                <Trash2 aria-hidden className="h-4 w-4" />
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** Create-form fields for a meeting: title and the required date/time
 *  (a `datetime-local` value, i.e. the browser's local time). */
export function NewMeetingFields({
  title,
  scheduledAt,
  onChange,
}: {
  title: LocalizedText;
  scheduledAt: string;
  onChange: (patch: { title?: LocalizedText; scheduledAt?: string }) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="grid max-w-2xl gap-6">
      <TranslatableField
        label={t("Title")}
        value={title}
        onChange={(next) => onChange({ title: next })}
        placeholder={t("e.g. “Faculty council, 12th meeting”")}
      />
      <MeetingDateInput
        value={scheduledAt}
        onChange={(next) => onChange({ scheduledAt: next })}
      />
    </div>
  );
}

// Meetings run between 6:00 and 21:00.
const HOURS = Array.from({ length: 16 }, (_, i) => `${String(i + 6).padStart(2, "0")}:00`);

/** Meeting date plus a full-hour time — committee meetings start on the
 *  hour, so a minute picker is just noise. `value` is a `datetime-local`
 *  string ("YYYY-MM-DDTHH:MM"); `onChange` reports "" until both parts are
 *  set. A stored time off the hour stays selectable. `onBlur` fires once
 *  focus leaves both controls. */
export function MeetingDateInput({
  value,
  onChange,
  onBlur,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  onBlur?: () => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const [date, setDate] = useState(value.slice(0, 10));
  const [time, setTime] = useState(value.slice(11, 16));
  useEffect(() => {
    if (!value) return;
    setDate(value.slice(0, 10));
    setTime(value.slice(11, 16));
  }, [value]);

  function update(nextDate: string, nextTime: string) {
    setDate(nextDate);
    setTime(nextTime);
    onChange(nextDate && nextTime ? `${nextDate}T${nextTime}` : "");
  }

  const hours = time && !HOURS.includes(time) ? [...HOURS, time].sort() : HOURS;
  return (
    <fieldset
      className="min-w-0"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) onBlur?.();
      }}
    >
      <legend className="mb-1 block text-sm font-medium text-slate-700 dark:text-slate-300">
        {t("Date and time")}
      </legend>
      <div className="flex gap-2">
        <input
          type="date"
          required
          aria-label={t("Date")}
          value={date}
          disabled={disabled}
          onChange={(event) => update(event.target.value, time)}
          className="min-w-0 flex-1 rounded-lg border border-field bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-600 focus:ring-offset-2 focus:ring-offset-white disabled:opacity-60 sm:max-w-[12rem] dark:bg-slate-900 dark:text-slate-100 dark:[color-scheme:dark] dark:focus:ring-offset-slate-950"
        />
        <Select
          required
          aria-label={t("Time")}
          value={time}
          disabled={disabled}
          onChange={(event) => update(date, event.target.value)}
          className="!w-auto disabled:opacity-60"
        >
          <option value="" disabled>
            {t("Time")}
          </option>
          {hours.map((hour) => (
            <option key={hour} value={hour}>
              {hour}
            </option>
          ))}
        </Select>
      </div>
    </fieldset>
  );
}
