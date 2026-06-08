# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/) and uses
[Semantic Versioning](https://semver.org/) ideas.

## [Unreleased]

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
