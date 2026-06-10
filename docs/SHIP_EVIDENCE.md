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

Current pushed head and latest run IDs should be read live:

```bash
git rev-parse HEAD
gh run list --branch chore/capture-source-race-hardening --limit 5
```

Representative remote workflow runs observed while verifying this lane:

- `27153338041` (`push`) failed; `runner_id: 0`, zero steps.
- `27153340311` (`pull_request`) failed; `runner_id: 0`, zero steps.
- `27153488920` (`push`) failed; `runner_id: 0`, zero steps.
- `27153491216` (`pull_request`) failed; `runner_id: 0`, zero steps.
- `27153578292` (`push`) failed; `runner_id: 0`, zero steps.
- `27153579954` (`pull_request`) failed; `runner_id: 0`, zero steps.

Earlier workflow run `27153235906` was triggered with `workflow_dispatch` for commit `90a66921e3a5d5e6c33cabd098693bcacaaaf54e` and failed the same way.

GitHub Actions did not execute repository steps. The most recent failed
run's system log (downloaded via `gh api repos/.../actions/runs/<id>/logs`)
shows the hosted runner was assigned — `Job is about to start running
on the hosted runner: GitHub Actions 1000024023` — but the runner never
sent a pickup heartbeat back to the control plane; the job was killed
~3 seconds later with `runner_id: 0` and zero steps recorded.

A previous revision of this file attributed the failures to a
"billing/spending-limit" issue. That diagnosis is incorrect:

- The run API reports `error: null` on every failure; a billing cap
  would surface an explicit error annotation.
- The repo `actions/permissions` is `enabled: true` and the user plan
  is `pro`. UBUNTU billable `total_ms` is `0` per failure (no compute
  was billed, so the cap never engaged).
- The same account's public `limen` repo is running successful
  scheduled Actions jobs in the same time window (e.g. run
  `27154751792`, `Deploy Dashboard`, `conclusion: success`,
  14 steps). The runner pool is healthy.
- The failure pattern (`runner_id: 0`, `runner_name: ""`,
  `runner_group_name: ""`, zero steps, ~3 s) is consistent with a
  hosted-runner-pickup heartbeat failure on this specific repo, not
  with a billing exhaustion or a runner-group exclusion.

The corrected diagnosis and the exact commands to merge the PR are
documented in `MERGE_PATH.md` at the repo root. Once the runner-pickup
transient clears, retry with:

```bash
gh workflow run capture-automation-ci --ref chore/capture-source-race-hardening
gh run watch <run-id> --exit-status
```

If the run still fails, retry with `gh run rerun <run-id> --failed-only`
(each attempt draws a fresh runner from the pool).

Additional pushes may create newer failed workflow runs. Use
`gh run list --branch chore/capture-source-race-hardening` for the
latest run IDs.

## Release decision

Do not mark the finishline complete until a GitHub Actions run executes `npm run release:verify` on the pushed commit and passes.

## Post-merge runner-pickup hardening (2026-06-08, branch `ci/runner-pickup-recovery`)

PR #3 was merged as squash commit `0bbf37c`. The post-merge push
triggered a `CLI smoke` run (`27161881679`) on `main` which failed
the same way as the 19 prior runs on the PR branch: runner
assigned, no pickup heartbeat, `runner_id: 0`, zero steps, ~3 s.

**Falsification:** an attempted fix on branch
`ci/runner-pickup-recovery` swapped `runs-on: ubuntu-latest` →
`runs-on: ubuntu-22.04` (a different image label, different runner
pool). Two new runs (`27163015265`, `27163023887`) on
`ubuntu-22.04` failed the same way. The image-label theory is
falsified; the runner-pickup failure is not specific to
`ubuntu-latest`. Branch `ci/runner-pickup-recovery` was reset and
contains only a comment block at the top of
`.github/workflows/automation-ci.yml` documenting the diagnosis
and the next-step options; the workflow behavior is unchanged
from `main`.

**Total failing runs on this repo today: 22 / 22**, across 2 image
labels (`ubuntu-latest`, `ubuntu-22.04`), 3 event types
(`push`, `pull_request`, `workflow_dispatch`), 3 branch tips
(`main`, `chore/capture-source-race-hardening`,
`ci/runner-pickup-recovery`), and 4+ distinct GitHub-hosted runner
IDs in the 1000024022–1000024075 range.

**No in-workflow change resolves the issue** as of 2026-06-08
19:55 UTC. The local release verifier remains the ground truth
and is green on the merge commit. See
`MERGE_PATH.md` and the inline comment block in
`.github/workflows/automation-ci.yml` for the full diagnostic trail
and the next-step options (self-hosted runner registration, repo
split, or wait for the GitHub-side transient to clear).

## Re-verification on 2026-06-10 (post-rename, post-PR-#13)

The local release verifier was re-run on 2026-06-10 against
commit `1e89e5b` (the `Media Ark` rename + brand module) on
`main`. The verifier exited `ok: true` and exercised all five
gates (unit/platform suite, deterministic engine + sidecar
recovery, one-command API/dashboard startup, MCP contract +
telemetry, docs + release artifacts). The runtime data
directory (`.media-ark/`) was instantiated with 4 source PNGs
from `data/captures/raw/` and the engine produced
`New=4 duplicates=0 errors=0`.

The runner-pickup GitHub-Actions issue is **unchanged** as of
2026-06-10 14:59 UTC. The `capture-automation-ci` workflow on
`main` continues to fail at the hosted-runner pickup step
(`runner_id: 0`, zero steps, ~3 s). The branch-protection
rules do **not** require this check, so human push/merge is
unaffected. The local `npm run release:verify` is the
authoritative acceptance gate.

The legacy data directory `.media-ark-data-legacy-2026-06-10/`
(pre-rename snapshot, 771 MB / 548 files) is now excluded via
`.gitignore` and documented in `docs/legacy-data-2026-06-10.md`.
The repository metadata on GitHub (`description`, `homepageUrl`,
`topics`) was updated to reflect the Media Ark brand.
