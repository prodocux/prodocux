# Phase 3 — verified artifact bytes

Phase 3 freezes **identity-bound verified retrieval** for opaque
`artifact://…` handles. Hosts (Farpals Core) can download bytes only
after supplying the exact identity previously returned in job results
or Kernel store responses, then recheck digest, size, and MIME before
any T2 publication step.

## Kernel routes

| Route | Schema | Purpose |
|-------|--------|---------|
| `POST /v1/artifacts/retrieve` | `prodocux_artifact_retrieve_v1` | Request verified bytes for one opaque identity |
| Response | `prodocux_artifact_content_v1` | Echoes request `artifact`; includes `content_b64` |

Legacy `GET /v1/render/artifacts/{artifact_id}` remains **sink-only**
and is not bound to full opaque identity (no digest contract on GET).
Phase 3 consumers should use `POST /v1/artifacts/retrieve`.

## Auth

Same profiles as Phase 1: `self_hosted` bearer or `production_mtls`
(bearer + verified client cert from trusted edge).

## Byte limit

Kernel rejects retrieval when resolved payload exceeds **32 MiB**
(`_MAX_RETRIEVAL_BYTES` in `api/main.py`) with HTTP **413** and stable
`ARTIFACT_TOO_LARGE` (`prodocux_safe_error_v1`).

Opaque artifact identity schemas allow `size_bytes` up to **100 MiB**
(`104857600`). That is the metadata/store representation ceiling only.
Artifacts larger than the retrieval policy may exist in intake/derived/sink
stores but **must not** be downloaded through `POST /v1/artifacts/retrieve`.
Hosts such as Farpals may apply a stricter local policy (for example 10 MiB)
before publication.

Response `content_b64` schema `maxLength` (~45M) corresponds to the ~32 MiB
retrieval wire ceiling, not the 100 MiB identity ceiling.

## Companion Engine route

Engine exposes job-bound hop:

`POST /internal/v1/jobs/{job_id}/retrieve` — validates terminal job
state, `kind`, and artifact identity against stored results, then calls
Kernel `POST /v1/artifacts/retrieve`.

See `pdx-artifact-engine/docs/phase3/README.md`.

## Farpals handoff

After this freeze, Farpals may implement:

1. `prodocux_publish_artifact` T2 confirmation
2. WordPress Media Library write
3. Compare / evidence / receipt UI

Farpals Phase 3 slice 1 (`prodocux_render_from_blocks`) already
returns metadata only; slice 2 depends on this contract.
