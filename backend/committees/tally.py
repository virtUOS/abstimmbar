# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""In-memory tally of secret ballots (§ 8).

Counts and free texts of a secret ballot live only in this process until the
ballot closes; nothing here is ever logged or written to the database. A
process restart loses the tally — ``EPOCH`` lets ballots detect that.
"""
import secrets
import threading
from collections import Counter

# Random per process start; a secret ballot opened under another epoch has
# lost its tally.
EPOCH: str = secrets.token_hex(8)


class SecretTally:
    def __init__(self):
        self._lock = threading.Lock()
        self._ballots: dict[int, dict] = {}

    def start(self, ballot_id: int) -> None:
        with self._lock:
            self._ballots[ballot_id] = {"groups": {}}

    def add(self, ballot_id: int, group_id: int, keys: list[str], text: str | None) -> None:
        with self._lock:
            groups = self._ballots[ballot_id]["groups"]
            group = groups.setdefault(
                group_id, {"counts": Counter(), "ballots": 0, "texts": []},
            )
            group["counts"].update(keys)
            group["ballots"] += 1
            if text is not None:
                group["texts"].append(text)

    def has(self, ballot_id: int) -> bool:
        with self._lock:
            return ballot_id in self._ballots

    def pop(self, ballot_id: int) -> dict | None:
        with self._lock:
            return self._ballots.pop(ballot_id, None)

    def discard(self, ballot_id: int) -> None:
        with self._lock:
            self._ballots.pop(ballot_id, None)


secret_tally = SecretTally()
