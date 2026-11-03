# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Connection status of meeting links (in memory, single process like the
SSE hub): which invites have an open ballot-page stream right now."""
import threading

from django.utils import timezone


class Presence:
    def __init__(self):
        self._lock = threading.Lock()
        self._connections = {}  # invite_id -> number of open streams
        self._since = {}  # invite_id -> datetime of the last disconnect

    def connect(self, invite_id) -> None:
        with self._lock:
            self._connections[invite_id] = self._connections.get(invite_id, 0) + 1
            self._since.pop(invite_id, None)

    def disconnect(self, invite_id) -> None:
        with self._lock:
            remaining = self._connections.get(invite_id, 0) - 1
            if remaining > 0:
                self._connections[invite_id] = remaining
                return
            self._connections.pop(invite_id, None)
            self._since[invite_id] = timezone.now()

    def status(self, invite_id):
        """(connected, disconnected_since) — never connected: (False, None)."""
        with self._lock:
            if self._connections.get(invite_id):
                return True, None
            return False, self._since.get(invite_id)


presence = Presence()
