# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""The protocol of an ended meeting as a PDF (same content and order as the protocol page).

Built from ``protocol.build()`` — so the secrecy rules of § 8 hold here too (no vote
timestamps, a secret ballot lists only who voted). Labels follow the request language.
"""
from datetime import datetime

from django.utils import formats, timezone
from django.utils.text import slugify
from django.utils.translation import get_language, gettext as _, gettext_lazy

from common.i18n_fields import translated_map
from common.pdf import PdfDocument
from rooms.models import QuestionSet

from . import protocol
from .models import MeetingControl
from .payloads import _canonical

FIXED_KEYS = {
    "yes": gettext_lazy("Yes"), "no": gettext_lazy("No"),
    "abstain": gettext_lazy("Abstention"), "text": gettext_lazy("Answers"),
}


def _local(value: str | None):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if timezone.is_aware(parsed):
        parsed = timezone.localtime(parsed)
    return parsed


def _date_time(value: str | None) -> str:
    local = _local(value)
    if not local:
        return ""
    if (get_language() or "").startswith("de"):
        return formats.date_format(local, "j. F Y, H:i")  # "15. Januar 2030, 11:00"
    return formats.date_format(local, "DATETIME_FORMAT")


def _time(value: str | None) -> str:
    local = _local(value)
    return formats.time_format(local, "H:i") if local else ""


def _fingerprint(hash_: str) -> str:
    """64 hex characters as 4 blocks of 16."""
    return " ".join(hash_[i:i + 16] for i in range(0, len(hash_), 16))


def _label(item: dict, key: str) -> str:
    if key in FIXED_KEYS:
        return str(FIXED_KEYS[key])
    return next((o["text"] for o in item["options"] if o["key"] == key), key)


def _item(doc: PdfDocument, item: dict) -> None:
    def build(doc: PdfDocument) -> None:
        doc.rule()
        doc.paragraph(_("TOP %(number)s") % {"number": item["label"]}, style="bold")
        doc.rich(item["text"])
        if item["version_changed"] and item["version"]:
            doc.paragraph(
                _("Version %(n)s – differs from the version at the start of the meeting")
                % {"n": item["version"]}, style="muted",
            )
        for rnd in item["rounds_discarded"]:
            if rnd["reason"] == "restart":
                doc.paragraph(_("Interrupted by a server restart"), style="muted")
            else:
                doc.paragraph(
                    _("Vote repeated (round %(round)s): %(comment)s")
                    % {"round": rnd["round"], "comment": rnd["comment"]}, style="muted",
                )
        if item["bundle_with"]:
            doc.paragraph(
                _("Voted en bloc with TOP %(labels)s") % {"labels": ", ".join(item["bundle_with"])},
                style="muted",
            )
        result = item["result"]
        if item["status"] == "not_voted" or not result:
            doc.paragraph(_("Not voted"), style="muted")
            return
        kind = _("Named vote") if item["named"] else _("Secret vote")
        if item["opened_at"] and item["closed_at"]:
            kind += " · " + _("Vote: %(start)s–%(end)s") % {
                "start": _time(item["opened_at"]), "end": _time(item["closed_at"]),
            }
        doc.paragraph(kind, style="muted")
        counts = result["total"]["counts"]
        doc.paragraph(
            "   ".join(f"{_label(item, o['key'])}: {counts.get(o['key'], 0)}" for o in item["options"]),
            style="bold",
        )
        doc.paragraph(
            _("%(voted)s of %(eligible)s eligible voters voted")
            % {"voted": result["total"]["voted"], "eligible": result["total"]["eligible"]},
            style="muted",
        )
        if len(result["groups"]) > 1:
            for group in result["groups"]:
                parts = ", ".join(
                    f"{_label(item, o['key'])} {group['counts'].get(o['key'], 0)}"
                    for o in item["options"]
                )
                doc.paragraph(f"{group['name']} ({group['voted']}/{group['eligible']}): {parts}",
                              style="small")
        if not result["count_check_ok"]:
            doc.paragraph(
                _("Count check failed: %(voted)s marked as voted, %(tally)s ballots counted.")
                % {"voted": result["voted"], "tally": result["tally_sum"]}, style="bold",
            )
        if item["voters"]:
            doc.paragraph(_("Voted: %(names)s") % {"names": ", ".join(v["name"] for v in item["voters"])})
        if item["named"] and item["named_votes"]:
            doc.bullets([
                f"{v['member']} ({v['group']}): {', '.join(_label(item, k) for k in v['keys'])}"
                for v in item["named_votes"]
            ])
        if item["texts"]:
            doc.bullets([f"({t['group']}) {t['text']}" for t in item["texts"]])
        if item["finding"]:
            doc.paragraph(
                _("Finding: adopted") if item["finding"] == "adopted" else _("Finding: rejected"),
                style="bold",
            )
        if not item["reference"]:
            doc.paragraph(_("No seal: this vote was closed before seals were introduced."), style="muted")
        else:
            def seal(doc: PdfDocument) -> None:
                doc.paragraph(_("Seal"), style="bold")
                doc.paragraph(f"{_('Reference')}: {item['reference']}", style="small")
                if item["fingerprint"]:
                    doc.paragraph(f"{_('Fingerprint')}: {_fingerprint(item['fingerprint'])}", style="small")
                if item["finding_fingerprint"]:
                    doc.paragraph(
                        f"{_('Fingerprint of the finding')}: {_fingerprint(item['finding_fingerprint'])}",
                        style="small",
                    )
            doc.box(seal)

    doc.keep_together(build)
    doc.spacer(mm=2)


def render(meeting: QuestionSet) -> bytes:
    """PDF bytes; raises ValidationError(code="not_ended") like ``protocol.build``."""
    data = protocol.build(meeting)
    doc = PdfDocument(
        f"{_('Protocol')}: {data['title']}", footer_left=f"{data['committee']} – {data['title']}",
    )
    doc.paragraph(data["committee"], style="muted")
    doc.heading(f"{_('Protocol')}: {data['title']}", 1)
    when = [
        _date_time(data["scheduled_at"]),
        _("Start: %(time)s") % {"time": _time(data["started_at"])} if data["started_at"] else "",
        _("End: %(time)s") % {"time": _time(data["ended_at"])} if data["ended_at"] else "",
    ]
    doc.paragraph(" · ".join(part for part in when if part), style="muted")

    attendance = data["attendance"]
    doc.heading(_("Attendance"), 2)
    if attendance["present"]:
        rows = []
        for person in attendance["present"]:
            line = f"{person['name']} ({person['group']})"
            if person["left"]:
                line += " – " + (
                    _("left after TOP %(label)s") % {"label": person["left_after"]}
                    if person["left_after"] else _("left")
                )
            rows.append(line)
        doc.bullets(rows)
    else:
        doc.paragraph("—")
    if attendance["substitutions"]:
        doc.heading(_("Substitutions"), 2)
        lines = []
        for sub in attendance["substitutions"]:
            values = {"deputy": sub["deputy"], "absent": sub["absent"], "group": sub["group"],
                      "label": sub["from_label"]}
            lines.append(
                _("%(deputy)s substitutes %(absent)s (%(group)s) from TOP %(label)s") % values
                if sub["from_label"] else _("%(deputy)s substitutes %(absent)s (%(group)s)") % values
            )
        doc.bullets(lines)
    if attendance["observers"]:
        doc.heading(_("Observers"), 2)
        doc.paragraph(", ".join(attendance["observers"]))

    doc.heading(_("Agenda"), 2)
    for top in data["tops"]:
        if top["title"]:
            doc.heading(_("TOP %(number)s") % {"number": top["number"]} + f" – {top['title']}", 3)
            if top["description"]:
                doc.rich(top["description"])
        for item in top["items"]:
            _item(doc, item)
    doc.spacer(mm=2)
    doc.paragraph(
        # Helvetica has no arrow glyph
        _("Every result in this protocol is sealed. With its reference and fingerprint, anyone "
          "managing the room can check under Abstimmbar → Room → “Check seal” whether the result "
          "was changed afterwards.").replace("→", "›"),
        style="muted",
    )
    return doc.render()


def filename(meeting: QuestionSet) -> str:
    slug = slugify(_canonical(translated_map(meeting, "title"))) or "meeting"
    when = meeting.scheduled_at
    if not when:
        control = MeetingControl.objects.filter(meeting_id=meeting.pk).first()
        when = control.started_at if control else None
    parts = [_("Protocol"), slug]
    if when:
        parts.append(timezone.localtime(when).date().isoformat())
    return "-".join(parts) + ".pdf"
