# Surface Onboarding

## CLI

Use the CLI when running local automation directly or from shell wrappers.

```bash
npm run capture:dry-run
npm run capture:run
npm run capture:pipeline
```

Expected evidence:

- `.capture-automation/manifest.json`
- `.capture-automation/index.jsonl`
- `.capture-automation/reports/`
- optional event logs from `--event-log`

Verification:

```bash
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --verify --json-report
```

## API

Start the platform:

```bash
npm run platform:start
```

Run a source check:

```bash
curl -sS -H 'content-type: application/json' \
  -d '{"action":"check-source","source":"data/captures/raw","out":".capture-automation"}' \
  http://127.0.0.1:8787/api/run
```

Expected evidence:

- response field `ok: true`
- response fields `event_log` and `report`
- `GET /api/status` shows `platform_events_exists: true` and `report_count >= 1`

## MCP

Start a stdio MCP session:

```bash
python3 -m src.platform.mcp_server
```

Send newline-delimited JSON-RPC:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"capture_status","arguments":{"source":"data/captures/raw","out":".capture-automation"}}}
```

Available tools:

- `capture_status`
- `capture_check`
- `capture_run`
- `capture_verify`
- `capture_query`

## Dashboard UI

Open:

```text
http://127.0.0.1:8787/
```

Use the dashboard to:

- set `source` and `out`
- run source checks, processing, verification, and queries
- inspect service health and the latest action response
- view indexed capture rows

The dashboard uses the same API/MCP runtime boundary. Paths outside `CAPTURE_PLATFORM_ALLOWED_ROOTS` are rejected.

## Clean Checkout Check

From a fresh checkout with Python and Node available:

```bash
npm run release:verify
```

Then verify:

- `/api/status` returns `ok: true`
- `/` serves the dashboard
- `python3 -m src.platform.mcp_server` responds to `initialize` and `tools/list`
