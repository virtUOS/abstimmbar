# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared metric layer for admin statistics (task 2 of the admin-stats-
prometheus feature). ``totals()`` returns current counts, ``daily(since)``
returns dense per-day time series. Consumed by the admin stats API and the
Prometheus exporter (tasks 3/4). Models are imported function-locally:
``common`` is a low-level app imported by rooms/live/lti/accounts, so a
module-level import of those apps here would create an import cycle.
"""
import datetime

from django.db.models import CharField, Count, Exists, OuterRef, Value
from django.db.models.functions import Concat, TruncDate
from django.utils import timezone


def _fill(rows_by_date, since, today, keys=("n",)):
    """rows_by_date: {date_iso: {key: int}} -> dense list since..today."""
    out = []
    day = since
    while day <= today:
        iso = day.isoformat()
        entry = {"date": iso}
        got = rows_by_date.get(iso, {})
        for k in keys:
            entry[k] = int(got.get(k, 0))
        out.append(entry)
        day += datetime.timedelta(days=1)
    return out


def totals():
    from accounts.models import User  # or get_user_model()
    from live.models import Run, Vote
    from lti.models import LtiContextLink
    from rooms.models import Question, QuestionSet, Room

    def _by(qs, field, all_values):
        counts = {r[field]: r["n"] for r in qs.values(field).annotate(n=Count("id"))}
        return {v: int(counts.get(v, 0)) for v in all_values}

    return {
        "rooms": Room.objects.count(),
        "rooms_lti": Room.objects.filter(
            Exists(LtiContextLink.objects.filter(room=OuterRef("pk")))
        ).count(),
        "users": User.objects.count(),
        "sets_by_type": _by(QuestionSet.objects, "type", QuestionSet.SetType.values),
        "questions_by_kind": _by(Question.objects, "kind", Question.Kind.values),
        "runs_by_type": _by(Run.objects, "question_set__type", QuestionSet.SetType.values),
        "participants": Vote.objects.values("token").distinct().count(),
        "questions_run": Vote.objects.values("run", "question").distinct().count(),
    }


def daily(since):
    from accounts.models import DailyModeSession, User
    from live.models import Run, Vote
    from rooms.models import QuestionSet, Room

    today = timezone.localdate()

    def _count_by_day(qs, date_field):
        rows = (qs.annotate(day=TruncDate(date_field)).values("day")
                  .annotate(n=Count("id")).order_by("day"))
        return {r["day"].isoformat(): {"n": r["n"]} for r in rows if r["day"]}

    rooms = _count_by_day(Room.objects.filter(created_at__date__gte=since), "created_at")
    users = _count_by_day(User.objects.filter(date_joined__date__gte=since), "date_joined")

    part_rows = (Vote.objects.filter(created_at__date__gte=since)
                 .annotate(day=TruncDate("created_at")).values("day")
                 .annotate(n=Count("token", distinct=True)))
    participants = {r["day"].isoformat(): {"n": r["n"]} for r in part_rows if r["day"]}

    qr_rows = (Vote.objects.filter(created_at__date__gte=since)
               .annotate(day=TruncDate("created_at")).values("day")
               .annotate(n=Count(Concat("run_id", Value("-"), "question_id",
                                        output_field=CharField()), distinct=True)))
    questions_run = {r["day"].isoformat(): {"n": r["n"]} for r in qr_rows if r["day"]}

    run_rows = (Run.objects.filter(created_at__date__gte=since)
                .annotate(day=TruncDate("created_at"))
                .values("day", "question_set__type").annotate(n=Count("id")))
    runs_by_type = {}
    for r in run_rows:
        if not r["day"]:
            continue
        runs_by_type.setdefault(r["day"].isoformat(), {})[r["question_set__type"]] = r["n"]

    sess_rows = (DailyModeSession.objects.filter(date__gte=since)
                 .values("date", "mode").annotate(n=Count("id")))
    sessions = {}
    for r in sess_rows:
        sessions.setdefault(r["date"].isoformat(), {})[r["mode"]] = r["n"]

    return {
        "rooms": _fill(rooms, since, today),
        "users": _fill(users, since, today),
        "participants": _fill(participants, since, today),
        "questions_run": _fill(questions_run, since, today),
        "runs_by_type": _fill(runs_by_type, since, today, keys=QuestionSet.SetType.values),
        "sessions_by_mode": _fill(sessions, since, today, keys=("easy", "pro")),
    }
