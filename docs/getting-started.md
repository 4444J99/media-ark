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
