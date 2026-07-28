# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""In-process SSE hub (ADR-0003).

One registry of subscriber queues per room. Every event is a full state
snapshot; vote-driven broadcasts are debounced so a burst of votes becomes
a handful of events. Sync views (ORM code in the threadpool) hand work to
the event loop via ``run_coroutine_threadsafe``.

Single-process by design — see ADR-0003 for the Redis scale-out path.
"""
import asyncio
import json
import threading
from collections import defaultdict

DEBOUNCE_SECONDS = 0.3
QUEUE_SIZE = 16


def sse_frame(payload):
    """Encode one payload as a Server-Sent-Events frame."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class _Subscriber:
    __slots__ = ("queue", "role")

    def __init__(self, role):
        self.queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.role = role


class RoomHub:
    def __init__(self):
        self._rooms = defaultdict(set)  # room_id -> set[_Subscriber]
        self._pending = {}  # room_id -> asyncio.TimerHandle (debounce)
        self._loop = None
        self._lock = threading.Lock()

    # -- called from the async stream view (event loop thread) ------------

    def subscribe(self, room_id, role):
        self._loop = asyncio.get_running_loop()
        subscriber = _Subscriber(role)
        with self._lock:
            self._rooms[room_id].add(subscriber)
        return subscriber

    def unsubscribe(self, room_id, subscriber):
        with self._lock:
            self._rooms[room_id].discard(subscriber)
            if not self._rooms[room_id]:
                del self._rooms[room_id]

    def participant_count(self, room_id):
        with self._lock:
            return sum(1 for s in self._rooms.get(room_id, ()) if s.role == "participant")

    # -- called from sync views (threadpool) -------------------------------

    def broadcast_threadsafe(self, room_id, build_payloads, debounce=False):
        """Schedule a broadcast; ``build_payloads()`` runs on the loop just
        before sending (so a debounced burst serializes state only once).

        ``build_payloads`` must be thread-safe and cheap-ish; it returns
        ``{"participant": {...}, "presenter": {...}}``.
        """
        if self._loop is None or self._loop.is_closed():
            return  # nobody has ever connected; nothing to notify

        async def _send():
            self._pending.pop(room_id, None)
            # ORM work must not run on the event loop — build in the pool.
            payloads = await self._loop.run_in_executor(None, build_payloads)
            # Serialize once per role, not once per subscriber — with 1000
            # participants that saves 999 json.dumps per broadcast.
            frames = {role: sse_frame(payload) for role, payload in payloads.items()}
            with self._lock:
                subscribers = list(self._rooms.get(room_id, ()))
            for subscriber in subscribers:
                frame = frames.get(subscriber.role)
                if frame is None:
                    continue
                try:
                    subscriber.queue.put_nowait(frame)
                except asyncio.QueueFull:
                    # Slow consumer: it will resync from the next snapshot.
                    pass

        def _fire():
            asyncio.ensure_future(_send())

        def _schedule():
            if debounce:
                if room_id in self._pending:
                    return  # a flush is already scheduled
                self._pending[room_id] = self._loop.call_later(DEBOUNCE_SECONDS, _fire)
            else:
                _fire()

        self._loop.call_soon_threadsafe(_schedule)


hub = RoomHub()
