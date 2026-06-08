# Screen Capture Automation: Market-Informed Design + Local Automation

## 1) External-market scan (what each steals best from)

- **CleanShot X**
  - Strong post-capture decision UX with immediate actions and context.
  - On-device OCR and clear capture metadata.
  - Reference: https://cleanshot.com/features
- **Snagit**
  - Capture-to-knowledge-asset lifecycle with searchable tagging and collaboration.
  - Reference: https://www.techsmith.com/snagit/features/
- **ShareX**
  - Highly configurable action chains and post-capture command hooks.
  - Reference: https://getsharex.com/features
- **Flameshot**
  - Script-first local workflows and lightweight extensibility.
  - Reference: https://github.com/flameshot-org/flameshot

## 2) Ideal form for this repo

- **Ingest**: deterministic discovery and canonical naming.
- **Process**: media normalization, thumbnailing, and index generation.
- **Enrich**: OCR, keyword extraction, hooks, and integrity checks.

## 3) Storage topology

- `data/captures/raw/`: source captures (input only).
- `.capture-automation/`: generated artifacts and pipeline state.
  - `manifest.json`
  - `index.jsonl`
  - `image/`, `video/`, `document/`
  - `_thumbnails/`
  - `reports/`
  - `pipeline-events.jsonl`

## 3a) Source behavior (important)

- Default processor behavior is **move mode**. Processed source files are removed from `data/captures/raw/` unless `--copy` is enabled.
- If you need source files retained for replay, dedupe recovery, or audit, run in copy mode:
  - `CAPTURE_PIPELINE_COPY=1 ./tools/capture-automation/capture_automation_pipeline.sh data/captures/raw .capture-automation`
  - or add `--copy` to `process_captures.py` / `run_capture_automation.sh`.

## 4) Run commands

```bash
# Dry run
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --dry-run

# Copy mode with one pass
./tools/capture-automation/run_capture_automation.sh data/captures/raw .capture-automation --copy

# Watch mode
./tools/capture-automation/capture_watch_service.sh data/captures/raw .capture-automation --watch

# Full pipeline: check -> process -> verify
./tools/capture-automation/capture_automation_pipeline.sh data/captures/raw .capture-automation
```

## 5) Recommended hardening

1. Keep one root source directory for all raw captures.
2. Use `--check-source` before each run.
3. Enable `--json-report` and optionally `--report` for machine-readable telemetry.
4. Add post-hooks for downstream enrichment and archival.
5. Run `--verify` on a schedule to catch drift.
