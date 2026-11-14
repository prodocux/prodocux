"""Archive revision 3 catalog and preflight over the host-owned source registry."""

import os
from secrets import token_urlsafe
from time import time_ns

from .contracts import digest, load, validate
from .decoders import ArchiveError
from .execution import (
    CHAIN_PROFILES,
    OPERATIONS,
    PORTABLE,
    execute_operation,
    verify_selection,
)
from .sources import scope


class Negotiation:
    def __init__(self, sources, *, isolated_zip_read=False):
        self.sources = sources
        self.isolated_zip_read = isolated_zip_read and os.name == "nt"
        self.profiles = []
        for target in load("archive_profile_targets.json"):
            native = target["release_target"] == "rc13_conditional_native_target"
            definition = {
                **target,
                "profile_contract": {"name": target["profile_id"], "version": "1"},
                "prerequisite_types": ["decoder"] if native else [],
            }
            reason = "PROFILE_NOT_IMPLEMENTED" if native else "PROFILE_UNQUALIFIED"
            status = "not_implemented" if native else "unqualified"
            operations = {
                operation: {"support_status": status, "reason_codes": [reason]}
                for operation in ("inspect", "list", "read", "resolve")
            }
            candidate = (
                self.isolated_zip_read
                and target["profile_id"] in PORTABLE | CHAIN_PROFILES
            )
            if candidate:
                for operation in OPERATIONS:
                    if (
                        target["profile_id"] in CHAIN_PROFILES
                        and operation != "resolve"
                    ):
                        continue
                    if operation == "resolve" and target["profile_id"].endswith(
                        ("-single-stream", "-single-member")
                    ):
                        continue
                    operations[operation] = {
                        "support_status": "qualified",
                        "reason_codes": [],
                    }
            self.profiles.append(
                {
                    "definition": definition,
                    "definition_digest": digest(definition),
                    "operations": operations,
                    "qualification_digest": digest(
                        {
                            "definition": definition,
                            "operations": sorted(
                                operation
                                for operation, status in operations.items()
                                if status["support_status"] == "qualified"
                            ),
                            "worker": "windows_appcontainer_job_object",
                        }
                    )
                    if candidate
                    else None,
                    "execution_profile_digest": digest(
                        {
                            "candidate": definition,
                            "policy": sources.policy,
                            "isolated_read": candidate,
                        }
                    ),
                }
            )
        self.revision = digest(self.profiles)

    def ledger(self, owner, source_ref, profile_id, now):
        lease = self.sources.lookup(owner, source_ref, now)
        entry = next(
            (
                item
                for item in self.profiles
                if item["definition"]["profile_id"] == profile_id
            ),
            None,
        )
        if entry is None:
            raise ArchiveError("PROFILE_UNKNOWN")
        return self.sources.initial_ledger(
            owner, lease, entry["execution_profile_digest"], now
        )

    def catalog(self, owner, now):
        width = self.sources.ttl_ms
        issued = now - now % width
        value = {
            "schema_version": "prodocux_archive_capability_catalog_v3",
            "snapshot_id": digest(
                [self.revision, owner.authority, owner.tenant, str(issued)]
            ),
            "registry_revision": self.revision,
            "authority_id": owner.authority,
            "tenant_id": owner.tenant,
            "issued_at_ms": str(issued),
            "expires_at_ms": str(issued + width),
            "profiles": self.profiles,
        }
        validate("capability_catalog_v3", value)
        return value

    def _preflight(self, owner, base, now):
        request, context = base["request"], base["context"]
        lease = self.sources.lookup(owner, request["source_ref"], now)
        if (
            context["operation_id"] != lease["operation_id"]
            or context["request_id"] != request["request_id"]
            or context["source_lease_digest"] != digest(lease)
            or context["credential_ref"] != request.get("credential_ref")
        ):
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        if request["operation"] == "read":
            span = request["requested_range"]
            if int(span["start"]) > int(span["end"]):
                raise ArchiveError("INVALID_RANGE")
        return request

    def _check_chain_decoder(self, request, profile):
        if request["operation"] != "resolve":
            return []
        registered = {
            digest(
                {"execution_profile_digest": item["execution_profile_digest"]}
            ): item["definition"]["profile_id"]
            for item in self.profiles
            if item["definition"]["profile_id"] in PORTABLE
            and item["operations"]["read"]["support_status"] == "qualified"
        }
        profiles = [
            registered.get(step["decoder_attestation_digest"])
            for step in request["chain"]
        ]
        if (
            not profiles
            or None in profiles
            or (profile not in CHAIN_PROFILES and profiles[0] != profile)
        ):
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        return profiles

    def negotiate(self, owner, value, now):
        validate("negotiation_request_v3", value)
        request = self._preflight(owner, value["base_request"], now)
        catalog = self.catalog(owner, now)
        if value["catalog_digest"] != digest(catalog):
            raise ArchiveError("CAPABILITY_CATALOG_CHANGED")
        entry = next(
            (
                item
                for item in catalog["profiles"]
                if item["definition"]["profile_id"] == value["profile_id"]
            ),
            None,
        )
        if entry is None:
            raise ArchiveError("PROFILE_UNKNOWN")
        if entry["definition"]["profile_contract"] != value["profile_contract"]:
            raise ArchiveError("PROFILE_CONTRACT_UNSUPPORTED")
        if (
            entry["definition_digest"] != value["expected_profile_digest"]
            or entry["execution_profile_digest"]
            != value["base_request"]["context"]["profile_digest"]
        ):
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        ledger = self.ledger(owner, request["source_ref"], value["profile_id"], now)
        if value["base_request"]["context"]["ledger_digest"] != digest(ledger):
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        result = {
            "schema_version": "prodocux_archive_negotiation_result_v3",
            "request_id": request["request_id"],
            "profile_id": value["profile_id"],
            "profile_contract": value["profile_contract"],
            "catalog_digest": value["catalog_digest"],
            "decision": "unavailable",
            "http_status": 200,
            "binding": None,
            "availability": {
                **entry["operations"][request["operation"]],
                "availability": "unavailable",
            },
        }
        if result["availability"]["support_status"] == "qualified":
            chain_profiles = self._check_chain_decoder(request, value["profile_id"])
            lease = self.sources.lookup(owner, request["source_ref"], now)
            verify_selection(
                self.sources,
                owner,
                lease,
                value["base_request"],
                value["profile_id"],
                now,
                chain_profiles,
            )
            issued = time_ns() // 1_000_000
            expires = min(int(lease["expires_at_ms"]), int(catalog["expires_at_ms"]))
            if issued >= expires:
                raise ArchiveError("NEGOTIATION_EXPIRED")
            binding = {
                "negotiation_id": token_urlsafe(24),
                "catalog_digest": value["catalog_digest"],
                "profile_id": value["profile_id"],
                "profile_contract": value["profile_contract"],
                "profile_digest": entry["definition_digest"],
                "execution_profile_digest": entry["execution_profile_digest"],
                "source_bundle_digest": lease["bundle_digest"],
                "source_chain_digest": digest(
                    request.get("parent_chain", request.get("chain", []))
                ),
                "operation_id": lease["operation_id"],
                "operation": request["operation"],
                "view": request["view"],
                "request_digest": digest(request),
                "authority_scope": scope(owner),
                "issued_at_ms": str(issued),
                "expires_at_ms": str(expires),
            }
            result.update(decision="accepted", binding=binding)
            result["availability"]["availability"] = "available"
            self.sources.save_binding(owner, lease, result, issued)
        validate("negotiation_result_v3", result)
        return result

    def execution_gate(self, owner, value, operation, now):
        validate("request_envelope_v3", value)
        request = self._preflight(owner, value["base"], now)
        if request["operation"] != operation:
            raise ArchiveError("MALFORMED_REQUEST")
        if value["mode"] == "discovery":
            if operation != "inspect" or value["profile_binding"] is not None:
                raise ArchiveError("PROFILE_BINDING_CHANGED")
            raise ArchiveError("PROFILE_UNQUALIFIED")
        binding = value["profile_binding"]
        if binding is None or digest(request) != binding["request_digest"]:
            raise ArchiveError("PROFILE_BINDING_CHANGED")
        if not int(binding["issued_at_ms"]) <= now < int(binding["expires_at_ms"]):
            raise ArchiveError("NEGOTIATION_EXPIRED")
        lease = self.sources.lookup(owner, request["source_ref"], now)
        accepted = self.sources.saved_binding(owner, lease, binding, now)
        catalog = self.catalog(owner, now)
        if digest(catalog) != binding["catalog_digest"]:
            raise ArchiveError("CAPABILITY_CATALOG_CHANGED")
        if (
            not self.isolated_zip_read
            or operation not in OPERATIONS
            or binding["profile_id"] not in PORTABLE | CHAIN_PROFILES
            or not any(
                entry["definition"]["profile_id"] == binding["profile_id"]
                and entry["operations"][operation]["support_status"] == "qualified"
                for entry in catalog["profiles"]
            )
        ):
            raise ArchiveError("PROFILE_UNQUALIFIED")
        chain_profiles = self._check_chain_decoder(request, binding["profile_id"])
        return execute_operation(
            self.sources,
            owner,
            lease,
            value["base"],
            accepted,
            clock=lambda: time_ns() // 1_000_000,
            chain_profiles=chain_profiles,
        )
