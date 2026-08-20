// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { Archive, DoorOpen, Heart as HeartIcon, LogOut, Search, SearchX, Trash2, Users } from "lucide-react";
import { useApp, useEasyMode } from "../App";
import { api, type Room, type SearchResults } from "../api";
import { localizedText } from "@basicbar/ui";
import JoinByCode from "../components/JoinByCode";
import { Pager } from "../components/Pager";
import { Button, ConfirmInline, EmptyState, InfoHint, TextInput } from "../components/ui";
import { RoomSettingsForm, NEW_ROOM_DEFAULTS, type RoomSettings } from "./RoomPage";

type SortKey = "title" | "last_used" | "created";

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "last_used", label: "Last used" },
  { value: "created", label: "Last created" },
  { value: "title", label: "A–Z" },
];

/** Plain-text preview of a rich-HTML field for the compact room card — the
 * description is authored as HTML (TipTap) and must not show raw tags here. */
function stripHtml(html: string): string {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div.textContent?.trim() ?? "";
}

function sortRooms(list: Room[], key: SortKey): Room[] {
  return [...list].sort((a, b) => {
    if (key === "title") {
      return localizedText(a.title).localeCompare(localizedText(b.title), "de");
    }
    if (key === "created") return b.created_at.localeCompare(a.created_at);
    // last_used: most recent run first, rooms never used go last.
    const av = a.last_used_at ?? "";
    const bv = b.last_used_at ?? "";
    if (av && bv) return bv.localeCompare(av);
    if (av !== bv) return av ? -1 : 1;
    return b.created_at.localeCompare(a.created_at);
  });
}

function Heart({ filled }: { filled: boolean }) {
  return (
    <HeartIcon
      aria-hidden
      fill={filled ? "currentColor" : "none"}
      className="h-5 w-5"
    />
  );
}

function RoomCard({
  room,
  onToggleFavorite,
  onArchive,
  confirmDelete,
  setConfirmDelete,
  onDelete,
  confirmLeave,
  setConfirmLeave,
  onLeave,
}: {
  room: Room;
  onToggleFavorite: (room: Room) => void;
  onArchive: (room: Room) => void;
  confirmDelete: number | null;
  setConfirmDelete: (id: number | null) => void;
  onDelete: (id: number) => void;
  confirmLeave: number | null;
  setConfirmLeave: (id: number | null) => void;
  onLeave: (id: number) => void;
}) {
  const { t } = useTranslation();
  const sharedByMe = room.is_owner && room.owner_count > 1;
  const favoriteLabel = room.is_favorite
    ? t("Remove favorite")
    : t("Mark as favorite");
  const description = stripHtml(localizedText(room.description));
  return (
    <li className="relative min-w-0 rounded-2xl border border-slate-200 dark:border-slate-800 p-4 hover:border-brand-600">
      <div className="flex items-start justify-between gap-2">
        <Link
          to={`/rooms/${room.id}`}
          className="min-w-0 flex-1 after:absolute after:inset-0 after:rounded-2xl"
        >
          <h2 className="flex items-center gap-1.5 truncate font-semibold text-slate-900 dark:text-slate-100">
            {localizedText(room.title)}
            {sharedByMe && (
              <span
                title={t("Shared with {{count}} other people", {
                  count: room.owner_count - 1,
                })}
                className="inline-flex items-center text-brand-600 dark:text-brand-400"
              >
                <Users aria-label={t("shared")} className="h-4 w-4" />
              </span>
            )}
            {room.is_lti && (
              <span
                title={t("Created from an LMS via LTI")}
                className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400"
              >
                {t("From LMS")}
              </span>
            )}
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
            {t("Code")}{" "}
            <span className="font-mono font-semibold text-brand-700 dark:text-brand-300">
              {room.code}
            </span>{" "}
            · {room.question_set_count}{" "}
            {t("question set", { count: room.question_set_count })}
          </p>
          {!room.is_owner && room.owner_name && (
            <p className="mt-0.5 text-xs text-slate-400">
              {room.is_member
                ? t("shared by {{name}}", { name: room.owner_name })
                : t("Owner: {{name}}", { name: room.owner_name })}
            </p>
          )}
          {description && (
            <p className="mt-1 line-clamp-2 text-sm text-slate-400 dark:text-slate-500">
              {description}
            </p>
          )}
        </Link>
        <div className="relative z-10 flex shrink-0 items-center gap-1">
          {/* A foreign admin room (visible only via the staff "show all"
           * toggle) is view-only: no favorite/archive/leave/delete. */}
          {(room.is_owner || room.is_member) && (
            <>
              <button
                type="button"
                aria-label={favoriteLabel}
                aria-pressed={room.is_favorite}
                title={favoriteLabel}
                onClick={() => onToggleFavorite(room)}
                className={`rounded-lg p-1.5 transition-colors ${
                  room.is_favorite
                    ? "text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40"
                    : "text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
                }`}
              >
                <Heart filled={room.is_favorite} />
              </button>
              <button
                type="button"
                aria-label={t("Archive room")}
                title={t("Archive room")}
                onClick={() => onArchive(room)}
                className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
              >
                <Archive aria-hidden className="h-5 w-5" />
              </button>
            </>
          )}
          {/* A room shared with me can only be left, not deleted (#26). */}
          {!room.is_owner && room.is_member ? (
            confirmLeave === room.id ? (
              <ConfirmInline
                message={t("Leave this shared room?")}
                confirmLabel={t("Leave")}
                onConfirm={() => onLeave(room.id)}
                onCancel={() => setConfirmLeave(null)}
              />
            ) : (
              <Button
                variant="ghost"
                aria-label={t("Leave room {{title}}", { title: localizedText(room.title) })}
                title={t("Leave this shared room")}
                onClick={() => setConfirmLeave(room.id)}
              >
                <LogOut aria-hidden className="h-4 w-4" />
              </Button>
            )
          ) : room.is_owner ? (
            confirmDelete === room.id ? (
              <ConfirmInline
                message={
                  sharedByMe
                    ? t("Delete room for all {{count}} people?", {
                        count: room.owner_count,
                      })
                    : t("Delete room?")
                }
                onConfirm={() => onDelete(room.id)}
                onCancel={() => setConfirmDelete(null)}
              />
            ) : (
              <Button
                variant="ghost"
                aria-label={t("Delete room {{title}}", { title: localizedText(room.title) })}
                onClick={() => setConfirmDelete(room.id)}
              >
                <Trash2 aria-hidden className="h-4 w-4" />
              </Button>
            )
          ) : null}
        </div>
      </div>
    </li>
  );
}

/** Room overview: favourites on top, the rest sortable + paged, plus create
 * and a keyword search across rooms, sets and questions. */
export default function RoomsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { whoami } = useApp();
  const isStaff = !!whoami?.is_staff;
  const easyMode = useEasyMode();
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [newRoom, setNewRoom] = useState<RoomSettings | null>(null);
  const [createError, setCreateError] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [confirmLeave, setConfirmLeave] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("last_used");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [showAll, setShowAll] = useState(false);

  const reload = () => api.listRooms(showAll).then((page) => setRooms(page.results));
  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showAll]);

  const term = query.trim();
  useEffect(() => {
    if (term.length < 2) {
      setResults(null);
      return;
    }
    const handle = window.setTimeout(() => {
      void api.search(term).then(setResults);
    }, 250);
    return () => window.clearTimeout(handle);
  }, [term]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    if (!newRoom) return;
    setCreateError("");
    try {
      // A blank title is fine — the backend fills a dated default.
      const created = await api.createRoom(newRoom);
      setNewRoom(null);
      navigate(`/rooms/${created.id}`);
    } catch (err) {
      try {
        const data = JSON.parse((err as Error).message);
        const value = data.detail ?? Object.values(data)[0];
        setCreateError(Array.isArray(value) ? value[0] : String(value));
      } catch {
        setCreateError(String(err));
      }
    }
  }

  async function handleDelete(id: number) {
    await api.deleteRoom(id);
    setConfirmDelete(null);
    await reload();
  }

  async function handleLeave(id: number) {
    await api.leaveRoom(id);
    setConfirmLeave(null);
    await reload();
  }

  async function toggleFavorite(room: Room) {
    const updated = await api.toggleRoomFavorite(room.id, !room.is_favorite);
    setRooms((current) =>
      (current ?? []).map((r) => (r.id === room.id ? updated : r)),
    );
  }

  async function archiveRoom(room: Room) {
    // Archiving drops the room from the overview; it lives on in the archive.
    await api.toggleRoomArchive(room.id, true);
    setRooms((current) => (current ?? []).filter((r) => r.id !== room.id));
  }

  if (!rooms) return null;

  const searching = term.length >= 2;
  const favorites = sortRooms(rooms.filter((r) => r.is_favorite), sortKey);
  // Rooms shared with me by someone else get their own category (#25); my own
  // rooms (incl. those I share with others) stay in the main, paged list.
  // Staff additionally see every other room (via ?all=1) in a third,
  // view-only category once "Show all rooms" is on.
  const mine = sortRooms(rooms.filter((r) => r.is_owner), sortKey);
  const sharedWithMe = sortRooms(
    rooms.filter((r) => !r.is_owner && r.is_member),
    sortKey,
  );
  const others = sortRooms(
    rooms.filter((r) => !r.is_owner && !r.is_member),
    sortKey,
  );
  const totalPages = Math.max(1, Math.ceil(mine.length / pageSize));
  const current = Math.min(page, totalPages);
  const pageMine = mine.slice((current - 1) * pageSize, current * pageSize);

  const cardProps = {
    onToggleFavorite: (r: Room) => void toggleFavorite(r),
    onArchive: (r: Room) => void archiveRoom(r),
    confirmDelete,
    setConfirmDelete,
    onDelete: (id: number) => void handleDelete(id),
    confirmLeave,
    setConfirmLeave,
    onLeave: (id: number) => void handleLeave(id),
  };

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">{t("My rooms")}</h1>
        <JoinByCode compact />
      </div>

      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 sm:max-w-xs">
          <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <TextInput
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("Search rooms, sets, questions …")}
            aria-label={t("Search rooms, question sets and questions")}
            className="pl-9"
          />
        </div>
        <div className="flex items-center gap-2">
          <InfoHint
            text={t(
              "A room is the permanent access point for participants — typically a course. Its code stays the same across all quizzes.",
            )}
          />
          <Button
            variant="primary"
            onClick={() => {
              setCreateError("");
              setNewRoom(NEW_ROOM_DEFAULTS);
            }}
          >
            + {t("New room")}
          </Button>
        </div>
      </div>

      {/* Single-step create dialog: name, description and features (#2). */}
      {newRoom && (
        <form
          onSubmit={handleCreate}
          className="mb-6 max-w-2xl rounded-2xl border border-brand-200 bg-brand-50/50 p-4 dark:border-brand-900"
        >
          <h2 className="mb-3 font-semibold">{t("New room")}</h2>
          <RoomSettingsForm
            draft={newRoom}
            onChange={(patch) => setNewRoom({ ...newRoom, ...patch })}
            titlePlaceholder={t("e.g. “Bio 101 lecture”")}
            easyMode={easyMode}
          />
          <div className="mt-3 flex gap-2">
            <Button type="submit" variant="primary">
              {t("Create")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setNewRoom(null);
                setCreateError("");
              }}
            >
              {t("Cancel")}
            </Button>
          </div>
          {createError && <p className="mt-1 text-sm text-red-600">{createError}</p>}
        </form>
      )}

      {searching ? (
        <SearchView results={results} query={term} />
      ) : rooms.length === 0 ? (
        <EmptyState icon={DoorOpen} title={t("No rooms yet")}>
          {t(
            "A room is the permanent access point for participants — typically a course. Its code stays the same across all quizzes.",
          )}
        </EmptyState>
      ) : (
        <>
          {favorites.length > 0 && (
            <section className="mb-6">
              <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-500 dark:text-slate-400">
                <span className="text-red-500">
                  <Heart filled />
                </span>
                {t("Favorites")}
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2">
                {favorites.map((room) => (
                  <RoomCard key={room.id} room={room} {...cardProps} />
                ))}
              </ul>
            </section>
          )}

          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400">
              {t("My rooms")}
            </h2>
            <div className="flex items-center gap-4">
              {isStaff && (
                <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                  <input
                    type="checkbox"
                    checked={showAll}
                    onChange={(event) => {
                      setShowAll(event.target.checked);
                      setPage(1);
                    }}
                    className="h-4 w-4 rounded border-slate-300 accent-brand-600 dark:border-slate-700"
                  />
                  {t("Show all rooms in the system")}
                </label>
              )}
              <label className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
                {t("Sort by:")}
                <select
                  value={sortKey}
                  onChange={(event) => {
                    setSortKey(event.target.value as SortKey);
                    setPage(1);
                  }}
                  className="rounded-md border border-slate-300 bg-white px-2 py-1 text-slate-700 focus:border-brand-600 focus:outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                >
                  {SORT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {t(option.label)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          {mine.length === 0 ? (
            <p className="text-sm text-slate-400">{t("You don't own any rooms yet.")}</p>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2">
              {pageMine.map((room) => (
                <RoomCard key={room.id} room={room} {...cardProps} />
              ))}
            </ul>
          )}
          <Pager
            page={current}
            pageSize={pageSize}
            count={mine.length}
            onPage={setPage}
            onPageSize={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />

          {/* Rooms shared with me by others (#25). */}
          {sharedWithMe.length > 0 && (
            <section className="mt-8">
              <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-500 dark:text-slate-400">
                <Users aria-hidden className="h-4 w-4" />
                {t("Shared with me")}
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2">
                {sharedWithMe.map((room) => (
                  <RoomCard key={room.id} room={room} {...cardProps} />
                ))}
              </ul>
            </section>
          )}

          {/* Staff-only: every other room, visible via "Show all rooms in the
              system". */}
          {showAll && others.length > 0 && (
            <section className="mt-8">
              <h2 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-slate-500 dark:text-slate-400">
                <Users aria-hidden className="h-4 w-4" />
                {t("All rooms in the system")}
                <span className="rounded-full bg-slate-200 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                  {t("Admin")}
                </span>
              </h2>
              <ul className="grid gap-3 sm:grid-cols-2">
                {others.map((room) => (
                  <RoomCard key={room.id} room={room} {...cardProps} />
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

/** Grouped search results (rooms, sets, questions). Each row links to the
 * relevant page; questions open their set's editor. */
function SearchView({
  results,
  query,
}: {
  results: SearchResults | null;
  query: string;
}) {
  const { t } = useTranslation();
  if (!results) return <p className="text-sm text-slate-400">{t("Searching …")}</p>;

  const empty =
    results.rooms.length === 0 &&
    results.sets.length === 0 &&
    results.questions.length === 0;
  if (empty) {
    return (
      <EmptyState icon={SearchX} title={t("No results")}>
        {t(
          "Nothing found in your rooms, question sets or questions for “{{query}}”.",
          { query },
        )}
      </EmptyState>
    );
  }

  const rowClass =
    "block rounded-xl border border-slate-200 dark:border-slate-800 px-4 py-2.5 hover:border-brand-600";
  const crumb = "text-xs text-slate-500 dark:text-slate-400";

  return (
    <div className="space-y-6">
      {results.rooms.length > 0 && (
        <Group title={t("Rooms")} count={results.rooms.length}>
          {results.rooms.map((room) => (
            <Link key={room.id} to={`/rooms/${room.id}`} className={rowClass}>
              <span className="font-medium text-slate-900 dark:text-slate-100">
                {room.title}
              </span>
              <span className={`ml-2 font-mono ${crumb}`}>{room.code}</span>
            </Link>
          ))}
        </Group>
      )}

      {results.sets.length > 0 && (
        <Group title={t("Question sets")} count={results.sets.length}>
          {results.sets.map((set) => (
            <Link key={set.id} to={`/sets/${set.id}`} className={rowClass}>
              <span className="font-medium text-slate-900 dark:text-slate-100">
                {set.title}
              </span>
              <span className={`ml-2 ${crumb}`}>
                {t("in {{room}}", { room: set.room_title })}
              </span>
            </Link>
          ))}
        </Group>
      )}

      {results.questions.length > 0 && (
        <Group title={t("Questions")} count={results.questions.length}>
          {results.questions.map((question) => (
            <Link
              key={question.id}
              to={`/sets/${question.question_set}`}
              className={rowClass}
            >
              <span className="text-slate-900 dark:text-slate-100">
                {question.text}
              </span>
              <span className={`mt-0.5 block ${crumb}`}>
                {question.set_title} · {question.room_title}
              </span>
            </Link>
          ))}
        </Group>
      )}
    </div>
  );
}

function Group({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 className="mb-2 text-sm font-semibold text-slate-500 dark:text-slate-400">
        {title} <span className="font-normal">({count})</span>
      </h2>
      <div className="space-y-2">{children}</div>
    </section>
  );
}
