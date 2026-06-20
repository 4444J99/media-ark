# Media Ark API and Usage Reference

This document is the customer-facing reference for integrating with Media Ark.
It covers the HTTP API, pro export downloads, MCP tools, and the CLI commands
that use the same processing engine.

## Base URL

Start the local API and dashboard:

```bash
npm run platform:start
```

Default base URL:

```text
http://127.0.0.1:8787
```

You can also run the server entrypoint directly:

```bash
python3 -m src.platform.api_server --host 127.0.0.1 --port 8787
```

All JSON requests should send:

```text
Content-Type: application/json
```

All JSON responses use UTF-8 and disable HTTP caching with `Cache-Control:
no-store`.

## Quickstart

Create a local API user:

```bash
curl -s http://127.0.0.1:8787/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"acme-ops","password":"change-me-please"}'
```

The response includes a bearer API key and the user's sandbox paths:

```json
{
  "ok": true,
  "user": {"id": 1, "username": "acme-ops"},
  "sandbox": "/Users/alice/.media-ark/users/acme-ops",
  "source": "/Users/alice/.media-ark/users/acme-ops/source",
  "out": "/Users/alice/.media-ark/users/acme-ops/out",
  "api_key": "ma_example"
}
```

Use the returned key on operational API requests:

```bash
export MEDIA_ARK_API_KEY="ma_example"

curl -s http://127.0.0.1:8787/api/status \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY"
```

Run a first source check:

```bash
curl -s http://127.0.0.1:8787/api/run \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"action":"check-source"}'
```

Run processing after you have placed files in the returned `source` directory:

```bash
curl -s http://127.0.0.1:8787/api/run \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"action":"process","copy":true,"max_files":100}'
```

## Authentication

Media Ark has two authentication surfaces.

Operational HTTP API requests use local user API keys:

- Public endpoints: `POST /api/auth/register`, `POST /api/auth/login`.
- Protected endpoints: `GET /api/status`, `GET /api/manifest`,
  `GET /api/index`, `POST /api/auth/api-key`, `POST /api/run`.
- Send protected requests with `Authorization: Bearer <api_key>`.
- Registration, login, and key rotation return the new API key in the response.
- Login and `POST /api/auth/api-key` rotate the key and invalidate the previous
  key.
- API keys are stored as SHA-256 digests, not plaintext.
- Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes.

Pro export endpoints use pro export tokens:

- Export endpoints: `GET /api/export/csv`, `GET /api/export/json`,
  `GET /api/export/zip`.
- Configure tokens with `MEDIA_ARK_PRO_TOKENS`.
- Send the pro token with `Authorization: Bearer <token>`, `X-Api-Key:
  <token>`, or `?token=<token>`.
- Export tokens are independent from local user API keys.
- If an archive manifest includes `owner`, the token principal must match that
  owner.

Usernames are normalized to lowercase. They must be 3-64 characters and may
contain letters, numbers, dot, dash, or underscore after the first character.
Passwords must be at least 8 characters.

## Runtime Boundaries

Authenticated HTTP users are sandboxed. When `source` or `out` is omitted, the
API defaults to:

```text
<user sandbox>/source
<user sandbox>/out
```

For authenticated operational endpoints, any supplied `source`, `out`,
`event_log`, or `report` path must resolve under that user's sandbox.

MCP requests and pro export requests use the configured platform allowed roots:

- Default allowed roots: the repository checkout and the operating system temp
  directory.
- Override with `MEDIA_ARK_ALLOWED_ROOTS`, separated by the platform path
  separator (`:` on macOS/Linux).
- Paths are expanded, resolved, and checked after symlink resolution.
- Requests outside the active boundary return `validation_error`.

Example deployment boundary:

```bash
MEDIA_ARK_ALLOWED_ROOTS="/srv/media-ark:/srv/media-ark-exports" \
  npm run platform:start
```

## Endpoint Summary

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/auth/register` | Public | Create a local user, sandbox, and API key. |
| `POST` | `/api/auth/login` | Public | Verify password and rotate the API key. |
| `POST` | `/api/auth/api-key` | User bearer | Rotate the current user's API key. |
| `GET` | `/api/status` | User bearer | Read source/out health, manifest state, index counts, telemetry, pro flag, and sync status. |
| `GET` | `/api/manifest` | User bearer | Return the parsed `manifest.json` payload for an output root. |
| `GET` | `/api/index` | User bearer | Return filtered records from `index.jsonl`. |
| `POST` | `/api/run` | User bearer | Run processing, source checks, verification, repair, or query actions. |
| `GET` | `/api/export/csv` | Pro token | Download the archive index as CSV. |
| `GET` | `/api/export/json` | Pro token | Download manifest, index rows, summary, and counts as JSON. |
| `GET` | `/api/export/zip` | Pro token | Download `manifest.json` and OCR sidecars as a zip file. |

## Auth Endpoints

### `POST /api/auth/register`

Creates a user, creates `<sandbox>/source` and `<sandbox>/out`, and returns the
first API key.

Request:

```json
{
  "username": "acme-ops",
  "password": "change-me-please"
}
```

Success: `201 Created`

```json
{
  "ok": true,
  "user": {"id": 1, "username": "acme-ops"},
  "sandbox": "/Users/alice/.media-ark/users/acme-ops",
  "source": "/Users/alice/.media-ark/users/acme-ops/source",
  "out": "/Users/alice/.media-ark/users/acme-ops/out",
  "api_key": "ma_example"
}
```

Common errors:

- `400 auth_error`: invalid username or password.
- `400 validation_error`: missing `username` or `password`, invalid JSON, or a
  non-object JSON body.
- `409 user_exists`: username already exists.

### `POST /api/auth/login`

Verifies credentials and returns a newly rotated API key. The previous key is
invalid immediately.

Request:

```json
{
  "username": "acme-ops",
  "password": "change-me-please"
}
```

Success: `200 OK`

```json
{
  "ok": true,
  "user": {"id": 1, "username": "acme-ops"},
  "sandbox": "/Users/alice/.media-ark/users/acme-ops",
  "source": "/Users/alice/.media-ark/users/acme-ops/source",
  "out": "/Users/alice/.media-ark/users/acme-ops/out",
  "api_key": "ma_new_key"
}
```

Common errors:

- `401 invalid_credentials`: username or password did not match.
- `400 auth_error`: invalid username or password format.
- `400 validation_error`: malformed request body.

### `POST /api/auth/api-key`

Rotates the API key for the authenticated user.

Request:

```bash
curl -s http://127.0.0.1:8787/api/auth/api-key \
  -X POST \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{}'
```

Success: `200 OK`

```json
{
  "ok": true,
  "user": {"id": 1, "username": "acme-ops"},
  "sandbox": "/Users/alice/.media-ark/users/acme-ops",
  "source": "/Users/alice/.media-ark/users/acme-ops/source",
  "out": "/Users/alice/.media-ark/users/acme-ops/out",
  "api_key": "ma_rotated_key"
}
```

## Operational Endpoints

### `GET /api/status`

Returns source/output status, manifest and index availability, telemetry files,
pro flag, and sync configuration status.

Query parameters:

| Name | Required | Default | Notes |
| --- | --- | --- | --- |
| `source` | No | `<sandbox>/source` | Must stay inside the user sandbox. |
| `out` | No | `<sandbox>/out` | Must stay inside the user sandbox. |

Example:

```bash
curl -s "http://127.0.0.1:8787/api/status" \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY"
```

Response:

```json
{
  "ok": true,
  "api_version": "1.0",
  "source": "/Users/alice/.media-ark/users/acme-ops/source",
  "out": "/Users/alice/.media-ark/users/acme-ops/out",
  "pro": false,
  "sync": {"configured": false, "provider": "s3", "bucket": "", "prefix": ""},
  "manifest_exists": true,
  "index_exists": true,
  "events_exists": true,
  "pipeline_events_exists": false,
  "platform_events_exists": true,
  "reports_exists": true,
  "report_count": 1,
  "latest_report": "/Users/alice/.media-ark/users/acme-ops/out/reports/platform-check-source-api-123.json",
  "manifest": {"run_id": "api-123", "status": "ok"},
  "index_rows": 42
}
```

### `GET /api/manifest`

Returns the parsed `manifest.json` for an output root. If no manifest exists,
`manifest` is an empty object.

Query parameters:

| Name | Required | Default | Notes |
| --- | --- | --- | --- |
| `out` | No | `<sandbox>/out` | Must stay inside the user sandbox. |

Example:

```bash
curl -s "http://127.0.0.1:8787/api/manifest" \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY"
```

Response:

```json
{
  "manifest": {
    "run_id": "api-123",
    "status": "ok",
    "stats": {"processed": 40, "duplicates": 2}
  }
}
```

### `GET /api/index`

Returns recent records from `index.jsonl`, with optional text, status, media,
and limit filters.

Query parameters:

| Name | Required | Default | Values |
| --- | --- | --- | --- |
| `out` | No | `<sandbox>/out` | Path inside the user sandbox. |
| `source` | No | `<sandbox>/source` | Accepted for parity with other endpoints. |
| `query` | No | empty | Case-insensitive text search across each JSON row, max 500 characters. |
| `limit` | No | `25` | Integer from `0` to `1000`; `0` means no returned records. |
| `status` | No | `all` | `all`, `processed`, `duplicate`. |
| `media` | No | `all` | `all`, `image`, `video`, `document`. |

Example:

```bash
curl -s "http://127.0.0.1:8787/api/index?query=invoice&status=processed&media=image&limit=10" \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY"
```

Response:

```json
{
  "index_rows": 42,
  "records": [
    {
      "id": "aaaa",
      "status": "processed",
      "media_type": "image",
      "canonical_path": "screenshots/2026-06-20/invoice.png",
      "ocr_text": "Invoice 1024"
    }
  ]
}
```

### `POST /api/run`

Runs one capture-platform action. Query parameters and JSON body fields are
merged; body fields win when both are present.

Request field summary:

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `action` | No, but recommended | `process` | `process`, `check-source`, `verify`, `repair`, or `query`. |
| `source` | No | `<sandbox>/source` | Path inside the user sandbox. |
| `out` | No | `<sandbox>/out` | Path inside the user sandbox. |
| `copy` | No | `false` | Copy source files instead of moving them. |
| `dry_run` | No | `false` | Simulate without changing files. Also accepts `dryRun`. |
| `media_types` | No | `all` | `all`, or comma-separated `image`, `video`, `document`. Also accepts `mediaTypes`. |
| `max_files` | No | `0` | Integer `0` to `50000`; `0` means unlimited. Also accepts `maxFiles`. |
| `min_size_bytes` | No | `0` | Integer `0` to `10000000000`. Also accepts `minSizeBytes`. |
| `max_size_bytes` | No | `0` | Integer `0` to `10000000000`; `0` means no max. Also accepts `maxSizeBytes`. |
| `query` | No | empty | Used by `action=query`, max 500 characters. |
| `query_media` | No | `all` | `all`, `image`, `video`, `document`. Also accepts `queryMedia`. |
| `query_status` | No | `all` | `all`, `processed`, `duplicate`. Also accepts `queryStatus`. |
| `query_limit` | No | `50` | Integer `0` to `1000`. Also accepts `queryLimit`. |
| `no_ocr` | No | `false` | Disable OCR. Also accepts `noOcr`. |
| `no_thumbnails` | No | `false` | Disable thumbnails. Also accepts `noThumbnails`. |
| `run_id` | No | generated | 1-96 chars: letters, numbers, dot, underscore, colon, dash. Also accepts `runId`. |
| `timeout` | No | `120` | Seconds, integer `1` to `600`. Also accepts `timeoutSec`. |
| `event_log` | No | `<out>/platform-events.jsonl` | Path inside the user sandbox. Also accepts `eventLog`. |
| `report` | No | `<out>/reports/platform-<action>-<run_id>.json` | Path inside the user sandbox. Also accepts `reportPath`. |

Process example:

```bash
curl -s http://127.0.0.1:8787/api/run \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "process",
    "copy": true,
    "media_types": "image,document",
    "max_files": 100,
    "run_id": "acme-import-001"
  }'
```

Query example:

```bash
curl -s http://127.0.0.1:8787/api/run \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "query",
    "query": "invoice",
    "query_status": "processed",
    "query_limit": 25
  }'
```

Success response:

```json
{
  "mode": "process",
  "ok": true,
  "run_id": "acme-import-001",
  "duration_ms": 287,
  "return_code": 0,
  "source": "/Users/alice/.media-ark/users/acme-ops/source",
  "out": "/Users/alice/.media-ark/users/acme-ops/out",
  "event_log": "/Users/alice/.media-ark/users/acme-ops/out/platform-events.jsonl",
  "report": "/Users/alice/.media-ark/users/acme-ops/out/reports/platform-process-acme-import-001.json",
  "payload": {"ok": true, "processed": 12}
}
```

If the underlying command fails, the response includes `error`, `stdout`, and
`stderr`.

## Pro Export Endpoints

Configure pro tokens before starting the server:

```bash
MEDIA_ARK_PRO_TOKENS="tok_live_acme:acme-ops" npm run platform:start
```

`MEDIA_ARK_PRO_TOKENS` accepts a comma- or newline-separated list. Each entry is
either `token` or `token:principal`. A bare token uses itself as the principal.

Ownership is enforced when the archive manifest includes an `owner` field:

```json
{
  "owner": "acme-ops"
}
```

An archive without `owner` is exportable by any configured pro principal.

### `GET /api/export/csv`

Downloads `index.jsonl` flattened to CSV.

```bash
curl -OJ "http://127.0.0.1:8787/api/export/csv?out=/srv/media-ark/acme/out" \
  -H "Authorization: Bearer $MEDIA_ARK_PRO_TOKEN"
```

Response headers:

```text
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="media-ark-export.csv"
```

### `GET /api/export/json`

Downloads one JSON document containing `manifest`, `index`, `index_summary`,
and `counts`.

```bash
curl -OJ "http://127.0.0.1:8787/api/export/json?out=/srv/media-ark/acme/out" \
  -H "Authorization: Bearer $MEDIA_ARK_PRO_TOKEN"
```

Response headers:

```text
Content-Type: application/json; charset=utf-8
Content-Disposition: attachment; filename="media-ark-export.json"
```

### `GET /api/export/zip`

Downloads `manifest.json` plus per-capture OCR sidecar JSON files under
`sidecars/`.

```bash
curl -OJ "http://127.0.0.1:8787/api/export/zip?out=/srv/media-ark/acme/out" \
  -H "Authorization: Bearer $MEDIA_ARK_PRO_TOKEN"
```

Response headers:

```text
Content-Type: application/zip
Content-Disposition: attachment; filename="media-ark-export.zip"
```

Export errors:

| HTTP | Error | Meaning |
| --- | --- | --- |
| `400` | `validation_error` | `out` is outside allowed roots or otherwise invalid. |
| `401` | `missing_token` | No pro token was supplied. |
| `403` | `pro_tier_required` | No tokens are configured or the supplied token is not authorized. |
| `403` | `ownership_denied` | The token principal does not match `manifest.owner`. |
| `404` | `unknown_format` | Format is not `csv`, `json`, or `zip`. |

## Error Envelope

Most API errors return a JSON object with these fields:

```json
{
  "ok": false,
  "error": "validation_error",
  "message": "source path is outside allowed roots: /allowed/root"
}
```

Common operational errors:

| HTTP | Error | Meaning |
| --- | --- | --- |
| `400` | `validation_error` | Bad JSON, invalid parameter, path outside boundary, or limit violation. |
| `401` | `unauthorized` | Missing or invalid user bearer token. |
| `500` | `command_failed` | The capture command returned a non-zero code. |
| `500` | `runtime_error` | The runtime bridge failed before command execution completed. |
| `500` | `internal_error` | Unhandled server error. Response message is intentionally generic. |

Protected operational endpoints include:

```text
WWW-Authenticate: Bearer realm="media-ark"
```

when a user bearer token is missing or invalid.

## Limits

| Limit | Value |
| --- | --- |
| JSON request body | `1 MB` |
| `query` text | `500` characters |
| `limit` | `0` to `1000` |
| `query_limit` | `0` to `1000` |
| `timeout` | `1` to `600` seconds |
| `max_files` | `0` to `50000` |
| `min_size_bytes` / `max_size_bytes` | `0` to `10000000000` |
| `run_id` | 1-96 characters from `[A-Za-z0-9_.:-]` |

## Observability

Every API or MCP action writes telemetry by default:

```text
<out>/platform-events.jsonl
<out>/reports/platform-<action>-<run_id>.json
```

`GET /api/status` exposes:

- `platform_events_exists`
- `reports_exists`
- `report_count`
- `latest_report`

`POST /api/run` returns the exact `event_log` and `report` paths for the run.

## Admin Configuration

| Variable | Purpose |
| --- | --- |
| `MEDIA_ARK_USERS_DB` | SQLite user database path. Default: `~/.media-ark/users.db`. |
| `MEDIA_ARK_USER_SANDBOX_ROOT` | Parent directory for user sandboxes. Default: `~/.media-ark/users`. |
| `MEDIA_ARK_ALLOWED_ROOTS` | Allowed roots for MCP and export paths. Default: repo root and temp dir. |
| `MEDIA_ARK_SOURCE` | Default source for non-authenticated platform surfaces. |
| `MEDIA_ARK_OUT` | Default output root for non-authenticated platform surfaces. |
| `MEDIA_ARK_PRO` | Enables the pro flag reported by `/api/status`. |
| `MEDIA_ARK_PRO_TOKENS` | Pro export token list, formatted as `token` or `token:principal`. |
| `MEDIA_ARK_SYNC_BUCKET` | Optional encrypted sync destination bucket. |
| `MEDIA_ARK_SYNC_ENDPOINT` | Optional S3/R2-compatible endpoint URL. |
| `MEDIA_ARK_SYNC_REGION` | Optional sync region. Default: `auto`. |
| `MEDIA_ARK_SYNC_PREFIX` | Optional remote sync prefix. |
| `MEDIA_ARK_SYNC_ACCESS_KEY_ID` | Optional sync access key. |
| `MEDIA_ARK_SYNC_SECRET_ACCESS_KEY` | Optional sync secret key. |
| `MEDIA_ARK_VERBOSE` | Set to `1` for verbose API server logging. |

## CLI Usage

The HTTP API delegates to the same processor used by the CLI.

One-shot processing:

```bash
python3 src/media_ark/process_captures.py data/captures/raw \
  --out .media-ark \
  --copy \
  --max-files 100
```

Query OCR/index text:

```bash
python3 src/media_ark/process_captures.py data/captures/raw \
  --out .media-ark \
  --query "invoice" \
  --query-format jsonl
```

Health and repair:

```bash
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --check-source
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --verify
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --repair
```

Convenience wrappers:

```bash
./tools/media-ark/run_media_ark.sh data/captures/raw .media-ark
./tools/media-ark/media_ark_watch.sh data/captures/raw .media-ark --watch
./tools/media-ark/media_ark_pipeline.sh data/captures/raw .media-ark
```

Core CLI options:

| Option | Purpose |
| --- | --- |
| `--out` | Output root. |
| `--copy` | Copy instead of move. |
| `--media-types` | `image`, `video`, `document`, or `all`. |
| `--ocr` / `--no-ocr` | Enable or disable OCR. |
| `--thumbnails` / `--no-thumbnails` | Enable or disable thumbnails. |
| `--dry-run` | Simulate without changing files. |
| `--watch` | Continuous watch mode. |
| `--query` | Search indexed text. |
| `--query-media` | Filter query by media type. |
| `--query-status` | Filter query by status. |
| `--query-limit` | Limit query results. |
| `--verify` | Run health checks only. |
| `--repair` | Repair manifest/index drift. |
| `--post-hook` | Run a JSON-hook pipeline extension. |

## MCP Usage

Run the MCP stdio bridge:

```bash
python3 -m src.platform.mcp_server
```

`npm run platform:start` preflights this stdio contract before starting the API
and dashboard.

Available tools:

| Tool | Purpose |
| --- | --- |
| `capture_status` | Read manifest/index status for a source/out pair. |
| `capture_check` | Run `--check-source`. |
| `capture_run` | Process captures once. |
| `capture_verify` | Run `--verify`. |
| `capture_query` | Search indexed captures by text and filters. |

MCP uses the same runtime validation, command bridge, telemetry output, and
allowed-root checks as the non-authenticated platform surfaces.
