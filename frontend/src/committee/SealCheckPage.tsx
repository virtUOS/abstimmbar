// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Committee rooms (Gremien-Raum): checks a seal reference from a protocol
 *  against the room's hash chain — is the sealed result still unchanged, was
 *  it discarded by a repeated vote, and is the whole chain intact. */
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams, useSearchParams } from "react-router";
import { localizedText } from "@basicbar/ui";
import { api, requestError, type Room, type SealLinkStatus, type SealVerification } from "../api";
import HomeCrumb from "../components/HomeCrumb";
import { ChevronDown, ShieldCheck } from "lucide-react";
import { Button, Field, TextInput } from "../components/ui";

const STATUS_TEXT: Record<SealLinkStatus, string> = {
  valid: "Matches the seal.",
  altered: "Changed after sealing!",
  discarded: "Discarded (vote repeated).",
  deleted: "Meeting deleted.",
};

const STATUS_STYLE: Record<SealLinkStatus, string> = {
  valid: "text-emerald-700 dark:text-emerald-400",
  altered: "font-semibold text-red-700 dark:text-red-400",
  discarded: "text-slate-600 dark:text-slate-400",
  deleted: "text-slate-600 dark:text-slate-400",
};

const KIND_TEXT = {
  result: "Result",
  finding: "Finding",
  discard: "Vote discarded",
} as const;

export default function SealCheckPage() {
  const { t } = useTranslation();
  const { roomId } = useParams();
  const [params] = useSearchParams();
  const [room, setRoom] = useState<Room | null>(null);
  const [reference, setReference] = useState(params.get("reference") ?? "");
  const [fingerprint, setFingerprint] = useState("");
  const [result, setResult] = useState<SealVerification | null>(null);
  const [checked, setChecked] = useState({ reference: "", fingerprint: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api.getRoom(Number(roomId)).then(setRoom).catch(() => setRoom(null));
  }, [roomId]);

  const check = () => {
    setBusy(true);
    setError("");
    const values = { reference: reference.trim(), fingerprint: fingerprint.trim() };
    api
      .verifySeal(Number(roomId), values.reference, values.fingerprint)
      .then((data) => {
        setResult(data);
        setChecked(values);
      })
      .catch((err) => {
        setResult(null);
        setError(t(requestError(err)));
      })
      .finally(() => setBusy(false));
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    check();
  };

  // Opened from a protocol ("Reference" link): check right away.
  useEffect(() => {
    if (params.get("reference")) check();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="mx-auto max-w-2xl">
      <nav className="mb-4 text-sm text-slate-500 dark:text-slate-400">
        <HomeCrumb /> /{" "}
        {room ? (
          <Link to={`/rooms/${roomId}`} className="hover:underline">
            {localizedText(room.title)}
          </Link>
        ) : (
          "…"
        )}{" "}
        / {t("Check seal")}
      </nav>
      <h1 className="mb-4 text-xl font-semibold text-slate-900 dark:text-slate-100">
        {t("Check seal")}
      </h1>
      {/* Open on a direct visit; folded when arriving from a protocol link,
          so the result is in view. */}
      <details
        data-testid="seal-guide"
        open={!params.get("reference")}
        className="group mb-6 rounded-xl border border-brand-200 bg-brand-50/60 p-4 text-sm text-slate-700 dark:border-brand-900 dark:bg-brand-950/30 dark:text-slate-300"
      >
        <summary className="flex cursor-pointer list-none items-center gap-2 font-semibold text-slate-900 dark:text-slate-100">
          <ShieldCheck aria-hidden className="h-4 w-4 text-brand-700 dark:text-brand-300" />
          {t("What does this page do?")}
          <ChevronDown aria-hidden className="ml-auto h-4 w-4 transition-transform group-open:rotate-180" />
        </summary>
        <div className="mt-2 grid gap-2">
        <p>
          {t(
            "When a vote is closed, Abstimmbar seals its result: it computes a fingerprint from the result and links it to the previous seal of this room, like a chain. Every later change to a stored result changes its fingerprint — so you can check whether a result in a protocol is still exactly what was decided.",
          )}
        </p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>{t("Take the reference of a vote from the protocol, e.g. “G42-20261104-TOP3a” (in the protocol you can also click it).")}</li>
          <li>{t("Optional: enter the fingerprint printed next to it — at least the first 16 characters. This also checks that the printed protocol matches the stored result.")}</li>
          <li>{t("Click “Check”.")}</li>
        </ol>
        <p className="font-medium text-slate-900 dark:text-slate-100">{t("What the results mean:")}</p>
        <ul className="list-disc space-y-1 pl-5">
          <li>{t("“Matches the seal”: the stored result is unchanged.")}</li>
          <li>{t("“Changed after sealing”: the stored data no longer matches — please inform the administrators.")}</li>
          <li>{t("“Discarded”: the vote was reset and repeated; the repeated vote has its own reference ending in “-W2”.")}</li>
          <li>{t("“Chain intact”: no seal of this room has been removed or altered.")}</li>
        </ul>
        </div>
      </details>
      <form onSubmit={submit} className="grid gap-3">
        <Field label={t("Reference")}>
          <TextInput
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            required
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <Field label={t("Fingerprint (optional)")}>
          <TextInput
            value={fingerprint}
            onChange={(event) => setFingerprint(event.target.value)}
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
          />
        </Field>
        <div>
          <Button type="submit" variant="primary" disabled={busy || !reference.trim()}>
            {t("Check")}
          </Button>
        </div>
      </form>

      {error && (
        <p role="alert" className="mt-4 text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}

      {result && (
        <section aria-live="polite" className="mt-6 grid gap-3">
          <h2 className="break-all font-mono text-sm text-slate-600 dark:text-slate-400">
            {checked.reference}
          </h2>
          {!result.found ? (
            <p className="text-sm text-slate-700 dark:text-slate-300">
              {t("No seal found for this reference.")}
            </p>
          ) : (
            <ul className="grid gap-2">
              {result.links.map((link) => (
                <li
                  key={link.seq}
                  className="min-w-0 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-800"
                >
                  <div className="font-medium text-slate-900 dark:text-slate-100">
                    {t(KIND_TEXT[link.kind])} · #{link.seq}
                  </div>
                  <div className={STATUS_STYLE[link.status]}>{t(STATUS_TEXT[link.status])}</div>
                  <div className="mt-1 break-all font-mono text-xs text-slate-500 dark:text-slate-400">
                    {link.hash}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {result.fingerprint_matches !== null && (
            <p
              className={`text-sm ${result.fingerprint_matches ? "text-emerald-700 dark:text-emerald-400" : "font-semibold text-red-700 dark:text-red-400"}`}
            >
              {result.fingerprint_matches
                ? t("The fingerprint matches.")
                : t("The fingerprint does not match.")}
            </p>
          )}
          <p
            className={`text-sm ${result.chain_intact ? "text-emerald-700 dark:text-emerald-400" : "font-semibold text-red-700 dark:text-red-400"}`}
          >
            {result.chain_intact ? t("Chain intact.") : t("Chain broken!")}
          </p>
        </section>
      )}
    </div>
  );
}
