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

- `./tools/capture-automation/run_capture_automation.sh`
- `./tools/capture-automation/capture_watch_service.sh`
- `./tools/capture-automation/capture_automation_pipeline.sh`

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

### Runtime security boundary

API and MCP paths are accepted only under configured allowed roots.

- Default allowed roots: the repository root and the OS temporary directory.
- Override with `CAPTURE_PLATFORM_ALLOWED_ROOTS`, using the platform path separator (`:` on macOS/Linux).
- `source` and `out` are normalized with symlinks resolved before checks run.
- Requests outside allowed roots return `validation_error` before the engine starts.
- JSON request bodies are capped at 1 MB.
- Platform numeric limits are bounded: `timeout <= 600`, `query_limit <= 1000`, and `max_files <= 50000`.

Example:

```bash
CAPTURE_PLATFORM_ALLOWED_ROOTS="/srv/captures:/srv/capture-state" npm run platform:start
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
  "out": ".capture-automation",
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
