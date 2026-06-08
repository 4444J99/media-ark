# Getting Started

## 1. Clone / open the repo

```bash
git clone <repo-url>
cd <repo>
```

## 2. Confirm the source layout

- Source captures: `data/captures/raw/`
- Core engine: `src/capture_automation/process_captures.py`
- Automation wrappers: `tools/capture-automation/`

## 3. Run a dry run

```bash
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --dry-run
```

## 4. Start automation with copy mode

```bash
./tools/capture-automation/run_capture_automation.sh data/captures/raw .capture-automation --copy
```

## 5. Inspect outputs

- `manifest.json`
- `index.jsonl`
- `image/`, `video/`, `document/`
- `reports/`

## 6. Keep it running

Use `capture_watch_service.sh` for periodic watch mode.

## 7) Product surfaces (API + dashboard + MCP)

Run once and open the control UI:

```bash
npm run platform:start
```

Open `http://127.0.0.1:8787/` in a browser. The command also preflights MCP because the MCP surface is stdio-based and starts per client session.

Expose tooling interface:

```bash
python3 -m src.platform.mcp_server
```
