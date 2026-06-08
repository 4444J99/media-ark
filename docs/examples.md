# Examples

## End-to-end one-shot run

```bash
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --copy --max-files 100
```

## Watch with retention

```bash
./tools/capture-automation/capture_watch_service.sh data/captures/raw .capture-automation --watch --interval 15 --max-runs 0 --copy
```

## Querying OCR text

```bash
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --query "invoice" --query-format jsonl
```

## Health + repair

```bash
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --check-source
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --verify
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --repair --repair-orphan-assets
```
