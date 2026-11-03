// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Console section "Attendance": who is connected, who has not entered yet,
 *  who was removed; remove (right away or after an item) and readmit via the
 *  PR-1 invite endpoints. Names appear here only, never on the beamer. */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Trash2, UserRoundCheck } from "lucide-react";
import { stripHtml } from "@basicbar/ui";
import { api, type MeetingAttendance as Row, type MeetingManager } from "../api";
import { Button, Field, Select } from "../components/ui";
import type { ConsoleAction } from "./MeetingAgenda";

function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function Status({ row }: { row: Row }) {
  const { t } = useTranslation();
  if (row.removed)
    return <span className="text-red-700 dark:text-red-400">{t("removed")}</span>;
  if (!row.entered)
    return <span className="text-slate-500 dark:text-slate-400">{t("not entered yet")}</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-300">
      <span
        aria-hidden
        className={`h-2 w-2 shrink-0 rounded-full ${row.connected ? "bg-emerald-500" : "bg-slate-400"}`}
      />
      {row.connected
        ? t("connected")
        : row.disconnected_since
          ? t("disconnected since {{time}}", { time: clock(row.disconnected_since) })
          : t("disconnected")}
    </span>
  );
}

export default function MeetingAttendance({
  setId,
  data,
  busy,
  act,
}: {
  setId: number;
  data: MeetingManager;
  busy: boolean;
  act: ConsoleAction;
}) {
  const { t } = useTranslation();
  const [removing, setRemoving] = useState<number | null>(null);
  const [after, setAfter] = useState("");
  const running = data.meeting.state === "started";

  return (
    <section aria-labelledby="console-attendance" className="grid gap-2">
      <h2
        id="console-attendance"
        className="text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
      >
        {t("Attendance")}
      </h2>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {data.attendance.map((row) => (
          <li key={row.invite} data-testid="console-attendee" className="grid gap-2 py-2">
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1 text-sm">
                <span className="block break-words font-medium text-slate-800 dark:text-slate-200">
                  {row.name}
                </span>
                <span className="block break-words text-xs text-slate-500 dark:text-slate-400">
                  {row.group}
                  {row.observer && ` · ${t("Observer")}`}
                  {row.deputy && ` · ${t("Deputy")}`}
                </span>
                <span className="block text-xs">
                  <Status row={row} />
                </span>
              </div>
              {running && removing !== row.invite && !row.removed && (
                <Button
                  variant="ghost"
                  aria-label={t("Remove {{name}}", { name: row.name })}
                  title={t("Remove")}
                  disabled={busy}
                  onClick={() => {
                    setAfter("");
                    setRemoving(row.invite);
                  }}
                >
                  <Trash2 aria-hidden className="h-4 w-4" />
                </Button>
              )}
              {running && row.removed && (
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => void act(() => api.readmitInvite(setId, row.invite))}
                  className="inline-flex items-center gap-1"
                >
                  <UserRoundCheck aria-hidden className="h-4 w-4" />
                  <span className="text-xs">{t("Readmit")}</span>
                </Button>
              )}
            </div>
            {running && removing === row.invite && (
              <div className="grid gap-2">
                <Field label={t("Remove from the meeting")}>
                  <Select value={after} onChange={(event) => setAfter(event.target.value)}>
                    <option value="">{t("Right away")}</option>
                    {data.items.map((item) => {
                      const label = t("Item {{number}}", { number: item.number });
                      const text = stripHtml(item.text).trim();
                      const short = text.length > 40 ? `${text.slice(0, 40)}…` : text;
                      return (
                        <option key={item.id} value={item.id}>
                          {t("after {{item}}", { item: short ? `${label}: ${short}` : label })}
                        </option>
                      );
                    })}
                  </Select>
                </Field>
                <span className="flex gap-1">
                  <Button
                    variant="danger"
                    disabled={busy}
                    onClick={() =>
                      void act(() =>
                        api.removeInvite(setId, row.invite, after ? Number(after) : null),
                      ).then((ok) => ok && setRemoving(null))
                    }
                  >
                    {t("Remove")}
                  </Button>
                  <Button variant="ghost" onClick={() => setRemoving(null)}>
                    {t("Cancel")}
                  </Button>
                </span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
