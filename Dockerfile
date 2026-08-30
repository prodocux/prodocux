# ProDocuX Kernel — Phase 1 private sidecar image.
#
# Layout (ADR-0003 / PHASE0_DECISIONS):
#   /                         read-only root (container)
#   /var/lib/prodocux/tmp     writable ephemeral work (+ intake under tmp/intake)
#   /var/lib/prodocux/artifacts writable output sink (+ derived under artifacts/derived)
#
# Example:
#   docker build -t prodocux-kernel:phase1 -f Dockerfile .
#   docker run --read-only \
#     -v pdx-tmp:/var/lib/prodocux/tmp \
#     -v pdx-out:/var/lib/prodocux/artifacts \
#     -e PRODOCUX_AUTH_PROFILE=self_hosted \
#     -e PRODOCUX_BEARER_TOKENS=dev-token \
#     -e PRODOCUX_ARTIFACT_MOUNT=/var/lib/prodocux/artifacts \
#     -e PRODOCUX_TMP_MOUNT=/var/lib/prodocux/tmp \
#     -e PRODOCUX_DERIVED_MOUNT=/var/lib/prodocux/artifacts/derived \
#     -p 8900:8900 prodocux-kernel:phase1
#
# production_mtls: set PRODOCUX_AUTH_PROFILE=production_mtls and terminate TLS
# with client-cert verification at the private edge (or forward
# SSL_CLIENT_VERIFY=SUCCESS from a trusted reverse proxy). Bearer remains required.

FROM python:3.11-slim@sha256:1042b61448fef4ba92d16a8c7eb4996d027568ce64792a7877fd88511e0af7c6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PRODOCUX_ARTIFACT_MOUNT=/var/lib/prodocux/artifacts \
    PRODOCUX_TMP_MOUNT=/var/lib/prodocux/tmp \
    PRODOCUX_INTAKE_MOUNT=/var/lib/prodocux/tmp/intake \
    PRODOCUX_DERIVED_MOUNT=/var/lib/prodocux/artifacts/derived \
    PRODOCUX_AUTH_PROFILE=self_hosted

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY api ./api
COPY prodocux_kernel ./prodocux_kernel
COPY run_kernel.py ./

RUN pip install --no-cache-dir . \
    && pip uninstall -y pip setuptools \
    && mkdir -p /var/lib/prodocux/tmp/intake \
               /var/lib/prodocux/artifacts/derived \
    && useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin pdx \
    && chown -R pdx:pdx /var/lib/prodocux

USER pdx

EXPOSE 8900

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8900/health')"

CMD ["python", "-c", "import uvicorn; uvicorn.run('api.main:app', host='0.0.0.0', port=8900)"]
