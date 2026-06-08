# Changelog

All notable changes to this project are documented here.

This project follows [Keep a Changelog](https://keepachangelog.com/) and uses
[Semantic Versioning](https://semver.org/) ideas.

## [Unreleased]

### Added
- Initial repo curation pass: minimal root, `src/`, `tools/`, `docs/`, `.config/` layout.
- Repository-quality docs and community scaffolding (`CONTRIBUTING`, `SECURITY`, `SUPPORT`, issue templates).
- GitHub Actions smoke workflow for CLI verification.

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
