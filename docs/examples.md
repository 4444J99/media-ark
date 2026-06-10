# Examples

## End-to-end one-shot run

```bash
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --copy --max-files 100
```

## Watch with retention

```bash
./tools/media-ark/media_ark_watch.sh data/captures/raw .media-ark --watch --interval 15 --max-runs 0 --copy
```

## Querying OCR text

```bash
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --query "invoice" --query-format jsonl
```

## Health + repair

```bash
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --check-source
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --verify
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --repair --repair-orphan-assets
```
