// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArchiveRestore, Archive } from "lucide-react";
import { api, type Room } from "../api";
import { Button, EmptyState } from "../components/ui";
import { localizedText } from "@basicbar/ui";

/** Archive page (#16): rooms the user archived out of their overview, with a
 * one-click restore. Reachable from the user menu, analogous to favourites. */
export default function ArchivePage() {
  const { t } = useTranslation();
  const [rooms, setRooms] = useState<Room[] | null>(null);

  useEffect(() => {
    void api.listArchivedRooms().then((page) => setRooms(page.results));
  }, []);

  async function restore(room: Room) {
    await api.toggleRoomArchive(room.id, false);
    setRooms((current) => (current ?? []).filter((r) => r.id !== room.id));
  }

  if (!rooms) return null;

  return (
    <div>
      <nav className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        <Link to="/" className="hover:text-brand-700 dark:hover:text-brand-300">
          {t("My rooms")}
        </Link>{" "}
        / {t("Archived rooms")}
      </nav>
      <h1 className="mb-6 text-2xl font-bold">{t("Archived rooms")}</h1>

      {rooms.length === 0 ? (
        <EmptyState icon={Archive} title={t("No archived rooms")}>
          {t(
            "Archived rooms disappear from “My rooms” and show up here instead. Use a room's ⋮ menu to archive it.",
          )}
        </EmptyState>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {rooms.map((room) => (
            <li
              key={room.id}
              className="relative flex items-start justify-between gap-2 rounded-2xl border border-slate-200 p-4 hover:border-brand-600 dark:border-slate-800"
            >
              <Link
                to={`/rooms/${room.id}`}
                className="min-w-0 after:absolute after:inset-0 after:rounded-2xl"
              >
                <h2 className="truncate font-semibold text-slate-900 dark:text-slate-100">
                  {localizedText(room.title)}
                </h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                  {t("Code")}{" "}
                  <span className="font-mono font-semibold text-brand-700 dark:text-brand-300">
                    {room.code}
                  </span>{" "}
                  · {room.question_set_count}{" "}
                  {t("question set", { count: room.question_set_count })}
                </p>
              </Link>
              <div className="relative z-10">
                <Button
                  onClick={() => void restore(room)}
                  className="inline-flex items-center gap-1.5 whitespace-nowrap"
                >
                  <ArchiveRestore aria-hidden className="h-4 w-4" />
                  {t("Restore")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
