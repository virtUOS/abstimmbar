# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""SSE streams of a running meeting (ADR-0003 pattern, own hub).

One hub keyed by meeting pk with two roles: ``public`` (beamer and ballot
pages) and ``manager`` (console). Every event is a full snapshot from
``payloads``. Writers call ``notify`` — it broadcasts once the transaction
has committed, so the snapshot sees the committed state.
"""
import asyncio

from asgiref.sync import sync_to_async
from django.db import connections, transaction
from django.http import Http404, JsonResponse, StreamingHttpResponse

from live.hub import RoomHub, sse_frame
from live.views import KEEPALIVE_FRAME, KEEPALIVE_SECONDS
from rooms.models import QuestionSet

from . import ballots, payloads, services
from .presence import presence

meeting_hub = RoomHub()


def broadcast_meeting(meeting: QuestionSet, debounce=False) -> None:
    meeting_id = meeting.pk

    def _build():
        # Runs in the hub's executor thread: give the pooled connection back
        # right away instead of parking it on a long-lived thread.
        try:
            fresh = QuestionSet.objects.filter(pk=meeting_id).first()
            if fresh is None:
                return {}
            return {
                "public": payloads.public_payload(fresh),
                "manager": payloads.manager_payload(fresh),
            }
        finally:
            connections.close_all()

    meeting_hub.broadcast_threadsafe(meeting_id, _build, debounce=debounce)


def notify(meeting: QuestionSet, debounce=False) -> None:
    """Broadcast after the surrounding transaction commits (immediately in
    autocommit mode)."""
    transaction.on_commit(lambda: broadcast_meeting(meeting, debounce=debounce))


def _stream(meeting, role, build, on_open=None, on_close=None):
    """Subscribe, presence and their cleanup all live inside the generator,
    so a stream that never starts (client gone before the first byte)
    leaves nothing behind."""
    async def events():
        subscriber = None
        try:
            subscriber = meeting_hub.subscribe(meeting.pk, role)
            if on_open:
                on_open()
            yield sse_frame(await sync_to_async(build)())
            while True:
                try:
                    yield await asyncio.wait_for(
                        subscriber.queue.get(), timeout=KEEPALIVE_SECONDS,
                    )
                except TimeoutError:
                    yield KEEPALIVE_FRAME
        finally:
            if subscriber is not None:
                meeting_hub.unsubscribe(meeting.pk, subscriber)
                if on_close:
                    on_close()

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-store"
    response["X-Accel-Buffering"] = "no"
    return response


def _closing(fn):
    def wrapped(*args):
        try:
            return fn(*args)
        finally:
            connections.close_all()
    return wrapped


async def member_stream(request, token):
    """Ballot page of a personal link (``public`` role)."""
    @_closing
    def _context():
        invite, state = services.resolve_invite(token)
        if state not in ("waiting", "active"):
            return None
        ballots.enter(invite)
        return invite

    invite = await sync_to_async(_context)()
    if invite is None:
        raise Http404
    meeting = invite.meeting

    def _on_open():
        presence.connect(invite.pk)
        # The console shows who is connected.
        broadcast_meeting(meeting, debounce=True)

    def _on_close():
        presence.disconnect(invite.pk)
        broadcast_meeting(meeting, debounce=True)

    return _stream(
        meeting, "public", _closing(lambda: payloads.public_payload(meeting)),
        _on_open, _on_close,
    )


async def manager_stream(request, pk):
    """Console of a meeting — only for the managers of its room."""
    @_closing
    def _context():
        if not request.user.is_authenticated:
            return None
        return QuestionSet.objects.filter(
            pk=pk, type=QuestionSet.SetType.MEETING,
            room__in=services.managed_committee_rooms(request.user),
        ).first()

    meeting = await sync_to_async(_context)()
    if meeting is None:
        return JsonResponse({"detail": "Forbidden"}, status=403)
    return _stream(meeting, "manager", _closing(lambda: payloads.manager_payload(meeting)))
