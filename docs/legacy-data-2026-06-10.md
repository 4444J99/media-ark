# Legacy capture data (2026-06-10 snapshot)

## What this is

`.media-ark-data-legacy-2026-06-10/` in the repo root is a 771 MB
snapshot of the runtime data directory from the **pre-rename**
workspace (`/Users/4jp/Desktop/screen-capture--060826/`, renamed to
`media-ark` on 2026-06-10).

It contains:

- 548 files: PNG screenshots, MOV screen recordings, PDF documents.
- 3 canonical subtrees: `image/`, `document/`, `video/`, organized
  by year/month from the previous run.
- `_thumbnails/` (image + document).
- `manifest.json`, `manifest.backup.json` (pre-rename paths still
  point at `/Users/4jp/Desktop/screen-capture--060826/`).
- `index.jsonl` (1 row) and `index-summary.json` (1 image, 0 video,
  0 document, 1 duplicate).
- One stray sidecar: `20260321_110357_31ac97f478.png.json` at the
  root (its `source_path` and `canonical_path` also reference the
  pre-rename workspace).

## Why it's preserved on disk but not git-tracked

The data is a real artifact of the prior run — not noise, not a
mistake. The contents are intact and could be re-ingested by the
current engine to produce a fresh `manifest.json` and `index.jsonl`
in the new (`.media-ark/`) directory. **They are not re-ingested
automatically** because:

1. The manifest `errors` array is a 130-row log of "no such file or
   directory" failures pointing at the pre-rename workspace. The
   current engine's narrow-source-missing path
   (`run_stats['skipped']` vs `run_stats['failed']`) treats those
   as skipped, not failed. Re-running on the preserved binaries
   alone would produce a clean manifest — but the source paths
   inside the JSONL index still reference the old workspace and
   would be a maintenance trap.
2. The binaries are 771 MB. The repo is meant to stay lean; the
   0.2.0 source tree is < 5 MB.

## How to use it

If you want to migrate the legacy data into the current pipeline:

```bash
# 1. Copy the canonical subtrees into the new source layout
mkdir -p data/captures/raw
cp -R .media-ark-data-legacy-2026-06-10/image data/captures/raw/
cp -R .media-ark-data-legacy-2026-06-10/document data/captures/raw/
cp -R .media-ark-data-legacy-2026-06-10/video data/captures/raw/

# 2. Run the engine against the new source path
npm run media-ark:run

# 3. Inspect the new manifest, then remove the legacy snapshot
#    (and the data/captures/raw/ copy) when satisfied
```

If you don't want it on disk at all, remove the directory
(`rm -rf .media-ark-data-legacy-2026-06-10/`) and this docs file
is the only remaining record.

## Provenance

- Created: 2026-06-08 (during the pre-rename run series).
- Renamed snapshot: 2026-06-10 (alongside the `screen-capture-automation` →
  `media-ark` rename, PR #13).
- `index-summary.json` `generated_at`: `2026-06-08T16:04:17.793341Z`.
- `manifest.json` `created_at`: `2026-06-08T13:50:14.250982Z`.
- `manifest.json` `run_id`: `run-1780934650-80286`.
- `manifest.json` `stats.files_seen_total`: 575.
- `manifest.json` `stats.errors`: 130 (all `FileNotFoundError` to the
  pre-rename workspace, by design — the source list was
  cross-machine).
