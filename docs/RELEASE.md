# Release and Recovery Plan

## Release acceptance gates

A release is acceptable only when all gates pass on the release commit:

1. `npm run release:verify`
2. CI runs `npm run release:verify` on the release commit and passes.

The verifier covers unit tests, deterministic engine output, API/dashboard startup, MCP tools, persisted telemetry, operational path rejection, required docs, rollback text, and sidecar recovery.

## Rollback plan

1. Stop the API/dashboard process.
2. Preserve current state before changing anything:

```bash
mkdir -p .media-ark/recovery
tar -czf ".media-ark/recovery/state-$(date -u +%Y%m%dT%H%M%SZ).tgz" .media-ark
```

3. Restore the last known-good checkout or release tag.
4. Keep `.media-ark/` in place unless the failure is known to be state corruption.
5. Run:

```bash
npm test
npm run release:verify
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --verify
```

6. If verification reports missing index or manifest state, run the recovery path below.

## Verified recovery path

The repair command rebuilds manifest and index state from surviving sidecar JSON when `manifest.json` or `index.jsonl` is lost.

```bash
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --repair --json-report
python3 src/media_ark/process_captures.py data/captures/raw --out .media-ark --verify --json-report
```

Use `--repair-orphan-assets` only after preserving a tarball backup; it prunes sidecars and thumbnails that no longer map to canonical assets.

The automated suite verifies this path by processing a capture, deleting `manifest.json` and `index.jsonl`, running `--repair`, then requiring `--verify` to return healthy.

Current release evidence and external CI blockers are tracked in [SHIP_EVIDENCE.md](SHIP_EVIDENCE.md).
