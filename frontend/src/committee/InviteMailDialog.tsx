// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Universität Osnabrück (virtUOS)

/** Dialog of the personal-links table: send each member their link by
 *  e-mail. The server adds date and link in the member's language; subject
 *  and message are not stored. The recipient count mirrors the backend:
 *  valid links with an address, not yet mailed unless "send again". */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { InviteMailResult, MeetingInvite } from "../api";
import { Button } from "../components/ui";
import { Modal } from "./MeetingAgenda";

export interface InviteMailBody {
  subject: string;
  message: string;
  resend: boolean;
}

const INPUT_CLASS =
  "w-full rounded-lg border border-field bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-brand-600 dark:bg-slate-900 dark:text-slate-100";

export function isValidInvite(invite: MeetingInvite): boolean {
  return invite.state === "waiting" || invite.state === "active";
}

export default function InviteMailDialog({
  title,
  invites,
  busy,
  onSend,
  onSent,
  onCancel,
}: {
  /** Meeting title (UI language) for the subject prefill. */
  title: string;
  invites: MeetingInvite[];
  busy: boolean;
  /** Sends; reports errors through `setError`, resolves null on failure. */
  onSend: (body: InviteMailBody, setError: (text: string) => void) => Promise<InviteMailResult | null>;
  onSent: (result: InviteMailResult) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [subject, setSubject] = useState(() => t("Invitation: {{title}}", { title }));
  const [message, setMessage] = useState("");
  const [resend, setResend] = useState(false);
  const [error, setError] = useState("");
  const [sending, setSending] = useState(false);

  const valid = invites.filter(isValidInvite);
  const recipients = valid.filter(
    (invite) => invite.member.email && (resend || invite.mailed_at === null),
  ).length;
  const withoutEmail = valid.filter((invite) => !invite.member.email).length;

  async function submit() {
    setSending(true);
    const result = await onSend(
      { subject: subject.trim(), message: message.trim(), resend },
      setError,
    );
    setSending(false);
    if (result) onSent(result);
  }

  return (
    <Modal label={t("Invite by e-mail")} onCancel={onCancel}>
      {/* No <form>: Enter in the subject must not send mails right away. */}
      <div className="grid gap-3">
        <h2 className="font-semibold text-slate-900 dark:text-slate-100">{t("Invite by e-mail")}</h2>
        <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
          {t("Subject")}
          <input
            type="text"
            autoFocus
            value={subject}
            maxLength={200}
            onChange={(event) => setSubject(event.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700 dark:text-slate-300">
          {t("Message (optional)")}
          <textarea
            value={message}
            maxLength={5000}
            rows={5}
            aria-describedby="invite-mail-hint"
            onChange={(event) => setMessage(event.target.value)}
            className={INPUT_CLASS}
          />
        </label>
        <p id="invite-mail-hint" className="-mt-1 text-xs text-slate-500 dark:text-slate-400">
          {t("Date and personal link are added automatically – in the member's language.")}
        </p>
        <label className="flex items-start gap-2 text-sm text-slate-700 dark:text-slate-200">
          <input
            type="checkbox"
            checked={resend}
            onChange={(event) => setResend(event.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-brand-600"
          />
          {t("Also send again to members already invited")}
        </label>
        <div className="grid gap-0.5 text-sm">
          <p data-testid="mail-recipients" className="font-medium text-slate-800 dark:text-slate-200">
            {t("Goes to {{count}} members", { count: recipients })}
          </p>
          {withoutEmail > 0 && (
            <p className="text-slate-600 dark:text-slate-300">
              {t("{{count}} without an e-mail address – please copy the link.", { count: withoutEmail })}
            </p>
          )}
        </div>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {t("Cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={busy || sending || recipients === 0 || !subject.trim()}
            onClick={() => void submit()}
          >
            {t("Send")}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
