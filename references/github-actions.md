# GitHub Actions Quick Guide

## Recommended minimum CI for this repo

- Lint/format checks (if configured)
- CLI help smoke check
- Dry-run/health check
- Optional: query and repair regression checks

## Minimal pattern

- `on`: `push`, `pull_request`, `workflow_dispatch`
- `runs-on`: `ubuntu-latest`
- Step 1: `checkout`
- Step 2: setup runtime
- Step 3: run lightweight checks
