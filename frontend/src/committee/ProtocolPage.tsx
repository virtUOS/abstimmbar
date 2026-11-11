// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee rooms (Gremien-Raum): the printable protocol of an ended
 *  meeting — attendance, substitutions, and per agenda item the text, the
 *  count, the finding and the seal reference. Printing (or "save as PDF")
 *  hides the app chrome and renders black on white. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { Download, Printer, ShieldCheck } from "lucide-react";
import { RichText } from "@basicbar/ui";
import {
  api,
  requestBody,
  requestError,
  type MeetingProtocol,
  type ProtocolItem,
  type ProtocolRound,
} from "../api";
import HomeCrumb from "../components/HomeCrumb";
import { TopNote } from "./MeetingAgenda";
import { Button } from "../components/ui";

/** 64 hex characters as 4 blocks of 16. */
function fingerprintBlocks(hash: string): string {
  return (hash.match(/.{1,16}/g) ?? [hash]).join(" ");
}

function answerLabel(
  t: (key: string) => string,
  item: ProtocolRound,
  key: string,
): string {
  if (key === "yes") return t("Yes");
  if (key === "no") return t("No");
  if (key === "abstain") return t("Abstention");
  if (key === "text") return t("Answers");
  return item.options.find((option) => option.key === key)?.text ?? key;
}

export default function ProtocolPage() {
  const { t, i18n } = useTranslation();
  const { setId } = useParams();
  const [protocol, setProtocol] = useState<MeetingProtocol | null>(null);
  const [roomId, setRoomId] = useState<number | null>(null);
  const [error, setError] = useState<"" | "not_ended" | "other">("");
  const [message, setMessage] = useState("");
  const [savingNote, setSavingNote] = useState(false);
  const [noteError, setNoteError] = useState<{ top: number; text: string } | null>(null);

  /** Notes can still be added after the meeting — the minutes are often
   *  completed afterwards (e.g. who did not vote and why). */
  async function saveNote(
    top: number,
    target: { section: number } | { question: number },
    text: string,
  ): Promise<boolean> {
    setSavingNote(true);
    setNoteError(null);
    try {
      await api.setMeetingNote(Number(setId), target, text);
      setProtocol(await api.getMeetingProtocol(Number(setId)));
      return true;
    } catch (err) {
      setNoteError({ top, text: t(requestError(err)) });
      return false;
    } finally {
      setSavingNote(false);
    }
  }

  useEffect(() => {
    setProtocol(null);
    setError("");
    api
      .getMeetingProtocol(Number(setId))
      .then(setProtocol)
      .catch((err) => {
        if (requestBody(err)?.code === "not_ended") setError("not_ended");
        else {
          setError("other");
          setMessage(requestError(err));
        }
      });
    void api
      .getQuestionSet(Number(setId))
      .then((set) => setRoomId(set.room))
      .catch(() => setRoomId(null));
  }, [setId]);

  const dateTime = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "long",
    timeStyle: "short",
  });
  const time = new Intl.DateTimeFormat(i18n.language, { timeStyle: "short" });

  return (
    <div className="protocol-sheet mx-auto max-w-3xl">
      <nav className="mb-4 flex flex-wrap items-center gap-1 text-sm text-slate-500 print:hidden dark:text-slate-400">
        <HomeCrumb /> /{" "}
        {roomId ? (
          <Link to={`/rooms/${roomId}`} className="hover:underline">
            {protocol?.committee ?? "…"}
          </Link>
        ) : (
          "…"
        )}{" "}
        / {t("Protocol")}
      </nav>

      {error === "not_ended" && (
        <p
          role="status"
          data-testid="protocol-not-ended"
          className="rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-900 dark:text-slate-300"
        >
          {t("The protocol is available once the meeting has ended.")}{" "}
          <Link to={`/sets/${setId}`} className="underline">
            {t("Back to the meeting")}
          </Link>
        </p>
      )}
      {error === "other" && (
        <p role="alert" className="text-sm text-red-700 dark:text-red-400">
          {t(message)}
        </p>
      )}

      {protocol && (
        <article data-testid="protocol" className="grid gap-6">
          <header className="grid gap-2">
            <div className="flex flex-col items-start gap-3 sm:flex-row sm:justify-between">
              <div className="min-w-0">
                <p className="text-sm text-slate-500 dark:text-slate-400">{protocol.committee}</p>
                <h1 className="break-words text-2xl font-semibold text-slate-900 dark:text-slate-100">
                  {t("Protocol")}: {protocol.title}
                </h1>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2 print:hidden">
                <a
                  href={api.meetingProtocolPdfUrl(Number(setId), i18n.language)}
                  download
                  data-testid="protocol-pdf"
                  className="inline-flex items-center gap-1.5 rounded-lg bg-brand-400 px-3 py-1.5 text-sm font-semibold text-slate-900 hover:bg-brand-500"
                >
                  <Download aria-hidden className="h-4 w-4" />
                  {t("Download PDF")}
                </a>
                <Button
                  variant="secondary"
                  className="inline-flex items-center gap-1.5"
                  onClick={() => window.print()}
                >
                  <Printer aria-hidden className="h-4 w-4" />
                  {t("Print")}
                </Button>
              </div>
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {[
                protocol.scheduled_at && dateTime.format(new Date(protocol.scheduled_at)),
                protocol.started_at &&
                  t("Start: {{time}}", { time: time.format(new Date(protocol.started_at)) }),
                protocol.ended_at && t("End: {{time}}", { time: time.format(new Date(protocol.ended_at)) }),
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </header>

          <section className="break-inside-avoid">
            <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
              {t("Attendance")}
            </h2>
            {protocol.attendance.present.length === 0 ? (
              <p className="text-sm text-slate-600 dark:text-slate-400">—</p>
            ) : (
              <ul className="grid gap-x-6 gap-y-0.5 text-sm text-slate-800 sm:grid-cols-2 dark:text-slate-200">
                {protocol.attendance.present.map((person, index) => (
                  <li key={index} className="min-w-0">
                    {person.name}{" "}
                    <span className="text-slate-500 dark:text-slate-400">({person.group})</span>
                    {person.left && (
                      <span className="text-slate-500 dark:text-slate-400">
                        {" "}
                        –{" "}
                        {person.left_after
                          ? t("left after TOP {{label}}", { label: person.left_after })
                          : t("left")}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {protocol.attendance.substitutions.length > 0 && (
            <section className="break-inside-avoid">
              <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                {t("Substitutions")}
              </h2>
              <ul className="grid gap-0.5 text-sm text-slate-800 dark:text-slate-200">
                {protocol.attendance.substitutions.map((sub, index) => (
                  <li key={index}>
                    {sub.from_label
                      ? t("{{deputy}} substitutes {{absent}} ({{group}}) from TOP {{label}}", {
                          deputy: sub.deputy,
                          absent: sub.absent,
                          group: sub.group,
                          label: sub.from_label,
                        })
                      : t("{{deputy}} substitutes {{absent}} ({{group}})", {
                          deputy: sub.deputy,
                          absent: sub.absent,
                          group: sub.group,
                        })}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {protocol.attendance.observers.length > 0 && (
            <section className="break-inside-avoid">
              <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                {t("Observers")}
              </h2>
              <p className="text-sm text-slate-800 dark:text-slate-200">
                {protocol.attendance.observers.join(", ")}
              </p>
            </section>
          )}

          <section className="grid gap-5">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {t("Agenda")}
            </h2>
            {protocol.tops.map((top) => (
              <div key={top.number} className="grid gap-3">
                {top.title && (
                  <div className="break-after-avoid">
                    <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                      {t("TOP {{number}}", { number: top.number })}: {top.title}
                    </h3>
                    {top.description && (
                      <RichText
                        html={top.description}
                        className="protocol-rich mt-0.5 text-sm text-slate-600 dark:text-slate-400"
                      />
                    )}
                  </div>
                )}
                {top.note && (
                  <p
                    data-testid="protocol-note"
                    className="hidden whitespace-pre-line break-words text-sm text-slate-800 print:block dark:text-slate-200"
                  >
                    <span className="font-semibold">{t("Note")}: </span>
                    {top.note}
                  </p>
                )}
                {(top.section || top.question) && (
                  <div className="grid gap-1.5 print:hidden">
                    <TopNote
                      text={top.note ?? ""}
                      editable
                      busy={savingNote}
                      onSave={(text) =>
                        saveNote(
                          top.number,
                          top.section ? { section: top.section } : { question: top.question as number },
                          text,
                        )
                      }
                    />
                    {noteError?.top === top.number && (
                      <p role="alert" className="text-sm text-red-700 dark:text-red-400">
                        {noteError.text}
                      </p>
                    )}
                  </div>
                )}
                {top.items.map((item) => (
                  <ItemBlock key={item.label} item={item} roomId={roomId} />
                ))}
              </div>
            ))}
          </section>

          <p className="border-t border-slate-200 pt-3 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
            {t("Every result in this protocol is sealed. With its reference and fingerprint, anyone managing the room can check under Abstimmbar → Room → “Check seal” whether the result was changed afterwards.")}
          </p>
        </article>
      )}
    </div>
  );
}

function ItemBlock({ item, roomId }: { item: ProtocolItem; roomId: number | null }) {
  const { t } = useTranslation();
  const muted = "text-slate-600 dark:text-slate-400";
  return (
    <div
      data-testid="protocol-item"
      className="break-inside-avoid grid gap-2 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-800"
    >
      <div className="flex items-start gap-2 font-medium text-slate-900 dark:text-slate-100">
        <span className="shrink-0 font-semibold">{t("TOP {{number}}", { number: item.label })}</span>
        <RichText html={item.text} className="protocol-rich min-w-0 flex-1" />
      </div>
      {item.version_changed && item.version && (
        <p className={muted}>
          {t("Version {{n}} – differs from the version at the start of the meeting", {
            n: item.version,
          })}
        </p>
      )}
      {item.rounds_discarded.map((round) => (
        <p key={round.round} className={muted}>
          {round.reason === "restart"
            ? t("Interrupted by a server restart")
            : t("Vote repeated (round {{round}}): {{comment}}", {
                round: round.round,
                comment: round.comment,
              })}
        </p>
      ))}
      {item.bundle_with.length > 0 && (
        <p className={muted}>
          {t("Voted en bloc with TOP {{labels}}", { labels: item.bundle_with.join(", ") })}
        </p>
      )}

      {item.status === "not_voted" || !item.result ? (
        <p className={muted}>{t("Not voted")}</p>
      ) : (
        <>
          {item.earlier_rounds.map((round) => (
            <RoundBlock key={round.round} item={item} round={round} heading roomId={roomId} />
          ))}
          <RoundBlock
            item={item}
            round={item}
            heading={item.runoff || item.earlier_rounds.length > 0}
            roomId={roomId}
          />
        </>
      )}
    </div>
  );
}

/** One closed ballot round: kind, counts, voters, finding, seal. */
function RoundBlock({
  item,
  round,
  heading,
  roomId,
}: {
  item: ProtocolItem;
  round: ProtocolRound;
  heading: boolean;
  roomId: number | null;
}) {
  const { t, i18n } = useTranslation();
  const time = new Intl.DateTimeFormat(i18n.language, { timeStyle: "short" });
  const label = (key: string) => answerLabel(t as (key: string) => string, round, key);
  const result = round.result;
  const muted = "text-slate-600 dark:text-slate-400";
  if (!result) return null;
  return (
    <div data-testid="protocol-round" className="grid gap-2">
      {heading && (
        <p className="font-semibold text-slate-900 dark:text-slate-100">
          {round.runoff
            ? t("Runoff (ballot {{n}})", { n: round.ballot_no })
            : t("Ballot {{n}}", { n: round.ballot_no })}
        </p>
      )}
      <p className={muted}>
        {round.named ? t("Named vote") : t("Secret vote")}
        {round.opened_at && round.closed_at && (
          <>
            {" · "}
            {t("Vote: {{start}}–{{end}}", {
              start: time.format(new Date(round.opened_at)),
              end: time.format(new Date(round.closed_at)),
            })}
          </>
        )}
        {item.kind === "election" && round.max_votes !== null && round.max_votes >= 2 && (
          <>
            {" · "}
            {t("Up to {{count}} votes per person", { count: round.max_votes })}
            {round.cumulate && t(", cumulating allowed")}
          </>
        )}
      </p>
      <ul className="flex flex-wrap gap-x-4 gap-y-0.5 text-slate-800 dark:text-slate-200">
        {round.options.map((option) => (
          <li key={option.key}>
            {label(option.key)}: <strong>{result.total.counts[option.key] ?? 0}</strong>
          </li>
        ))}
      </ul>
      <p className={muted}>
        {t("{{voted}} of {{eligible}} eligible voters voted", {
          voted: result.total.voted,
          eligible: result.total.eligible,
        })}
      </p>
      {result.groups.length > 1 && (
        <ul className={`grid gap-0.5 text-xs ${muted}`}>
          {result.groups.map((group) => (
            <li key={group.name}>
              {group.name} ({group.voted}/{group.eligible}):{" "}
              {round.options
                .map((option) => `${label(option.key)} ${group.counts[option.key] ?? 0}`)
                .join(", ")}
            </li>
          ))}
        </ul>
      )}
      {!result.count_check_ok && (
        <p role="alert" className="font-semibold text-red-700 dark:text-red-400">
          {t("Count check failed: {{voted}} marked as voted, {{tally}} ballots counted.", {
            voted: result.voted,
            tally: result.tally_sum,
          })}
        </p>
      )}
      {round.voters.length > 0 && (
        <p className="text-slate-800 dark:text-slate-200">
          {t("Voted: {{names}}", { names: round.voters.map((voter) => voter.name).join(", ") })}
        </p>
      )}
      {round.named && round.named_votes.length > 0 && (
        <ul className="grid gap-0.5 text-slate-800 dark:text-slate-200">
          {round.named_votes.map((vote, index) => (
            <li key={index}>
              {vote.member} ({vote.group}): {vote.keys.map(label).join(", ")}
            </li>
          ))}
        </ul>
      )}
      {round.texts.length > 0 && (
        <ul className="grid gap-1 text-slate-800 dark:text-slate-200">
          {round.texts.map((entry, index) => (
            <li key={index} className="break-words">
              <span className={muted}>({entry.group})</span> {entry.text}
            </li>
          ))}
        </ul>
      )}
      {round.finding && (
        <p className="font-semibold text-slate-900 dark:text-slate-100">
          {round.finding === "adopted" ? t("Finding: adopted") : t("Finding: rejected")}
        </p>
      )}
      {!round.reference && round.result && (
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {t("No seal: this vote was closed before seals were introduced.")}
        </p>
      )}
      {round.reference && (
        <div
          data-testid="protocol-seal"
          className="grid gap-0.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600 break-inside-avoid dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400"
        >
          <p className="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
            <ShieldCheck aria-hidden className="h-4 w-4" />
            {t("Seal")}
          </p>
          <p>
            {t("Reference")}:{" "}
            {roomId ? (
              <Link
                to={`/rooms/${roomId}/seals?reference=${encodeURIComponent(round.reference)}`}
                className="font-mono underline print:no-underline"
              >
                {round.reference}
              </Link>
            ) : (
              <span className="font-mono">{round.reference}</span>
            )}
          </p>
          {round.fingerprint && (
            <p>
              {t("Fingerprint")}:{" "}
              <span className="break-all font-mono">{fingerprintBlocks(round.fingerprint)}</span>
            </p>
          )}
          {round.finding_fingerprint && (
            <p>
              {t("Fingerprint of the finding")}:{" "}
              <span className="break-all font-mono">
                {fingerprintBlocks(round.finding_fingerprint)}
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
