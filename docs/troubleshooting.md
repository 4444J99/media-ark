# Troubleshooting

## Nothing is being processed

1. Ensure your files are in `data/captures/raw/` or the source path you pass.
2. Use `--verbose` and `--check-source` to inspect scan behavior.
3. Verify extensions are supported: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.tiff`, `.heic`, `.avif`, `.mov`, `.mp4`, `.m4v`, `.webm`, `.avi`, `.mkv`, `.mpg`, `.mpeg`, `.pdf`.

## Watch mode exits immediately

- Check if `--max-runs` is set to `0` for indefinite mode.
- Confirm no stale lock: remove `.capture-automation/manifest.lock` only if safe.

## OCR isn't available

- Install `tesseract` to enable text extraction and title inference.

## Wrapper path errors

- Confirm scripts are executable (`chmod +x tools/capture-automation/*.sh`).
