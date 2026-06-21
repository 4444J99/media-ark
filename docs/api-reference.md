# API Reference

## CLI API (`process_captures.py`)

### Core options

- `--source` (positional): source path.
- `--out`: output root path.
- `--copy`: copy instead of move.
- `--media-types`: image/video/document/all.
- `--ocr`, `--no-ocr`: OCR toggles.
- `--thumbnails`, `--no-thumbnails`: thumbnail generation.
- `--dry-run`: simulation mode.
- `--watch`: continuous mode.
- `--query`: keyword query over indexed text.
- `--query-media`: filter query by media type.
- `--query-status`: filter query by status.
- `--query-limit`: max query result count.
- `--verify`: run health checks only.
- `--repair`: repair manifest/index drift.
- `--post-hook`: JSON-hook pipeline extension.

### Common workflow entrypoints

- `./tools/media-ark/run_media_ark.sh`
- `./tools/media-ark/media_ark_watch.sh`
- `./tools/media-ark/media_ark_pipeline.sh`

## Platform API (HTTP)

Start server:

```bash
npm run platform:start
```

Base URL: `http://127.0.0.1:8787`

Direct server entrypoint:

```bash
python3 -m src.platform.api_server --host 127.0.0.1 --port 8787
```

### Authentication

The HTTP API stores local users in SQLite at `~/.media-ark/users.db` by default.
Override with `MEDIA_ARK_USERS_DB` when running tests or deployments.
Per-user sandboxes default to `~/.media-ark/users/<username>`; override the
root with `MEDIA_ARK_USER_SANDBOX_ROOT`.

- `POST /api/auth/register` creates a user, a per-user sandbox, and an API key.
- `POST /api/auth/login` verifies the password and rotates the API key.
- `POST /api/auth/api-key` rotates the API key for the bearer-authenticated user.
- All other `/api/*` requests require `Authorization: Bearer <api_key>`.

Register:

```bash
curl -s http://127.0.0.1:8787/api/auth/register \
  -H 'content-type: application/json' \
  -d '{"username":"localuser","password":"change-me-please"}'
```

Use the returned `api_key`:

```bash
curl -s http://127.0.0.1:8787/api/status \
  -H "Authorization: Bearer $MEDIA_ARK_API_KEY"
```

### Runtime security boundary

API and MCP paths are accepted only under configured allowed roots. Authenticated
HTTP API requests are further restricted to the authenticated user's sandbox;
when no `source` or `out` is supplied, the API defaults to `<sandbox>/source`
and `<sandbox>/out`.

- Default allowed roots: the repository root and the OS temporary directory.
- Override with `MEDIA_ARK_ALLOWED_ROOTS`, using the platform path separator (`:` on macOS/Linux).
- `source` and `out` are normalized with symlinks resolved before checks run.
- Requests outside allowed roots return `validation_error` before the engine starts.
- JSON request bodies are capped at 1 MB.
- Platform numeric limits are bounded: `timeout <= 600`, `query_limit <= 1000`, and `max_files <= 50000`.

Example:

```bash
MEDIA_ARK_ALLOWED_ROOTS="/srv/captures:/srv/capture-state" npm run platform:start
```

### Observability

Every API or MCP action persists telemetry by default under the selected `out` root.

- Event log: `<out>/platform-events.jsonl`
- Per-action report: `<out>/reports/platform-<mode>-<run_id>.json`
- `GET /api/status` reports `platform_events_exists`, `reports_exists`, `report_count`, and `latest_report`.
- `POST /api/run` and MCP action results include `event_log` and `report` paths.

The event/report paths can be overridden with `event_log`/`eventLog` and `report`/`reportPath`, but overrides must still pass the allowed-root boundary.

### GET endpoints

- `GET /api/status?source=<source>&out=<out>`
  - returns source/out status, manifest/index existence, and row count.
- `GET /api/manifest?out=<out>`
  - returns parsed manifest payload if present.
- `GET /api/index?source=<source>&out=<out>&limit=<n>&status=<all|processed|duplicate>&media=<all|image|video|document>`
  - returns filtered recent index records.

### Export endpoints (pro tier)

- `GET /api/export/csv?out=<out>` — the index (`index.jsonl`) flattened to CSV.
- `GET /api/export/zip?out=<out>` — `manifest.json` plus every OCR sidecar, bundled into a zip.
- `GET /api/export/json?out=<out>` — the full archive (manifest + index rows + summary) as one JSON document.

All three return a downloadable file (`Content-Disposition: attachment`).

Export is gated behind the pro tier and is ownership-checked:

- Configure authorized tokens with `MEDIA_ARK_PRO_TOKENS`, a comma/newline-separated
  list of `token` or `token:principal` entries (a bare token uses itself as the principal).
- Callers present their token via `Authorization: Bearer <token>`, `X-Api-Key: <token>`,
  or a `token` query parameter.
- Responses: `403 pro_tier_required` (no tokens configured or token not authorized),
  `401 missing_token` (no token supplied), `403 ownership_denied` (the archive's
  `manifest.json` records an `owner` that does not match the caller's principal),
  `404 unknown_format` (format other than `csv`/`zip`/`json`). An archive with no
  recorded `owner` is exportable by any authorized pro caller.

```bash
MEDIA_ARK_PRO_TOKENS="s3cret:alice" npm run platform:start
curl -OJ -H "Authorization: Bearer s3cret" \
  "http://127.0.0.1:8787/api/export/zip?out=.media-ark"
```

### POST endpoint

- `POST /api/run`
  - body: JSON payload
  - required keys: `action` (`process`, `check-source`, `verify`, `repair`, `query`)
  - optional keys:
    - `source`
    - `out`
    - `copy`
    - `dry_run`
    - `max_files`
    - `query`
    - `query_media`
    - `query_status`
    - `query_limit`
    - `no_ocr`, `no_thumbnails`
    - `min_size_bytes`, `max_size_bytes`, `run_id`, `timeout`

Example:

```json
{
  "action": "process",
  "source": "data/captures/raw",
  "out": ".media-ark",
  "copy": true,
  "max_files": 50
}
```

## MCP API (stdio)

Run:

```bash
python3 -m src.platform.mcp_server
```

`npm run platform:start` preflights this stdio contract before starting the API/dashboard surface.

MCP tools use the same allowed-root and input validation as the HTTP API.

Tools:

- `capture_status`
- `capture_check`
- `capture_run`
- `capture_verify`
- `capture_query`
