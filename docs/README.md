# Media Ark

A local-first capture processing engine for screenshots, PDFs, and videos.

Includes:

- command-line automation
- web dashboard (`web/`)
- HTTP API server (`src/platform/api_server.py`)
- MCP stdio gateway (`src/platform/mcp_server.py`)

Use this project to turn a raw capture folder into a clean, searchable pipeline of canonical artifacts.

Default behavior moves source files into `.media-ark/` during processing. Use `--copy` if you want to keep originals in `data/captures/raw/`.

API and MCP requests are path-bound by default. `source` and `out` must live under the checkout root or the OS temporary directory unless `MEDIA_ARK_ALLOWED_ROOTS` is set for a deployment.

API and MCP actions persist event logs and per-run reports under the selected output root by default.

Release rollback and recovery commands are documented in [RELEASE.md](RELEASE.md).

Surface-specific onboarding for CLI, API, MCP, and dashboard UI is documented in [ONBOARDING.md](ONBOARDING.md).

Customer-facing endpoint contracts, authentication flows, examples, and export
usage are documented in [api-reference.md](api-reference.md).

Pricing and the free local-only vs Pro encrypted cloud sync/backup split are documented in [PRICING.md](PRICING.md).

Current ship evidence and remote CI status are documented in [SHIP_EVIDENCE.md](SHIP_EVIDENCE.md).
