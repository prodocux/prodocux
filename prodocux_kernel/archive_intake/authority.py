"""Durable host-side archive lease and budget accounting.

The caller supplies a verified transport identity. This module does not
interpret headers or accept a wire authority assertion.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from secrets import token_urlsafe

from .decoders import ArchiveError

COUNTERS = (
    "source_bytes",
    "expanded_bytes",
    "returned_bytes",
    "metadata_bytes",
    "elapsed_ms",
    "peak_memory_bytes",
    "depth",
    "volumes",
    "entries",
)
PEAK_COUNTERS = frozenset(("peak_memory_bytes", "depth"))


@dataclass(frozen=True)
class Identity:
    authority: str
    tenant: str
    principal: str


def _vector(value):
    if set(value) != set(COUNTERS) or any(
        type(number) is not int or not 0 <= number <= 2**64 - 1
        for number in value.values()
    ):
        raise ArchiveError("MALFORMED_REQUEST")
    return dict(value)


def _combine(left, right):
    return {
        key: max(left[key], right[key])
        if key in PEAK_COUNTERS
        else left[key] + right[key]
        for key in COUNTERS
    }


def _within(value, limits):
    return all(value[key] <= limits[key] for key in COUNTERS)


class ArchiveAuthority:
    def __init__(self, database):
        self.database = database
        with self._transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_lease (
                    ref TEXT PRIMARY KEY, authority TEXT NOT NULL, tenant TEXT NOT NULL,
                    principal TEXT NOT NULL, bundle_digest TEXT NOT NULL, expires_ms INTEGER NOT NULL,
                    active INTEGER NOT NULL, limits TEXT NOT NULL, spent TEXT NOT NULL
                )
                """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_attempt (
                    ref TEXT NOT NULL REFERENCES archive_lease(ref),
                    request_id TEXT NOT NULL, binding_digest TEXT NOT NULL,
                    state TEXT NOT NULL, reserved TEXT NOT NULL, measured TEXT,
                    PRIMARY KEY (ref, request_id)
                )
                """)

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.database, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        finally:
            db.close()

    def issue(self, owner, bundle_digest, *, expires_ms, now_ms, limits):
        if not now_ms < expires_ms < 2**63:
            raise ArchiveError("MALFORMED_REQUEST")
        limits = _vector(limits)
        if not all(limits.values()):
            raise ArchiveError("MALFORMED_REQUEST")
        ref = token_urlsafe(32)
        with self._transaction() as db:
            db.execute(
                "INSERT INTO archive_lease VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    ref,
                    owner.authority,
                    owner.tenant,
                    owner.principal,
                    bundle_digest,
                    expires_ms,
                    json.dumps(limits),
                    json.dumps(dict.fromkeys(COUNTERS, 0)),
                ),
            )
        return ref

    def _owned(self, db, owner, ref):
        row = db.execute("SELECT * FROM archive_lease WHERE ref=?", (ref,)).fetchone()
        if row is None or (row["authority"], row["tenant"], row["principal"]) != (
            owner.authority,
            owner.tenant,
            owner.principal,
        ):
            raise ArchiveError("SOURCE_NOT_FOUND")
        return row

    def _live(self, db, owner, ref, now_ms):
        row = self._owned(db, owner, ref)
        if not row["active"]:
            raise ArchiveError("SOURCE_NOT_FOUND")
        if now_ms >= row["expires_ms"]:
            raise ArchiveError("SOURCE_LEASE_EXPIRED")
        return row

    def close(self, owner, ref):
        with self._transaction() as db:
            self._owned(db, owner, ref)
            db.execute("UPDATE archive_lease SET active=0 WHERE ref=?", (ref,))

    def authorize(self, owner, ref, *, now_ms):
        with self._transaction() as db:
            return self._live(db, owner, ref, now_ms)["bundle_digest"]

    def reserve(self, owner, ref, request_id, binding_digest, proposed, *, now_ms):
        """Return True once. Exact retries must never start a second worker."""
        proposed = _vector(proposed)
        with self._transaction() as db:
            lease = self._live(db, owner, ref, now_ms)
            old = db.execute(
                "SELECT * FROM archive_attempt WHERE ref=? AND request_id=?",
                (ref, request_id),
            ).fetchone()
            if old is not None:
                if (
                    old["binding_digest"] != binding_digest
                    or json.loads(old["reserved"]) != proposed
                ):
                    raise ArchiveError("PROFILE_BINDING_CHANGED")
                if old["state"] in ("running", "unknown"):
                    raise ArchiveError("OPERATION_RECONCILIATION_REQUIRED")
                return False
            if db.execute(
                "SELECT 1 FROM archive_attempt WHERE ref=? AND state IN ('running', 'unknown')",
                (ref,),
            ).fetchone():
                raise ArchiveError("OPERATION_RECONCILIATION_REQUIRED")
            if not _within(
                _combine(json.loads(lease["spent"]), proposed),
                json.loads(lease["limits"]),
            ):
                raise ArchiveError("BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO archive_attempt VALUES (?, ?, ?, 'running', ?, NULL)",
                (ref, request_id, binding_digest, json.dumps(proposed)),
            )
        return True

    def settle(self, owner, ref, request_id, measured):
        """Record trusted measurements. None retains the reservation as unknown."""
        if measured is not None:
            measured = _vector(measured)
        with self._transaction() as db:
            lease = self._owned(db, owner, ref)
            row = db.execute(
                "SELECT * FROM archive_attempt WHERE ref=? AND request_id=?",
                (ref, request_id),
            ).fetchone()
            if row is None or row["state"] == "settled":
                raise ArchiveError("OPERATION_NOT_ACTIVE")
            if measured is None:
                db.execute(
                    "UPDATE archive_attempt SET state='unknown' WHERE ref=? AND request_id=?",
                    (ref, request_id),
                )
                return
            spent = _combine(json.loads(lease["spent"]), measured)
            if any(value > 2**64 - 1 for value in spent.values()):
                raise ArchiveError("BUDGET_EXHAUSTED")
            db.execute(
                "UPDATE archive_lease SET spent=? WHERE ref=?", (json.dumps(spent), ref)
            )
            db.execute(
                "UPDATE archive_attempt SET state='settled', measured=? WHERE ref=? AND request_id=?",
                (json.dumps(measured), ref, request_id),
            )
