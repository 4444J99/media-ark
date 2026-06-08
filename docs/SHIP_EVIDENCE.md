# Ship Evidence

## Current commit lane

- Branch: `chore/capture-source-race-hardening`
- Local release verifier command: `npm run release:verify`
- Remote workflow: `capture-automation-ci`

## Verified locally on 2026-06-08

`npm run release:verify` passed in the working tree.

The verifier covers:

- unit/platform tests
- deterministic copy-mode engine output for the same input set
- sidecar repair recovery after deleting `manifest.json` and `index.jsonl`
- one-command `npm run platform:start`
- dashboard HTML served from `/`
- API status/run behavior
- MCP initialize/tools/call behavior
- API/MCP telemetry persistence
- API/MCP outside-root path rejection
- required docs and release artifacts

A clean-room copy without `.git`, runtime outputs, caches, or local generated state also passed `npm run release:verify` on 2026-06-08.

## Remote CI status

Remote workflow run `27153235906` was triggered with `workflow_dispatch` for commit `90a66921e3a5d5e6c33cabd098693bcacaaaf54e`.

GitHub Actions did not execute repository steps. The job failed before checkout/setup with this annotation:

```text
The job was not started because recent account payments have failed or your spending limit needs to be increased. Please check the 'Billing & plans' section in your settings
```

This means remote CI pass/fail for the code is not yet proven. Once billing/spending is restored, rerun:

```bash
gh workflow run capture-automation-ci --ref chore/capture-source-race-hardening
gh run watch <run-id> --exit-status
```

## Release decision

Do not mark the finishline complete until a GitHub Actions run executes `npm run release:verify` on the pushed commit and passes.
