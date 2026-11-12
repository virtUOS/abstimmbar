# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Send each committee member their personal meeting link by e-mail.

Privacy: one message per member with exactly one recipient; subject and
text are not stored (only ``MeetingInvite.mailed_at``); logs carry counts
and exception classes only — never addresses or links.
"""

import logging
import smtplib
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.template.loader import render_to_string
from django.utils import timezone, translation

from common.i18n_fields import resolve_translated_text, translated_map
from rooms.models import QuestionSet

from . import services
from .models import MeetingInvite
from .serializers import invite_url

logger = logging.getLogger(__name__)

_SEND_ERRORS = (smtplib.SMTPException, OSError)


@dataclass
class MailResult:
    sent: list[MeetingInvite] = field(default_factory=list)
    failed: list[MeetingInvite] = field(default_factory=list)
    no_email: list[MeetingInvite] = field(default_factory=list)


def _recipients(meeting: QuestionSet, *, resend: bool, result: MailResult):
    """Valid invites (waiting/active) in CSV order; members without an
    address go to ``result.no_email``."""
    services.ensure_invites(meeting)
    invites = meeting.invites.select_related("member__group").order_by(
        "member__group__position", "member__group_id", "member__name", "id",
    )
    selected = []
    for invite in invites:
        invite.meeting = meeting
        if services.invite_state(invite) not in ("waiting", "active"):
            continue
        if not invite.member.email:
            result.no_email.append(invite)
        elif resend or invite.mailed_at is None:
            selected.append(invite)
    return selected


def _body(meeting: QuestionSet, invite: MeetingInvite, *, request, message: str) -> str:
    with translation.override(invite.member.language):
        scheduled = meeting.scheduled_at
        return render_to_string("committees/mail/invite.txt", {
            "message": message,
            "title": resolve_translated_text(translated_map(meeting, "title")),
            "scheduled_at": timezone.localtime(scheduled) if scheduled else None,
            "url": invite_url(request, invite),
        })


def send_invitations(
    meeting: QuestionSet, *, request, subject: str, message: str, resend: bool,
) -> MailResult:
    result = MailResult()
    invites = _recipients(meeting, resend=resend, result=result)
    if not invites:
        return result
    chair_email = getattr(request.user, "email", "") or ""
    connection = get_connection(fail_silently=False)
    try:
        connection.open()
    except _SEND_ERRORS as exc:
        logger.warning(
            "Invite mail: connection failed (%s), %d not sent", type(exc).__name__, len(invites),
        )
        result.failed = invites
        return result
    errors = set()
    try:
        for invite in invites:
            mail = EmailMessage(
                subject, _body(meeting, invite, request=request, message=message),
                from_email=settings.DEFAULT_FROM_EMAIL, to=[invite.member.email],
                reply_to=[chair_email] if chair_email else [], connection=connection,
            )
            try:
                mail.send()
            except _SEND_ERRORS as exc:
                errors.add(type(exc).__name__)
                result.failed.append(invite)
                continue
            invite.mailed_at = timezone.now()
            MeetingInvite.objects.filter(pk=invite.pk).update(mailed_at=invite.mailed_at)
            result.sent.append(invite)
    finally:
        try:
            connection.close()
        except _SEND_ERRORS:
            pass
    if result.failed:
        logger.warning(
            "Invite mail: %d of %d failed (%s)",
            len(result.failed), len(invites), ", ".join(sorted(errors)),
        )
    return result
