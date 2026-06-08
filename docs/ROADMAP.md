# Product Roadmap and Finishline

## Lifecycle status

This project follows a complete product lifecycle:

1. Problem definition and validation
2. Platform architecture and contracts
3. Build (pipeline + surfaces)
4. Verification and operations hardening
5. Release engineering
6. Ongoing growth and retention

Current position: **Stage 4/5 (Verification + Release prep)**.

## Finishline (must-have conditions to ship)

- One-command startup of API, MCP, and dashboard in clean environments.
- Deterministic ingest/process/enrich outcome for the same input set.
- End-to-end CI green with API, MCP, and unit tests.
- Public docs for CLI, API, MCP, and dashboard operations.
- Observability: status endpoints, report files, and error signals are persisted.
- Deployment guidance for a practical production or always-on path.
- Governance update: versioned changelog and release acceptance notes.

## Current progress by domain

### P0 (blocking for ship)

- [x] API surface added (`/api/status`, `/api/index`, `/api/manifest`, `/api/run`)
- [x] MCP tools added (`capture_status`, `capture_check`, `capture_run`, `capture_verify`, `capture_query`)
- [x] Dashboard shell added in `web/`
- [x] Test harness scaffold added in `tests/`
- [x] One-command local platform start (`npm run platform:start`) with MCP preflight
- [x] API/MCP path and input validation boundary
- [x] Verified repair path for lost manifest/index recovery
- [x] Persisted API/MCP telemetry reports and event logs
- [x] Surface onboarding for CLI/API/MCP/dashboard UI
- [x] Release verifier covers engine/API/dashboard/MCP/security/docs/recovery
- [ ] Run-time install/deploy hardening (containers, service files, secrets handling)
- [x] Full local clean-environment verifier for API + MCP + dashboard startup

### P1 (important, pre-release)

- [x] Health/telemetry hardening for persisted platform action evidence
- [ ] Data-store durability and backup/restore instructions for `.capture-automation`
- [x] Security hardening for endpoint inputs and run-time boundaries
- [ ] Operations playbook for common failure modes

### P2 (post-launch growth)

- [ ] Scheduled pipeline orchestration and queue model
- [ ] Advanced dashboard analytics and trend views
- [ ] Plugin/integration layer for downstream systems
- [ ] Long-term cleanup and archive/retention policies

## Definition of "done" for any milestone

Each milestone is finished only when:

1. Acceptance criteria are verified in the target environment.
2. The change set is linked in `CHANGELOG.md`.
3. Any user-facing behavior changes are mirrored in docs (`docs/` and `README.md`).
4. A rollback plan exists and has been simulated.

Rollback and recovery commands live in `docs/RELEASE.md`; the sidecar repair recovery path is covered by the test suite.

## 90-day finishline

Ship target: **clean, local-first ingest-to-enrichment loop that can be run as a repeatable service with deterministic outputs**, then iterate on reliability and automation scale.
