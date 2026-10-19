# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/) and uses
[Semantic Versioning](https://semver.org/) ideas.

## [Unreleased] — Renamed to Media Ark

### Changed
- **Product name: `screen-capture-automation` → `media-ark`** (display: "Media Ark"). Domain: `media-ark.org` (registered 2026-06-10 via Cloudflare). GitHub repo: `4444J99/media-ark` (rename pending post-PR-#13).
- Python package: `src/capture_automation/` → `src/media_ark/`.
- Operational wrappers: `tools/capture-automation/` → `tools/media-ark/` (and 4 scripts renamed: `run_media_ark.sh`, `media_ark_watch.sh`, `media_ark_pipeline.sh`, `start_media_ark.sh`).
- Default data directory: `.capture-automation/` → `.media-ark/`.
- Env-var prefix: `CAPTURE_PLATFORM_*` → `MEDIA_ARK_*` (no shim; this is a breaking change for any external consumer of those env vars).
- HTTP `Server:` response header: `CapturePlatform/1.0` → `MediaArk/1.0`.
- MCP `serverInfo.name`: `screen-capture-platform` → `media-ark`.
- npm package name: `screen-capture-automation` → `media-ark`.
- npm scripts: `capture:*` → `media-ark:*` (the `platform:*` scripts are unchanged).
- Web UI default `--out` value: `.capture-automation` → `.media-ark`.
- `.gitignore` rule: `.capture-automation/` → `.media-ark/`.
- Workflow `automation-ci.yml` paths updated; workflow `name: capture-automation-ci` **kept** for runner-pickup continuity (issue #5).

### Added
- **`pyproject.toml`**: Python project metadata; `[project] name = "media-ark"`, `[project.urls] Homepage = "https://media-ark.org"`, `[project.scripts] media-ark = "media_ark.process_captures:main"`, etc. Canonical Python project metadata surface.
- **`src/media_ark/__init__.py` brand module**: single source of truth for the product's identity. Exports `BRAND_NAME`, `BRAND_DISPLAY`, `BRAND_DOMAIN`, `BRAND_REPO_URL`, `BRAND_DATA_DIR`, `BRAND_NPM`, `BRAND_PYTHON_PKG`, `BRAND_ENV_PREFIX`, `BRAND_MCP_NAME`, `BRAND_SERVER_VERSION`, and `env_key(suffix)`. The product's identity strings are now *data*, not strings baked into source. Renaming the product is a one-file change.
- `src/platform/config.py` reads `BRAND_DATA_DIR` and `BRAND_ENV_PREFIX` from the brand module; env-var names are derived via `env_key("SOURCE")` etc.
- `src/platform/api_server.py` reads `BRAND_SERVER_VERSION`; `MEDIA_ARK_VERBOSE` env var (was `CAPTURE_PLATFORM_VERBOSE`).
- `src/platform/mcp_server.py` reads `BRAND_MCP_NAME`.
- `tools/media-ark/verify_release.py` reads `BRAND_PYTHON_PKG`, `BRAND_DATA_DIR`, and `env_key(...)` from the brand module.
- README h1 updated to "Media Ark"; storage-model section documents the brand module.

### Not changed
- Workflow name `capture-automation-ci` (runner-pickup continuity).
- MCP tool names `capture_status`, `capture_check`, `capture_run`, `capture_verify`, `capture_query` (API contract; renaming these would break MCP clients).
- The 12 prior closeout files in `~/.Codex/plans/` (historical record; references the old repo URL by design).

### Verified
- GitHub Actions workflow for dependabot github-actions update (#1635125501) completed successfully on main (https://github.com/4444J99/media-ark/actions/runs/39187403257). CI green after actions/setup-python and related bumps. Receipt: small progress step on near-release product.
- Dependabot "pip in /." update (#1635125348) succeeded (https://github.com/4444J99/media-ark/actions/runs/39187400842, commit ff0d8ba4c3db12443b3b1cbd0bc7fe0c945a01d3). Receipt: green progress step on near-finished Stage 4/5 repo.

## [0.2.0] — 2026-06-10

### Added
- `docs/legacy-data-2026-06-10.md` — provenance and migration recipe for the pre-rename capture snapshot (`.media-ark-data-legacy-2026-06-10/`, 771 MB / 548 files).
- GitHub repo metadata aligned with the Media Ark brand: `description` ("Media Ark: a local-first media archive pipeline for images, video, PDF, and documents."), `homepageUrl` (`https://media-ark.org`), and topics (`media-pipeline`, `local-first`, `ocr`, `automation`, `data-pipeline`, `python`; `screen-capture` removed).
- Re-verification record in `docs/SHIP_EVIDENCE.md` (§"Re-verification on 2026-06-10 (post-rename, post-PR-#13)").

### Changed
- `.gitignore` — `.media-ark-data-legacy-2026-06-10/` excluded from version control (preserved on disk; documented in `docs/legacy-data-2026-06-10.md`).
- `docs/PROFILE_README.md` — title and product description updated from "Screen Capture Automation" to "Media Ark"; brand section added.

### Verified
- `npm run release:verify` exits `ok: true` on `main` at commit `1e89e5b` (engine: New=4 duplicates=0 errors=0; all 5 verifier gates green: unit/platform suite, deterministic engine + sidecar recovery, one-command API/dashboard startup, MCP contract + telemetry, docs + release artifacts).
- Runner-pickup GitHub-Actions issue unchanged (documented as known, non-blocking; branch protection does not require it).

## [0.1.0] — 2026-06-09 (renamed entry)

### Added
- Initial repo curation pass: minimal root, `src/`, `tools/`, `docs/`, `.config/` layout.
- Repository-quality docs and community scaffolding (`CONTRIBUTING`, `SECURITY`, `SUPPORT`, issue templates).
- GitHub Actions smoke workflow for CLI verification.
- One-command platform startup (`npm run platform:start`) with API/dashboard launch and MCP preflight.
- Regression coverage for operational shell wrappers and copy-mode idempotency.
- API/MCP allowed-root path validation, bounded platform inputs, and invalid-request tests.
- Sidecar-based repair recovery for lost manifest/index state, with release rollback documentation.
- Default persisted platform telemetry: API/MCP event logs, per-action reports, and status evidence fields.
- Surface onboarding documentation for CLI, API, MCP, and dashboard UI.
- Release verifier command covering engine determinism, API/dashboard startup, MCP, security rejection, docs, telemetry, and recovery.
- Ship evidence artifact recording local clean-room proof and current remote CI blocker.

### Changed
- Centralized source file moved into `src/capture_automation/process_captures.py`.
- Runtime orchestrators moved to `tools/capture-automation/`.
- Raw capture inputs standardized under `data/captures/raw/`.
- Output/state artifacts standardized under `.capture-automation/`.

### Fixed
- Wrapper script path resolution to source entrypoint.
- Reduced root clutter and duplicate config surface.

## [0.1.0] - 2026-06-08

### Added
- Initial structured release of screen capture ingestion pipeline.
- Ingest, process, and enrich automation with idempotent indexing.
- Watch mode, query mode, and verification tooling.
