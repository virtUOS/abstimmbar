// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** The beamer picture of a running meeting (Gremien-Raum): the shown agenda
 *  item with its version, the vote status and — while a vote is open — only
 *  the participation per group; after closing, the count per group and in
 *  total, and released free texts. Pure presentation of `MeetingPublic`.
 *
 *  Never shows names (§ 8): attendance lives only in the console's panel.
 *  Content (motion text, options, group names) is canonical-language plain
 *  data from the server — not run through `localizedText`. */
import { useTranslation } from "react-i18next";
import { Lock, UserRound } from "lucide-react";
import { RichText } from "@basicbar/ui";
import type { MeetingBallot, MeetingCounts, MeetingItem, MeetingPublic, MeetingText } from "../api";

const pct = (n: number, of: number) => (of > 0 ? Math.round((n / of) * 100) : 0);

/** Count keys in display order; unknown keys are appended. */
function answerKeys(item: MeetingItem, counts: MeetingCounts): string[] {
  const keys =
    item.kind === "resolution"
      ? ["yes", "no", "abstain"]
      : item.kind === "open_text"
        ? ["text", "abstain"]
        : [...item.options.map((option) => `opt:${option.id}`), "abstain"];
  for (const key of Object.keys(counts)) if (!keys.includes(key)) keys.push(key);
  return keys;
}

export function useAnswerLabel() {
  const { t } = useTranslation();
  return (item: MeetingItem, key: string): string => {
    if (key === "yes") return t("Yes");
    if (key === "no") return t("No");
    if (key === "abstain") return t("Abstention");
    if (key === "text") return t("Answers");
    if (key.startsWith("opt:")) {
      const option = item.options.find((o) => `opt:${o.id}` === key);
      if (option) return option.text;
    }
    return key;
  };
}

/** Group id → name, from the ballot's progress and result. */
export function groupNames(ballot: MeetingBallot | null): Map<number, string> {
  const names = new Map<number, string>();
  for (const group of ballot?.progress.groups ?? []) names.set(group.id, group.name);
  for (const group of ballot?.result?.groups ?? []) names.set(group.id, group.name);
  return names;
}

function Bar({ value, className = "bg-brand-500" }: { value: number; className?: string }) {
  return (
    <div className="h-3 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
      <div className={`h-full rounded-full ${className}`} style={{ width: `${value}%` }} />
    </div>
  );
}

function Progress({ ballot }: { ballot: MeetingBallot }) {
  const { t } = useTranslation();
  const { voted, eligible, groups } = ballot.progress;
  return (
    <div className="grid gap-4">
      <p className="text-2xl font-semibold tabular-nums md:text-3xl" data-testid="beamer-progress">
        {t("{{voted}} of {{eligible}} voted", { voted, eligible })}
      </p>
      <Bar value={pct(voted, eligible)} />
      {groups.length > 1 && (
        <ul className="grid gap-3">
          {groups.map((group) => (
            <li key={group.id} className="grid gap-1">
              <span className="flex justify-between gap-3 text-base md:text-lg">
                <span className="min-w-0 break-words">{group.name}</span>
                <span className="shrink-0 tabular-nums text-slate-500 dark:text-slate-400">
                  {group.voted} / {group.eligible}
                </span>
              </span>
              <Bar value={pct(group.voted, group.eligible)} className="bg-brand-400" />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Result({ item, ballot }: { item: MeetingItem; ballot: MeetingBallot }) {
  const { t } = useTranslation();
  const label = useAnswerLabel();
  const result = ballot.result;
  if (!result) return null;
  const totalKeys = answerKeys(item, result.total.counts);
  const sum = totalKeys.reduce((acc, key) => acc + (result.total.counts[key] ?? 0), 0);
  return (
    <div className="grid gap-6" data-testid="beamer-result">
      <div className="grid gap-3">
        <h2 className="text-lg font-semibold text-slate-500 dark:text-slate-400">{t("Total")}</h2>
        <ul className="grid gap-3">
          {totalKeys.map((key) => {
            const n = result.total.counts[key] ?? 0;
            return (
              <li key={key} className="grid gap-1">
                <span className="flex justify-between gap-3 text-xl md:text-2xl">
                  <span className="min-w-0 break-words">{label(item, key)}</span>
                  <span className="shrink-0 font-semibold tabular-nums">{n}</span>
                </span>
                <Bar value={pct(n, sum)} />
              </li>
            );
          })}
        </ul>
      </div>
      {result.groups.length > 1 && (
        <ul className="grid gap-2 border-t border-slate-200 pt-4 dark:border-slate-800">
          {result.groups.map((group) => (
            <li key={group.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
              <span className="font-semibold">{group.name}</span>
              {answerKeys(item, group.counts).map((key) => (
                <span key={key} className="text-slate-600 dark:text-slate-300">
                  {label(item, key)}{" "}
                  <span className="font-semibold tabular-nums text-slate-900 dark:text-slate-100">
                    {group.counts[key] ?? 0}
                  </span>
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TextList({ texts, names }: { texts: MeetingText[]; names: Map<number, string> }) {
  return (
    <ul className="grid gap-2">
      {texts.map((entry, index) => (
        <li
          key={index}
          className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800"
        >
          {entry.group !== null && names.get(entry.group) && (
            <span className="block text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              {names.get(entry.group)}
            </span>
          )}
          <span className="whitespace-pre-wrap break-words">{entry.text}</span>
        </li>
      ))}
    </ul>
  );
}

export default function MeetingBeamer({ data }: { data: MeetingPublic }) {
  const { t } = useTranslation();
  const item = data.item;
  const ballot = item?.ballot ?? null;
  return (
    <div className="flex h-full min-h-0 flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <header className="shrink-0 px-6 pt-5 text-sm font-medium text-slate-500 dark:text-slate-400 md:px-10">
        <span className="break-words">{data.meeting.title}</span>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-6 md:px-10">
        {!item && data.top ? (
          <div key={`top-${data.top.number}`} className="ab-fade-in mx-auto grid max-w-4xl gap-6">
            <span className="justify-self-start rounded-full bg-brand-100 px-3 py-1 text-sm font-semibold text-brand-900 dark:bg-brand-900/40 dark:text-brand-100">
              {t("TOP {{number}}", { number: data.top.number })}
            </span>
            {data.top.title && (
              <h1 className="break-words text-3xl font-semibold leading-snug md:text-5xl">
                {data.top.title}
              </h1>
            )}
            {data.top.description && (
              <RichText
                className="break-words text-xl leading-snug md:text-3xl [&_img]:my-4 [&_img]:max-h-64 [&_ol]:list-decimal [&_ol]:pl-8 [&_ul]:list-disc [&_ul]:pl-8"
                html={data.top.description}
              />
            )}
          </div>
        ) : !item ? (
          <div className="flex h-full items-center justify-center text-center">
            <p className="text-2xl text-slate-500 dark:text-slate-400 md:text-3xl">
              {t("Waiting for the next item")}
            </p>
          </div>
        ) : (
          <div key={item.id} className="ab-fade-in mx-auto grid max-w-4xl gap-8">
            <div className="grid gap-4">
              <div className="flex flex-wrap items-center gap-2">
                <span className="rounded-full bg-brand-100 px-3 py-1 text-sm font-semibold text-brand-900 dark:bg-brand-900/40 dark:text-brand-100">
                  {t("TOP {{number}}", { number: item.label })}
                </span>
                {data.top?.title && (
                  <span className="min-w-0 break-words text-base font-semibold text-slate-700 dark:text-slate-200">
                    {data.top.title}
                  </span>
                )}
                {item.version !== null && (
                  <span
                    className={`rounded-full border px-3 py-1 text-sm ${
                      item.changed
                        ? "border-amber-300 text-amber-800 dark:border-amber-700 dark:text-amber-300"
                        : "border-slate-300 text-slate-600 dark:border-slate-700 dark:text-slate-300"
                    }`}
                  >
                    {item.changed
                      ? t("Version {{n}} · changed", { n: item.version })
                      : t("Version {{n}}", { n: item.version })}
                  </span>
                )}
              </div>
              <RichText
                className="break-words text-2xl font-semibold leading-snug md:text-4xl [&_img]:my-4 [&_img]:max-h-64 [&_ol]:list-decimal [&_ol]:pl-8 [&_ul]:list-disc [&_ul]:pl-8"
                html={item.text}
              />
              {item.bundle.length > 0 && (
                <div className="grid gap-4">
                  {item.bundle.map((extra) => (
                    <div key={extra.id} className="grid gap-2">
                      <span className="justify-self-start rounded-full bg-brand-100 px-3 py-1 text-sm font-semibold text-brand-900 dark:bg-brand-900/40 dark:text-brand-100">
                        {t("TOP {{number}}", { number: extra.label })}
                      </span>
                      <RichText
                        className="break-words text-xl leading-snug md:text-3xl [&_img]:my-4 [&_img]:max-h-64 [&_ol]:list-decimal [&_ol]:pl-8 [&_ul]:list-disc [&_ul]:pl-8"
                        html={extra.text}
                      />
                    </div>
                  ))}
                  <p className="text-lg text-slate-600 dark:text-slate-300">
                    {t("One vote for all of these resolutions.")}
                  </p>
                </div>
              )}
              {item.options.length > 0 && !ballot?.result && (
                <ol className="grid gap-2 text-lg md:text-2xl">
                  {item.options.map((option, index) => (
                    <li key={option.id} className="flex gap-3">
                      <span className="font-semibold text-slate-400">{index + 1}.</span>
                      <span className="min-w-0 break-words">{option.text}</span>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            {ballot?.status === "open" && (
              <section className="grid gap-4">
                <p className="inline-flex items-center gap-2 text-lg font-semibold text-emerald-700 dark:text-emerald-400 md:text-xl">
                  {item.named ? (
                    <UserRound aria-hidden className="h-5 w-5" />
                  ) : (
                    <Lock aria-hidden className="h-5 w-5" />
                  )}
                  {item.named ? t("Vote in progress · named") : t("Vote in progress · secret")}
                </p>
                <Progress ballot={ballot} />
              </section>
            )}
            {ballot?.status === "closed" && <Result item={item} ballot={ballot} />}
            {ballot?.status === "closed" && ballot.finding && (
              <p
                data-testid="beamer-finding"
                className={`inline-flex w-fit rounded-full px-4 py-1.5 text-xl font-semibold md:text-2xl ${
                  ballot.finding === "adopted"
                    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                    : "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300"
                }`}
              >
                {ballot.finding === "adopted" ? t("Adopted") : t("Rejected")}
              </p>
            )}
            {ballot?.texts && ballot.texts.length > 0 && (
              <section className="grid gap-3">
                <h2 className="text-lg font-semibold text-slate-500 dark:text-slate-400">
                  {t("Answers")}
                </h2>
                <TextList texts={ballot.texts} names={groupNames(ballot)} />
              </section>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
