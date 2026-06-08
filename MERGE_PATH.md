# Merge Path: screen-capture--060826

This file documents the corrected diagnosis for the failing PR #3 CI runs
and the exact commands needed to merge the branch once the runner
scheduling issue is resolved. It is the artifact for the 2026-06-08
review session; the canonical evidence in `docs/SHIP_EVIDENCE.md` is
updated separately.

## Corrected diagnosis (2026-06-08)

The previous handoff claimed the failing CI runs on
`chore/capture-source-race-hardening` were due to a "GitHub Actions
billing/spending-limit" issue preventing jobs from starting before
checkout. The new evidence disproves that.

**Observations that falsify the billing claim:**

| Signal | Value | Why it disproves billing |
|---|---|---|
| `error` field on the failing run API | `null` | Billing failures produce an explicit error annotation |
| Repo `actions/permissions` | `enabled: true` | Actions are not disabled |
| User plan | `pro` (private_repos: 9999) | Not a free-tier-cap scenario |
| UBUNTU billable `total_ms` per failing run | `0` | No compute was billed, so the cap never engaged |
| `runner_id` on every failing job | `0` | No runner was ever assigned |
| `runner_name` on every failing job | `""` | No runner was ever assigned |
| `runner_group_name` on every failing job | `""` | No runner group was matched |
| `steps` on every failing job | `[]` | The workflow body never executed |
| `created_at` → `updated_at` interval | ~3 seconds | A billing cap fails immediately, not after 3s |
| Same pattern on every branch since 14:57 UTC today | 16/16 runs | Not branch-specific |
| Same account, same time, on the public `limen` repo | 2/2 successful, 9–14 steps each | Runner pool is healthy in this account |

**Direct log evidence (latest failing run, downloaded via
`gh api repos/.../actions/runs/<id>/logs`):**

```text
2026-06-08T16:58:58.366Z Requested labels: ubuntu-latest
2026-06-08T16:58:58.366Z Job defined at: .../.github/workflows/automation-ci.yml@refs/pull/3/merge
2026-06-08T16:58:58.366Z Waiting for a runner to pick up this job...
2026-06-08T16:58:58.343Z Evaluating smoke.if
2026-06-08T16:58:58.343Z Result: true
2026-06-08T16:58:58.828Z Job is waiting for a hosted runner to come online.
2026-06-08T16:58:58.827Z Job is about to start running on the hosted runner: GitHub Actions 1000024023
```

The log ends at "Job is about to start running" and then nothing. A
hosted runner was assigned (numeric ID 1000024023, in the same range as
successful runs in `limen` and `a-i--skills`), but the runner never
sent a heartbeat back. The job was killed ~3 seconds after scheduling
and recorded with `runner_id: 0` because the runner never confirmed
pickup.

**Conclusion:** this is a runner-pickup heartbeat failure on this
specific repo, not a billing exhaustion, not a runner-group exclusion,
not a workflow file parse error, and not a step-content issue. The
runner's connection to the GitHub control plane is being terminated
right at job handoff. The most likely cause is a GitHub Actions
transient / capacity issue specific to this repo, and the only safe
remediation is to wait and retry.

## What actually blocks the PR merge

`required_status_checks.contexts` and `checks` on `main` are both
empty, so the failing `CLI smoke` check is not a merge blocker. The
real blocker is the **`required_conversation_resolution: true`** rule
on `main` branch protection combined with **11 unresolved review
threads** on PR #3 (gemini-code-assist[bot] and
chatgpt-codex-connector[bot]). All 11 substantive findings have been
addressed in the review branch `review/screen-capture-platform-2026-06-08`
(see the regression test file `tests/test_review_findings_regression.py`).
The threads still need to be marked resolved on GitHub after the
review branch lands on `chore/capture-source-race-hardening`.

`mergeStateStatus` is `blocked` for conversation reasons, not for CI.

## Commands to merge the PR

### Step 1 — fast-forward the public branch with the review fixes

```bash
cd /Users/4jp/Desktop/screen-capture--060826
git fetch origin review/screen-capture-platform-2026-06-08
git checkout chore/capture-source-race-hardening
git merge --ff-only origin/review/screen-capture-platform-2026-06-08
git push origin chore/capture-source-race-hardening
```

### Step 2 — reply to and resolve each PR review thread

For each of the 11 threads, post a one-line "addressed in
\<commit-SHA\>" reply, then click "Resolve conversation".

```bash
# Inspect thread IDs (replace with the right PR if not #3)
gh api repos/4444J99/screen-capture--060826/pulls/3/comments \
  --jq '.[] | {id, path, line, user: .user.login, resolved: false}'
```

### Step 3 — re-trigger CI to get a green run

```bash
gh workflow run capture-automation-ci --ref chore/capture-source-race-hardening
gh run list --branch chore/capture-source-race-hardening --limit 3 \
  --json databaseId,headSha,status,conclusion,event,createdAt,url
# wait for completion
gh run watch <run-id> --exit-status
```

If the runner-pickup issue persists, retry with `gh run rerun` (each
new attempt gets a new runner from the pool):

```bash
gh run rerun <run-id> --failed-only
```

### Step 4 — merge

```bash
gh pr merge 3 --squash --delete-branch
```

### Rollback (if a regression is caught after merge)

```bash
gh pr close 3          # before merge
# or
git revert -m 1 <merge-sha>   # after merge
```

## Runner-group diagnostic read-only probes (already run)

The following `gh api` calls were executed during the review session
to rule out org/policy-level runner exclusions. They are included here
so the next session does not have to re-run them:

```bash
# All of these return 404 / empty because the user-level endpoints
# GitHub exposes for self-hosted runner groups are org-only.
gh api user/runner-groups
gh api /user/actions/runner-groups
gh api /orgs/4444J99/actions/runner-groups
gh api /user/actions/permissions
# Repo-level (returns useful data):
gh api repos/4444J99/screen-capture--060826/actions/runners
gh api repos/4444J99/screen-capture--060826/actions/permissions
gh api repos/4444J99/screen-capture--060826/actions/permissions/workflow
```

`repos/.../actions/runners` returned `{"total_count": 0, "runners": []}`,
confirming the repo has no self-hosted runners registered; the failures
are on the hosted runner pool, which is shared and working for other
repos in the account.

## Companion artifacts

- `docs/SHIP_EVIDENCE.md` — corrected in this same branch to remove
  the "billing/spending-limit" claim and point future agents at
  `gh run list` for live evidence.
- `tests/test_review_findings_regression.py` — 12 tests covering the
  11 review-thread findings.
- `~/.Codex/plans/closeout-2026-06-08-review-screen-capture-platform.md`
  — session closeout superseding the prior
  `closeout-2026-06-08-screen-capture-platform.md`.
