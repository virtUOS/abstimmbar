// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee rooms (Gremien-Raum): the printable protocol of an ended
 *  meeting — attendance, substitutions, and per agenda item the text, the
 *  count, the finding and the seal reference. Printing (or "save as PDF")
 *  hides the app chrome and renders black on white. */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";
import { Printer } from "lucide-react";
import { RichText } from "@basicbar/ui";
import {
  api,
  requestBody,
  requestError,
  type MeetingProtocol,
  type ProtocolItem,
} from "../api";
import HomeCrumb from "../components/HomeCrumb";
import { Button } from "../components/ui";

/** 64 hex characters as 4 blocks of 16. */
function fingerprintBlocks(hash: string): string {
  return (hash.match(/.{1,16}/g) ?? [hash]).join(" ");
}

function answerLabel(
  t: (key: string) => string,
  item: ProtocolItem,
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
              <Button
                variant="secondary"
                className="inline-flex shrink-0 items-center gap-1.5 print:hidden"
                onClick={() => window.print()}
              >
                <Printer aria-hidden className="h-4 w-4" />
                {t("Print / save as PDF")}
              </Button>
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
                        className="mt-0.5 text-sm text-slate-600 dark:text-slate-400"
                      />
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
            {t("Verification: Abstimmbar → Room → Check seal")}
          </p>
        </article>
      )}
    </div>
  );
}

function ItemBlock({ item, roomId }: { item: ProtocolItem; roomId: number | null }) {
  const { t, i18n } = useTranslation();
  const time = new Intl.DateTimeFormat(i18n.language, { timeStyle: "short" });
  const label = (key: string) => answerLabel(t as (key: string) => string, item, key);
  const result = item.result;
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

      {item.status === "not_voted" || !result ? (
        <p className={muted}>{t("Not voted")}</p>
      ) : (
        <>
          <p className={muted}>
            {item.named ? t("Named vote") : t("Secret vote")}
            {item.opened_at && item.closed_at && (
              <>
                {" · "}
                {t("Vote: {{start}}–{{end}}", {
                  start: time.format(new Date(item.opened_at)),
                  end: time.format(new Date(item.closed_at)),
                })}
              </>
            )}
          </p>
          <ul className="flex flex-wrap gap-x-4 gap-y-0.5 text-slate-800 dark:text-slate-200">
            {item.options.map((option) => (
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
                  {item.options
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
          {item.voters.length > 0 && (
            <p className="text-slate-800 dark:text-slate-200">
              {t("Voted: {{names}}", { names: item.voters.map((voter) => voter.name).join(", ") })}
            </p>
          )}
          {item.named && item.named_votes.length > 0 && (
            <ul className="grid gap-0.5 text-slate-800 dark:text-slate-200">
              {item.named_votes.map((vote, index) => (
                <li key={index}>
                  {vote.member} ({vote.group}): {vote.keys.map(label).join(", ")}
                </li>
              ))}
            </ul>
          )}
          {item.texts.length > 0 && (
            <ul className="grid gap-1 text-slate-800 dark:text-slate-200">
              {item.texts.map((entry, index) => (
                <li key={index} className="break-words">
                  <span className={muted}>({entry.group})</span> {entry.text}
                </li>
              ))}
            </ul>
          )}
          {item.finding && (
            <p className="font-semibold text-slate-900 dark:text-slate-100">
              {item.finding === "adopted" ? t("Finding: adopted") : t("Finding: rejected")}
            </p>
          )}
          {item.reference && (
            <div className={`grid gap-0.5 border-t border-slate-100 pt-2 text-xs dark:border-slate-800 ${muted}`}>
              <p>
                {t("Reference")}:{" "}
                {roomId ? (
                  <Link
                    to={`/rooms/${roomId}/seals?reference=${encodeURIComponent(item.reference)}`}
                    className="font-mono underline print:no-underline"
                  >
                    {item.reference}
                  </Link>
                ) : (
                  <span className="font-mono">{item.reference}</span>
                )}
              </p>
              {item.finding_fingerprint && (
                <p>
                  {t("Fingerprint of the finding")}:{" "}
                  <span className="break-all font-mono">
                    {fingerprintBlocks(item.finding_fingerprint)}
                  </span>
                </p>
              )}
              {item.fingerprint && (
                <p>
                  {t("Fingerprint")}:{" "}
                  <span className="break-all font-mono">{fingerprintBlocks(item.fingerprint)}</span>
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
