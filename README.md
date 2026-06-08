<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/dynamic-banner.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/light-banner.svg">
  <img alt="Screen Capture Automation banner" src="docs/assets/light-banner.svg" />
</picture>

<h1 align="center">Screen Capture Automation</h1>

<p align="center">
  <img alt="CI" src="https://img.shields.io/badge/CI-automated-brightgreen" />
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" />
  <img alt="License" src="https://img.shields.io/badge/License-MIT-0f172a" />
  <img alt="Status" src="https://img.shields.io/badge/Status-local%20first%20pipeline-1f2937" />
</p>

<h2 align="center">Automates the one-day "cleanup day" into one-hour deterministic loops.</h2>

## Table of Contents

- [Problem](#problem)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Storage Model](#storage-model)
- [Commands](#commands)
- [Maintenance](#maintenance)
- [Governance](#governance)

## Problem

Raw screenshots, PDFs, and recordings are created faster than they can be curated manually.

This repo provides a resilient, local-first pipeline that converts raw captures into:

- canonicalized media layouts,
- sidecar metadata,
- OCR/keyword enrichment,
- queryable indexes,
- repairable state.

## Architecture

```mermaid
flowchart TD
  A[Raw source\ndata/captures/raw] --> B[Ingest scan]
  B --> C[Deduplicate + canonical naming]
  C --> D[Process and normalize]
  D --> E[Generate thumbnails/OCR metadata]
  E --> F[Append sidecar + index]
  F --> G[State and reports]
  G --> H[Query + verify + repair]
```

## Quick Start

### 1) Dry run against local captures

```bash
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --dry-run
```

### 2) One-shot ingest + enrich

```bash
./tools/capture-automation/run_capture_automation.sh data/captures/raw .capture-automation --copy
```

### 3) Start unattended watch mode

```bash
./tools/capture-automation/capture_watch_service.sh data/captures/raw .capture-automation --watch --interval 10 --max-runs 0
```

### 4) Run full check/process/verify cycle

```bash
./tools/capture-automation/capture_automation_pipeline.sh data/captures/raw .capture-automation
```

## Product Surfaces (CLI, API, MCP, Dashboard)

### API + dashboard

Start the platform in one command:

```bash
npm run platform:start
```

The command creates the default source/output directories, preflights the stdio MCP tool contract, then starts the API and dashboard at `http://127.0.0.1:8787/`.

Start UI + API directly:

```bash
python3 -m src.platform.api_server --host 127.0.0.1 --port 8787
```

- Open `http://127.0.0.1:8787/` for the dashboard.
- `GET /api/status?source=<path>&out=<path>`
- `GET /api/manifest?out=<path>`
- `GET /api/index?out=<path>&limit=<n>&status=<all|processed|duplicate>&media=<all|image|video|document>`
- `POST /api/run` with JSON `{"action":"process|check-source|verify|repair|query","source":"...","out":"..."}`

### MCP (stdio)

```bash
python3 -m src.platform.mcp_server
```

Exposed tools:

- `capture_status`
- `capture_check`
- `capture_run`
- `capture_verify`
- `capture_query`

### CLI remains the primary automation engine

```bash
npm run capture:run
npm run capture:watch
npm run capture:pipeline
```

Run verification:

```bash
npm run release:verify
```

## Storage Model

- `data/captures/raw/` — incoming captures.
- `src/capture_automation/` — core engine.
- `src/platform/` — API/MCP runtime bridge.
- `tools/capture-automation/` — operational wrappers.
- `.capture-automation/` — canonical outputs, manifests, indexes, events.
- `.config/` — examples and tooling presets.
- `docs/` — guides and operational references.
- `web/` — dashboard UI shell.

## Commands

```bash
# Query indexed OCR text
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --query "meeting"

# Source scan summary only
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --check-source

# Health check only
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --verify

# Repair drift and stale state
python3 src/capture_automation/process_captures.py data/captures/raw --out .capture-automation --repair --repair-orphan-assets
```

## Maintenance

- Add hooks via `--post-hook` for downstream enrichment.
- Keep `data/captures/raw/` as the only inbound source.
- Use `--cleanup-raw` carefully (copy mode recommended).
- Use `--event-log` and `--report` for run telemetry.
- API/MCP actions persist telemetry by default to `.capture-automation/platform-events.jsonl` and `.capture-automation/reports/`.
- Use `CAPTURE_PLATFORM_ALLOWED_ROOTS` to restrict API/MCP `source` and `out` paths in deployed environments.

## Governance

- [Contributing](.github/CONTRIBUTING.md)
- [Security](.github/SECURITY.md)
- [Support](.github/SUPPORT.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [License](LICENSE)
- [Changelog](CHANGELOG.md)

## Documentation

- [docs/](docs/README.md)
- [docs/CAPTURE_PIPELINE.md](docs/CAPTURE_PIPELINE.md)
- [docs/getting-started.md](docs/getting-started.md)
- [docs/ONBOARDING.md](docs/ONBOARDING.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/RELEASE.md](docs/RELEASE.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)
