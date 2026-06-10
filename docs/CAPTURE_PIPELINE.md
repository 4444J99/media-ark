# Media Ark: Market-Informed Design + Local Automation

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
- `.media-ark/`: generated artifacts and pipeline state.
  - `manifest.json`
  - `index.jsonl`
  - `image/`, `video/`, `document/`
  - `_thumbnails/`
  - `reports/`
  - `pipeline-events.jsonl`

## 3a) Source behavior (important)

- Default processor behavior is **move mode**. Processed source files are removed from `data/captures/raw/` unless `--copy` is enabled.
- If you need source files retained for replay, dedupe recovery, or audit, run in copy mode:
  - `CAPTURE_PIPELINE_COPY=1 ./tools/media-ark/media_ark_pipeline.sh data/captures/raw .media-ark`
  - or add `--copy` to `process_captures.py` / `run_media_ark.sh`.

## 4) Run commands

```bash
# Dry run
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --dry-run

# Copy mode with one pass
./tools/media-ark/run_media_ark.sh data/captures/raw .media-ark --copy

# Watch mode
./tools/media-ark/media_ark_watch.sh data/captures/raw .media-ark --watch

# Full pipeline: check -> process -> verify
./tools/media-ark/media_ark_pipeline.sh data/captures/raw .media-ark
```

## 5) Recommended hardening

1. Keep one root source directory for all raw captures.
2. Use `--check-source` before each run.
3. Enable `--json-report` and optionally `--report` for machine-readable telemetry.
4. Add post-hooks for downstream enrichment and archival.
5. Run `--verify` on a schedule to catch drift.
