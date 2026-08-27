"""Private sidecar authentication profile (Phase 1).

Frozen contract: ``docs/phase0/schemas/prodocux_sidecar_auth_profile_v1.json``.

Profiles:

- unset / empty: legacy opt-in bearer (tokens optional; tests stay open)
- ``self_hosted``: rotatable bearer required; mTLS not required
- ``production_mtls``: rotatable bearer **and** verified client certificate

mTLS may be terminated at the process (TLS layer) or at a private reverse
proxy. Proxy deployments set ``SSL_CLIENT_VERIFY: SUCCESS`` (configurable).
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterable, Mapping
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

PROFILE_SELF_HOSTED = "self_hosted"
PROFILE_PRODUCTION_MTLS = "production_mtls"
_VALID_PROFILES = frozenset({PROFILE_SELF_HOSTED, PROFILE_PRODUCTION_MTLS})


def configured_bearer_tokens() -> frozenset[str]:
    raw = os.environ.get("PRODOCUX_BEARER_TOKENS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def auth_profile_name() -> str | None:
    raw = os.environ.get("PRODOCUX_AUTH_PROFILE", "").strip()
    if not raw:
        return None
    if raw not in _VALID_PROFILES:
        return raw  # invalid — ready will fail closed
    return raw


def mtls_required() -> bool:
    return auth_profile_name() == PROFILE_PRODUCTION_MTLS


def auth_enabled() -> bool:
    """True when bearer checks apply (explicit profile or tokens configured)."""
    profile = auth_profile_name()
    if profile in _VALID_PROFILES:
        return True
    return bool(configured_bearer_tokens())


def auth_profile_document() -> dict[str, Any]:
    """Return the active profile document matching the Phase 0 schema shape."""
    profile = auth_profile_name() or PROFILE_SELF_HOSTED
    if profile not in _VALID_PROFILES:
        profile = PROFILE_SELF_HOSTED
    doc: dict[str, Any] = {
        "schema_version": "prodocux_sidecar_auth_profile_v1",
        "profile": profile,
        "network": "private",
        "request_body_logging": False,
        "public_ingress": False,
        "bearer": {
            "header": "Authorization",
            "scheme": "Bearer",
            "rotatable": True,
            "logged": False,
        },
        "mtls": {"required": profile == PROFILE_PRODUCTION_MTLS},
    }
    return doc


def auth_profile_ok() -> bool:
    """Ready-check: profile name known and required credentials present."""
    profile = auth_profile_name()
    if profile is None:
        return True
    if profile not in _VALID_PROFILES:
        return False
    if not configured_bearer_tokens():
        return False
    return True


def _mtls_verify_header() -> str:
    return os.environ.get("PRODOCUX_MTLS_VERIFY_HEADER", "SSL_CLIENT_VERIFY").strip() or (
        "SSL_CLIENT_VERIFY"
    )


def _mtls_verify_value() -> str:
    return os.environ.get("PRODOCUX_MTLS_VERIFY_VALUE", "SUCCESS").strip() or "SUCCESS"


def client_certificate_verified(headers: Mapping[str, str]) -> bool:
    """Return True when the edge asserts a verified client certificate.

    Accepts the configured proxy verify header, or the presence of a
    non-empty ``X-Forwarded-Tls-Client-Cert`` / ``X-Client-Cert`` header as
    a secondary private-proxy signal.
    """
    verify_header = _mtls_verify_header()
    expected = _mtls_verify_value()
    # Starlette headers are case-insensitive Mapping.
    if headers.get(verify_header) == expected:
        return True
    # Alternate common private-proxy signals (presence = verified).
    for name in ("x-forwarded-tls-client-cert", "x-client-cert"):
        value = headers.get(name)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _safe_error(*, code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "schema_version": "prodocux_safe_error_v1",
            "ok": False,
            "code": code,
            "message": message,
            "retryable": False,
            "request_id": "unauthenticated",
        },
    )


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Enforce bearer (+ optional mTLS) for ``/v1`` when the profile requires it."""

    def __init__(self, app, *, public_paths: Iterable[str] | None = None) -> None:
        super().__init__(app)
        self._public = frozenset(public_paths or ("/health", "/ready"))

    async def dispatch(self, request: Request, call_next) -> Response:
        if not auth_enabled():
            return await call_next(request)
        path = request.url.path
        if path in self._public:
            return await call_next(request)
        if not path.startswith("/v1"):
            return await call_next(request)

        if mtls_required() and not client_certificate_verified(request.headers):
            return _safe_error(
                code="AUTH_MTLS_REQUIRED",
                message="verified client certificate required",
                status_code=401,
            )

        tokens = configured_bearer_tokens()
        if not tokens:
            return _safe_error(
                code="AUTH_MISCONFIGURED",
                message="bearer tokens are not configured for this auth profile",
                status_code=503,
            )

        header = request.headers.get("authorization", "")
        scheme, _, credential = header.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            return _safe_error(
                code="AUTH_REQUIRED",
                message="bearer token required",
                status_code=401,
            )
        if not any(secrets.compare_digest(credential, token) for token in tokens):
            return _safe_error(
                code="AUTH_INVALID",
                message="bearer token rejected",
                status_code=401,
            )
        return await call_next(request)
