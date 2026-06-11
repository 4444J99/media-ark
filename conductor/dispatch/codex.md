# Dispatch projection: codex

This is the **lens-shaped view of the `media-ark` conductor
surface for Codex-kind agents** (ChatGPT Codex, codex-connector,
and any tool that identifies as a Codex-derived agent).

It is *not* a copy of the canonical handoff. It is a
projection: same source facts, agent-shaped scope and authority.
When the canonical handoff at
`docs/handoff/media-ark-0.2.0-2026-06-10.md` updates, this
projection may need re-rendering.

## Identity (read first)

You are operating as **codex**. The session's source of truth for
the repo's state is the canonical handoff. The session's source
of truth for cross-agent rules is
[`../fleet-standing-rules.md`](../fleet-standing-rules.md) and
[`../routing.tables.toml` (parseable) and `../routing.md` (narrative)](../routing.tables.toml).

## What you are authorized to do (read `routing.tables.toml` (and `routing.md`) first)

| Intent | Authorized? | Notes |
|---|---|---|
| `verify` | yes | Local `npm run release:verify` is the ground truth. Report `ok: true` or the failing gate name. |
| `triage` | no | Read-only on issues is fine; commenting is `claude`/`jules`/`gpt-scheduled`. |
| `commit` | yes | One DONE per commit. Conventional Commits subject. Feature branch. |
| `push` | yes | Feature branch only. Never force, never `main`. |
| `pr-draft` | yes | Squash-merge path. Resolve all review threads before merging. |
| `pr-merge` | **no** | Conductor-only. Hand the conductor a ready-to-paste `gh pr merge` command. |
| `worktree-new` | no (in default) | `opencode` is the only agent with the cross-host Desktop peer convention. Codex uses `~/Workspace/4444J99/media-ark--<name>`. |
| `worktree-prune` | **no** | Conductor-only. You may *propose* with evidence; you may not execute. |
| `handoff-write` | yes | Doc-only. PR title `docs:`. PR body must include the parity-gap rationale if it closes a parity gap. |
| `fleet-handoff-author` | yes | New-lane work, not closeout continuation. PR title `feat:`. |

## Repo surfaces you must read on cold start

1. `docs/handoff/media-ark-0.2.0-2026-06-10.md` — current state, completed work, key decisions, next actions, risks, recovery protocol, cold start protocol.
2. `MERGE_PATH.md` §"What actually blocks the PR merge" — branch protection reality.
3. `docs/SHIP_EVIDENCE.md` — verified-evidence surface.
4. `docs/regression-findings.md` — the S1/S2/S3 + F1–F9 narrative (the discipline you should imitate when writing new handoff content).
5. `src/media_ark/__init__.py` — the brand module. Identity is data; renaming is a one-file change.

## Standing rules you must obey

- **Additive only.** No overwriting prior artifacts. (Standing rule #1.)
- **Squash-merge only.** Branch protection `required_linear_history: true` enforces it; you enforce it by not opening `--merge` or `--rebase` PRs.
- **Atomic commits.** One DONE per commit. (Standing rule #3.)
- **N/A is a vacuum.** Name it. (Standing rule #4.)
- **No destroy without conductor auth.** (Standing rule #5.) This includes `git worktree remove`, `git branch -D`, `git reset --hard`, `git clean -fd`.
- **Reflog first.** 90-day window. Never claim work is "lost" without `git reflog` and `git fsck --unreachable` first. (Standing rule #6.)
- **Local `npm run release:verify` is the ground truth.** (Standing rule #7.)

## Blind spots (what you cannot do even if you think you should)

- **You cannot merge a PR.** Even if all review threads are
  resolved and the verifier is green. The merge button is the
  conductor's; you hand the conductor a `gh pr merge <N> --squash
  --delete-branch` command and stop. The 0.2.0 handoff's parity
  gap was caused by an agent attempting a direct push to `main`;
  the same rule forbids you from triggering a merge.
- **You cannot register a self-hosted runner.** Issue #5's
  close-criterion (self-hosted-runner registration vs.
  `not_planned`) is a conductor decision. You may *post a status
  comment* with `gh run list` evidence; you may not take an
  action that resolves the issue.
- **You cannot touch a secret the `secrets-map.md` skeleton has
  not authorized.** The skeleton is `unset — awaiting conductor`
  for every cell. The default is no access. Wait for the
  conductor to fill the cell.
- **You cannot detect a "named follow-up" that drifts.** Standing
  rule #4 names a gap; you do not own the gap's resolution. The
  `docs/regression-findings.md` §"F2 Blindspot A" pattern is the
  discipline: name the gap, point at the manual-review path,
  do not close the gap yourself unless the conductor has
  authorized it.
- **You cannot detect an additive-in-spirit-but-destructive-in-form
  change.** Standing rule #1 is enforced by commit-message
  discipline and human review, not by an automated gate. The
  PR review is the gate.

## What "lane-clean" means for a codex session

A codex session is lane-clean when:

- `git rev-parse HEAD` matches `git rev-parse origin/main` (or
  matches a feature branch the session was authorized to advance).
- `git status --porcelain` for tracked files is empty.
- `npm run release:verify` returns `{"ok": true, ...}`.
- The session's work landed as one squash-merged PR (or is staged
  on a feature branch awaiting PR).
- The session's narrative names any named gaps it surfaced
  (per Rule #4) and did not silently absorb them.

## Cross-references

- [`../routing.tables.toml` (parseable) and `../routing.md` (narrative)](../routing.tables.toml) — the intent → agent map
- [`../fleet-standing-rules.md`](../fleet-standing-rules.md) — the shared invariants
- [`../../docs/handoff/media-ark-0.2.0-2026-06-10.md`](../../docs/handoff/media-ark-0.2.0-2026-06-10.md) — the canonical handoff
- [`../../MERGE_PATH.md`](../../MERGE_PATH.md) — the merge policy this projection extends
