# API Reference (CLI)

## `process_captures.py`

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
- `--verify`: run health checks only.
- `--repair`: repair manifest/index drift.
- `--post-hook`: JSON-hook pipeline extension.

### Common workflow entrypoints

- `./tools/capture-automation/run_capture_automation.sh`
- `./tools/capture-automation/capture_watch_service.sh`
- `./tools/capture-automation/capture_automation_pipeline.sh`
