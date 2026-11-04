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

  const submit = (event: FormEvent) => {
    event.preventDefault();
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
