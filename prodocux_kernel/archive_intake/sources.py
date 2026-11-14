"""Host-owned upload session and immutable lease state for archive intake."""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from .authority import COUNTERS, ArchiveAuthority, _combine, _vector, _within
from .contracts import digest, validate
from .decoders import ArchiveError

CHUNK_LIMIT = 1 << 20
SOURCE_LIMIT = 64 << 20
LARGE_SOURCE_LIMIT = 8 << 30
LEDGER_LIMITS = {
    "source_bytes": 256 << 20,
    "expanded_bytes": 512 << 20,
    "returned_bytes": 8 << 20,
    "metadata_bytes": 16 << 20,
    "elapsed_ms": 120_000,
    "peak_memory_bytes": 512 << 20,
    "depth": 8,
    "volumes": 64,
    "entries": 16_384,
}


def scope(owner):
    return {
        "authority_id": owner.authority,
        "tenant_id": owner.tenant,
        "principal_id": owner.principal,
    }


class ArchiveSources(ArchiveAuthority):
    def __init__(self, database, *, ttl_ms, large_sources=False):
        super().__init__(database)
        self.ttl_ms = ttl_ms
        self.source_limit = LARGE_SOURCE_LIMIT if large_sources else SOURCE_LIMIT
        self.chunk_limit = 8 << 20 if large_sources else CHUNK_LIMIT
        self.ledger_limits = {**LEDGER_LIMITS}
        if large_sources:
            self.ledger_limits.update(source_bytes=64 << 30, elapsed_ms=900_000)
        self.policy = digest(
            {
                "ttl_ms": str(ttl_ms),
                "chunk_limit": str(self.chunk_limit),
                "source_limit": str(self.source_limit),
                "ledger_limits": self.ledger_limits,
            }
        )
        with self._transaction() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_upload (
                    session TEXT PRIMARY KEY, owner TEXT NOT NULL, plan TEXT NOT NULL,
                    lease TEXT
                )
                """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_chunk (
                    session TEXT NOT NULL REFERENCES archive_upload(session),
                    start INTEGER NOT NULL, data BLOB NOT NULL,
                    PRIMARY KEY (session, start)
                )
                """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_reconciliation_cost (
                    session TEXT NOT NULL REFERENCES archive_upload(session),
                    binding_digest TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (session, binding_digest)
                )
                """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_wire_ledger (
                    session TEXT NOT NULL REFERENCES archive_upload(session),
                    profile_digest TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (session, profile_digest)
                )
                """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_wire_binding (
                    session TEXT NOT NULL REFERENCES archive_upload(session),
                    negotiation_id TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY (session, negotiation_id)
                )
                """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS archive_wire_receipt (
                    session TEXT NOT NULL REFERENCES archive_upload(session),
                    binding_digest TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY (session, binding_digest)
                )
                """)

    def create(self, owner, plan, now):
        validate("source_admission_v2", plan)
        if (
            plan["authority_binding"] != scope(owner)
            or plan["policy_digest"] != self.policy
        ):
            raise ArchiveError("FORBIDDEN")
        if plan["mode"] != "chunked_snapshot" or len(plan["volumes"]) != 1:
            raise ArchiveError("PROFILE_NOT_APPLICABLE")
        volume = plan["volumes"][0]
        if volume["ordinal"] != "0" or volume["declared_size_bytes"] is None:
            raise ArchiveError("MALFORMED_REQUEST")
        size = int(volume["declared_size_bytes"])
        if size > self.source_limit:
            raise ArchiveError("SOURCE_TOO_LARGE")
        if not now < int(plan["expires_at_ms"]) <= now + self.ttl_ms:
            raise ArchiveError("SOURCE_LEASE_EXPIRED")
        expected_start = 0
        for chunk in plan["upload_chunks"]:
            start, end = (int(chunk["range"][edge]) for edge in ("start", "end"))
            if (
                chunk["volume_key"] != volume["volume_key"]
                or start != expected_start
                or not 0 < end - start <= self.chunk_limit
            ):
                raise ArchiveError("INVALID_RANGE")
            expected_start = end
        if expected_start != size or not 0 < size or len(plan["upload_chunks"]) > 4096:
            raise ArchiveError("INVALID_RANGE")
        with self._transaction() as db:
            old = db.execute(
                "SELECT owner, plan FROM archive_upload WHERE session=?",
                (plan["session_id"],),
            ).fetchone()
            if old:
                if json.loads(old["owner"]) != scope(owner):
                    raise ArchiveError("SOURCE_NOT_FOUND")
                if json.loads(old["plan"]) != plan:
                    raise ArchiveError("PROFILE_BINDING_CHANGED")
            else:
                db.execute(
                    "INSERT INTO archive_upload VALUES (?, ?, ?, NULL)",
                    (plan["session_id"], json.dumps(scope(owner)), json.dumps(plan)),
                )
        return {"session_id": plan["session_id"], "operation_id": plan["operation_id"]}

    def _session(self, db, owner, session, now):
        row = db.execute(
            "SELECT * FROM archive_upload WHERE session=?", (session,)
        ).fetchone()
        if row is None or json.loads(row["owner"]) != scope(owner):
            raise ArchiveError("SOURCE_NOT_FOUND")
        plan = json.loads(row["plan"])
        lease = json.loads(row["lease"]) if row["lease"] else None
        if lease is not None and lease["state"] != "active":
            raise ArchiveError("SOURCE_NOT_FOUND")
        if now >= int((lease or plan)["expires_at_ms"]):
            raise ArchiveError("SOURCE_LEASE_EXPIRED")
        return plan, lease

    def upload(self, owner, session, volume, start, end, checksum, data, now):
        if len(data) > self.chunk_limit:
            raise ArchiveError("SOURCE_TOO_LARGE")
        if end - start != len(data) or hashlib.sha256(data).hexdigest() != checksum:
            raise ArchiveError("INTEGRITY_FAILED")
        with self._transaction() as db:
            plan, lease = self._session(db, owner, session, now)
            if lease is not None:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            descriptor = {
                "volume_key": volume,
                "range": {"start": str(start), "end": str(end)},
                "sha256": checksum,
            }
            if descriptor not in plan["upload_chunks"]:
                raise ArchiveError("INVALID_RANGE")
            db.execute(
                "INSERT OR IGNORE INTO archive_chunk VALUES (?, ?, ?)",
                (session, start, data),
            )

    def seal(self, owner, session, now):
        with self._transaction() as db:
            plan, existing = self._session(db, owner, session, now)
            if existing is not None:
                return existing
            checksums = hashlib.sha256()
            size = count = 0
            for count, row in enumerate(
                db.execute(
                    "SELECT start, data FROM archive_chunk WHERE session=? ORDER BY start",
                    (session,),
                ),
                1,
            ):
                chunk = plan["upload_chunks"][count - 1]
                if (
                    row["start"] != size
                    or hashlib.sha256(row["data"]).hexdigest() != chunk["sha256"]
                ):
                    raise ArchiveError("SOURCE_CHANGED")
                checksums.update(row["data"])
                size += len(row["data"])
            volume = plan["volumes"][0]
            if (
                count != len(plan["upload_chunks"])
                or str(size) != volume["declared_size_bytes"]
            ):
                raise ArchiveError("VOLUME_MISSING")
            bundle = {
                "schema_version": "prodocux_archive_source_bundle_v1",
                "volumes": [
                    {
                        "ordinal": "0",
                        "volume_key": volume["volume_key"],
                        "sha256": checksums.hexdigest(),
                        "size_bytes": str(size),
                    }
                ],
            }
            bundle_digest = digest(bundle)
            if plan["expected_bundle_digest"] not in (None, bundle_digest):
                raise ArchiveError("SOURCE_CHANGED")
            lease = {
                "schema_version": "prodocux_archive_source_lease_v2",
                "session_id": session,
                "source_ref": token_urlsafe(32),
                "operation_id": plan["operation_id"],
                "authority_binding": scope(owner),
                "policy_digest": self.policy,
                "bundle": bundle,
                "bundle_digest": bundle_digest,
                "state": "active",
                "issued_at_ms": str(now),
                "expires_at_ms": plan["expires_at_ms"],
                "immutable": True,
                "storage_kind": "controlled_spool",
            }
            validate("source_lease_v2", lease)
            db.execute(
                "UPDATE archive_upload SET lease=? WHERE session=?",
                (json.dumps(lease), session),
            )
            return lease

    def control(self, owner, session, request, now):
        validate("source_control_v2", request)
        with self._transaction() as db:
            _, lease = self._session(db, owner, session, now)
            if (
                lease is None
                or request["session_id"] != session
                or request["operation_id"] != lease["operation_id"]
                or request["expected_lease_digest"] != digest(lease)
            ):
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            action = request["action"]
            expiry = request["requested_expiry_ms"]
            if action == "renew":
                if (
                    expiry is None
                    or not int(lease["expires_at_ms"])
                    < int(expiry)
                    <= now + self.ttl_ms
                ):
                    raise ArchiveError("INVALID_RANGE")
                lease["expires_at_ms"] = expiry
            elif expiry is not None:
                raise ArchiveError("MALFORMED_REQUEST")
            else:
                lease["state"] = {"close": "closed", "revoke": "revoked"}[action]
                db.execute("DELETE FROM archive_chunk WHERE session=?", (session,))
            db.execute(
                "UPDATE archive_upload SET lease=? WHERE session=?",
                (json.dumps(lease), session),
            )
            return lease

    def lookup(self, owner, ref, now):
        with self._transaction() as db:
            # The opaque reference is the lookup key. Authority comes from transport.
            row = db.execute(
                "SELECT session FROM archive_upload WHERE json_extract(lease, '$.source_ref')=?",
                (ref,),
            ).fetchone()
            if row is None:
                raise ArchiveError("SOURCE_NOT_FOUND")
            _, lease = self._session(db, owner, row["session"], now)
            return lease

    @contextmanager
    def worker_snapshot(self, owner, lease, now):
        with TemporaryDirectory(prefix="prodocux-archive-") as directory:
            path = Path(directory) / "source"
            checksum = hashlib.sha256()
            size = 0
            with self._transaction() as db, path.open("wb") as output:
                _, live = self._session(db, owner, lease["session_id"], now)
                if live != lease:
                    raise ArchiveError("PROFILE_BINDING_CHANGED")
                for row in db.execute(
                    "SELECT start, data FROM archive_chunk WHERE session=? ORDER BY start",
                    (lease["session_id"],),
                ):
                    if row["start"] != size:
                        raise ArchiveError("SOURCE_CHANGED")
                    data = row["data"]
                    size += len(data)
                    output.write(data)
                    checksum.update(data)
            volume = lease["bundle"]["volumes"][0]
            if (
                checksum.hexdigest() != volume["sha256"]
                or str(size) != volume["size_bytes"]
            ):
                raise ArchiveError("SOURCE_CHANGED")
            yield path

    def source_signature(self, owner, lease, now):
        with self._transaction() as db:
            _, live = self._session(db, owner, lease["session_id"], now)
            if live != lease:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            rows = db.execute(
                "SELECT substr(data, 1, 4) AS signature FROM archive_chunk "
                "WHERE session=? AND start<4 ORDER BY start",
                (lease["session_id"],),
            )
            return b"".join(row["signature"] for row in rows)[:4]

    def initial_ledger(self, owner, lease, profile_digest, now):
        session = lease["session_id"]
        with self._transaction() as db:
            _, live = self._session(db, owner, session, now)
            if live != lease:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            row = db.execute(
                "SELECT value FROM archive_wire_ledger WHERE session=? AND profile_digest=?",
                (session, profile_digest),
            ).fetchone()
            if row is not None:
                return json.loads(row["value"])
            ledger = {
                "schema_version": "prodocux_archive_resource_ledger_v2",
                "operation_id": lease["operation_id"],
                "authority_binding": scope(owner),
                "source_bundle_digest": lease["bundle_digest"],
                "profile_digest": profile_digest,
                "policy_digest": self.policy,
                "revision": "0",
                "previous_ledger_digest": None,
                "limits": {
                    "max_" + key: str(value)
                    for key, value in self.ledger_limits.items()
                },
                "observed": dict.fromkeys(COUNTERS, "0"),
                "consumed": dict.fromkeys(COUNTERS, "0"),
                "state": "active",
                "attempts": [],
            }
            validate("resource_ledger_v2", ledger)
            db.execute(
                "INSERT INTO archive_wire_ledger VALUES (?, ?, ?)",
                (session, profile_digest, json.dumps(ledger)),
            )
            return ledger

    def save_binding(self, owner, lease, result, now):
        validate("negotiation_result_v3", result)
        binding = result["binding"]
        if result["decision"] != "accepted" or binding is None:
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        with self._transaction() as db:
            _, live = self._session(db, owner, lease["session_id"], now)
            if (
                live != lease
                or binding["authority_scope"] != scope(owner)
                or binding["operation_id"] != live["operation_id"]
                or binding["source_bundle_digest"] != live["bundle_digest"]
                or not int(binding["issued_at_ms"])
                <= now
                < int(binding["expires_at_ms"])
                or int(binding["expires_at_ms"]) > int(live["expires_at_ms"])
            ):
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            db.execute(
                "INSERT INTO archive_wire_binding VALUES (?, ?, ?)",
                (lease["session_id"], binding["negotiation_id"], json.dumps(result)),
            )

    def _wire_state(self, db, lease, profile):
        row = db.execute(
            "SELECT value FROM archive_wire_ledger WHERE session=? AND profile_digest=?",
            (lease["session_id"], profile),
        ).fetchone()
        if row is None:
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        return json.loads(row["value"])

    def saved_binding(self, owner, lease, binding, now):
        with self._transaction() as db:
            _, live = self._session(db, owner, lease["session_id"], now)
            row = db.execute(
                "SELECT value FROM archive_wire_binding WHERE session=? AND negotiation_id=?",
                (lease["session_id"], binding["negotiation_id"]),
            ).fetchone()
            if live != lease or row is None:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            value = json.loads(row["value"])
            if value["binding"] != binding:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            return value

    def verify_list_cursor(self, owner, lease, cursor, now):
        with self._transaction() as db:
            _, live = self._session(db, owner, lease["session_id"], now)
            if live != lease:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            rows = db.execute(
                "SELECT json_extract(value, '$.base.response.result.next_cursor') AS cursor "
                "FROM archive_wire_receipt WHERE session=? "
                "AND json_extract(value, '$.base.response.operation')='list'",
                (lease["session_id"],),
            )
            if not any(
                row["cursor"] and json.loads(row["cursor"]) == cursor for row in rows
            ):
                raise ArchiveError("PROFILE_BINDING_CHANGED")

    def _commit_ledger(self, db, lease, old, new):
        new["previous_ledger_digest"] = digest(old)
        new["revision"] = str(int(old["revision"]) + 1)
        validate("resource_ledger_v2", new)
        db.execute(
            "UPDATE archive_wire_ledger SET value=? WHERE session=? AND profile_digest=?",
            (json.dumps(new), lease["session_id"], new["profile_digest"]),
        )
        return new

    def reserve_wire(self, owner, lease, base, binding, proposed, now):
        proposed = _vector(proposed)
        with self._transaction() as db:
            _, live = self._session(db, owner, lease["session_id"], now)
            row = db.execute(
                "SELECT value FROM archive_wire_binding WHERE session=? AND negotiation_id=?",
                (lease["session_id"], binding["negotiation_id"]),
            ).fetchone()
            request = base["request"]
            context = base["context"]
            if (
                live != lease
                or row is None
                or json.loads(row["value"])["binding"] != binding
                or context["source_lease_digest"] != digest(live)
                or context["operation_id"] != binding["operation_id"]
                or context["request_id"] != request["request_id"]
                or context["profile_digest"] != binding["execution_profile_digest"]
                or request["operation"] != binding["operation"]
                or request["source_ref"] != live["source_ref"]
                or digest(request) != binding["request_digest"]
            ):
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            if not int(binding["issued_at_ms"]) <= now < int(binding["expires_at_ms"]):
                raise ArchiveError("NEGOTIATION_EXPIRED")
            old = self._wire_state(db, lease, binding["execution_profile_digest"])
            if old["state"] == "blocked":
                if any(attempt["state"] != "settled" for attempt in old["attempts"]):
                    raise ArchiveError("OPERATION_RECONCILIATION_REQUIRED")
                raise ArchiveError("BUDGET_EXHAUSTED")
            if context["ledger_digest"] != digest(old):
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            if any(
                attempt["attempt_id"] == request["request_id"]
                for attempt in old["attempts"]
            ):
                raise ArchiveError("OPERATION_NOT_ACTIVE")
            used = dict.fromkeys(COUNTERS, 0)
            for other in db.execute(
                "SELECT value FROM archive_wire_ledger WHERE session=?",
                (lease["session_id"],),
            ):
                ledger = json.loads(other["value"])
                if any(attempt["state"] != "settled" for attempt in ledger["attempts"]):
                    raise ArchiveError("OPERATION_RECONCILIATION_REQUIRED")
                used = _combine(
                    used, {key: int(value) for key, value in ledger["observed"].items()}
                )
            limits = {key: int(old["limits"]["max_" + key]) for key in COUNTERS}
            if not _within(_combine(used, proposed), limits):
                raise ArchiveError("BUDGET_EXHAUSTED")
            attempt = {
                "attempt_id": request["request_id"],
                "request_binding_digest": digest(binding),
                "state": "reserved",
                "observed": dict.fromkeys(COUNTERS, "0"),
            }
            return self._commit_ledger(
                db,
                lease,
                old,
                {**old, "state": "blocked", "attempts": [*old["attempts"], attempt]},
            )

    def record_reconciliation_cost(self, lease, binding, request_id, measured):
        """Record measurements established by the trusted host after execution stops."""
        measured = _vector(measured)
        if not all(measured[key] for key in ("source_bytes", "volumes", "elapsed_ms")):
            raise ArchiveError("MALFORMED_REQUEST")
        key = digest(binding)
        with self._transaction() as db:
            old = self._wire_state(db, lease, binding["execution_profile_digest"])
            if not any(
                item["attempt_id"] == request_id
                and item["request_binding_digest"] == key
                and item["state"] == "unknown_cost"
                for item in old["attempts"]
            ):
                raise ArchiveError("OPERATION_NOT_ACTIVE")
            prior = db.execute(
                "SELECT value FROM archive_reconciliation_cost WHERE session=? AND binding_digest=?",
                (lease["session_id"], key),
            ).fetchone()
            if prior is not None and json.loads(prior["value"]) != measured:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            db.execute(
                "INSERT OR IGNORE INTO archive_reconciliation_cost VALUES (?, ?, ?)",
                (lease["session_id"], key, json.dumps(measured)),
            )

    def reconcile_wire(self, owner, session, negotiation_id, now):
        with self._transaction() as db:
            _, lease = self._session(db, owner, session, now)
            row = db.execute(
                "SELECT value FROM archive_wire_binding WHERE session=? AND negotiation_id=?",
                (session, negotiation_id),
            ).fetchone()
            if lease is None or row is None:
                raise ArchiveError("SOURCE_NOT_FOUND")
            accepted = json.loads(row["value"])
            binding = accepted["binding"]
            evidence = db.execute(
                "SELECT value FROM archive_reconciliation_cost WHERE session=? AND binding_digest=?",
                (session, digest(binding)),
            ).fetchone()
            if evidence is None:
                raise ArchiveError("OPERATION_RECONCILIATION_REQUIRED")
            old = self._wire_state(db, lease, binding["execution_profile_digest"])
            if any(
                item["request_binding_digest"] == digest(binding) and item["state"] == "settled"
                for item in old["attempts"]
            ):
                return old
            return self.settle_wire(
                lease, binding, accepted["request_id"], json.loads(evidence["value"]), transaction=db,
            )

    def settle_wire(
        self, lease, binding, request_id, measured, *, make_receipt=None, transaction=None,
    ):
        if measured is not None:
            measured = _vector(measured)
        with (self._transaction() if transaction is None else nullcontext(transaction)) as db:
            old = self._wire_state(db, lease, binding["execution_profile_digest"])
            attempts = [dict(attempt) for attempt in old["attempts"]]
            attempt = next(
                (item for item in attempts if item["attempt_id"] == request_id), None
            )
            if (
                attempt is None
                or attempt["state"] == "settled"
                or attempt["request_binding_digest"] != digest(binding)
            ):
                raise ArchiveError("OPERATION_NOT_ACTIVE")
            if measured is None:
                attempt["state"] = "unknown_cost"
                return self._commit_ledger(
                    db, lease, old, {**old, "attempts": attempts}
                )
            attempt.update(
                state="settled",
                observed={key: str(value) for key, value in measured.items()},
            )
            observed = _combine(
                {key: int(value) for key, value in old["observed"].items()}, measured
            )
            if any(value > 2**64 - 1 for value in observed.values()):
                raise ArchiveError("BUDGET_EXHAUSTED")
            limits = {key: int(old["limits"]["max_" + key]) for key in COUNTERS}
            committed = self._commit_ledger(
                db,
                lease,
                old,
                {
                    **old,
                    "attempts": attempts,
                    "state": "active"
                    if all(observed[key] < limits[key] for key in COUNTERS)
                    else "blocked",
                    "observed": {key: str(value) for key, value in observed.items()},
                    "consumed": {
                        key: str(min(value, limits[key]))
                        for key, value in observed.items()
                    },
                },
            )
            if make_receipt is not None:
                # A revoked lease must not publish a result from an in-flight worker.
                row = db.execute(
                    "SELECT lease FROM archive_upload WHERE session=?",
                    (lease["session_id"],),
                ).fetchone()
                if row is None or json.loads(row["lease"])["state"] != "active":
                    return committed
                receipt = make_receipt(committed)
                validate("result_envelope_v3", receipt)
                if (
                    receipt["mode"] != "negotiated"
                    or receipt["profile_binding_digest"] != digest(binding)
                    or receipt["base"]["request_id"] != request_id
                    or receipt["base"]["operation_id"] != lease["operation_id"]
                    or receipt["base"]["source_lease_digest"] != digest(lease)
                    or receipt["base"]["committed_ledger_digest"] != digest(committed)
                    or receipt["base"]["response"]["request_id"] != request_id
                    or receipt["base"]["response"]["operation"] != binding["operation"]
                ):
                    raise ArchiveError("PROFILE_BINDING_CHANGED")
                db.execute(
                    "INSERT INTO archive_wire_receipt VALUES (?, ?, ?)",
                    (lease["session_id"], digest(binding), json.dumps(receipt)),
                )
            return committed

    def wire_receipt(self, owner, lease, binding, now):
        with self._transaction() as db:
            _, live = self._session(db, owner, lease["session_id"], now)
            if live["source_ref"] != lease["source_ref"]:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            row = db.execute(
                "SELECT value FROM archive_wire_receipt WHERE session=? AND binding_digest=?",
                (lease["session_id"], digest(binding)),
            ).fetchone()
            return None if row is None else json.loads(row["value"])
