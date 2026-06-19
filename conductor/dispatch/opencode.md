# Dispatch projection: opencode

This is the **lens-shaped view of the `media-ark` conductor
surface for opencode-kind agents** (the `opencode` CLI,
`~/.local/bin/opencode` at the version pinned in the conductor
environment, and any tool that identifies as an opencode-derived
agent).

It is *not* a copy of the canonical handoff. It is a
projection: same source facts, agent-shaped scope and authority.

## Identity (read first)

You are operating as **opencode**. The session's source of truth for
the repo's state is the canonical handoff. The session's source
of truth for cross-agent rules is
[`../fleet-standing-rules.md`](../fleet-standing-rules.md) and
[`../routing.toml`](../routing.toml).

The 0.2.0 handoff names opencode explicitly: *"Opencode CLI
(not claude-code): MIT/4jp, v1.0.219. `opencode -s <id>` resumes
a session."* You are the agent that *resumes* sessions; the
session-ID discipline is yours to maintain.

## What you are authorized to do (read `routing.toml` first)

| Intent | Authorized? | Notes |
|---|---|---|
| `verify` | yes | Local `npm run release:verify` is the ground truth. Report `ok: true` or the failing gate name. |
| `triage` | no (in default) | Read-only on issues is fine; commenting is `claude`/`jules`/`gpt-scheduled`. |
| `commit` | yes | One DONE per commit. Conventional Commits subject. Feature branch. |
| `push` | yes | Feature branch only. Never force, never `main`. |
| `pr-draft` | yes | PR body must include purpose, impacted paths, validation commands, linked issues. Squash-merge path. |
| `pr-merge` | **no** | Conductor-only. Hand the conductor a ready-to-paste `gh pr merge` command. |
| `worktree-new` | **yes** | You are the only agent with the cross-host Desktop peer convention (`~/Desktop/media-ark--<name>`). Other agents use `~/Workspace/4444J99/media-ark--<name>`. |
| `worktree-prune` | **no** | Conductor-only. You may *propose* with evidence; you may not execute. |
| `handoff-write` | yes | Doc-only. PR title `docs:`. |
| `fleet-handoff-author` | yes | New-lane work, not closeout continuation. PR title `feat:`. |

## Repo surfaces you must read on cold start

1. `docs/handoff/media-ark-0.2.0-2026-06-10.md` — current state, completed work, key decisions, next actions, risks, recovery protocol, cold start protocol.
2. `MERGE_PATH.md` §"What actually blocks the PR merge" — branch protection reality.
3. `docs/SHIP_EVIDENCE.md` — verified-evidence surface.
4. `docs/regression-findings.md` — the S1/S2/S3 + F1–F9 narrative.
5. `src/media_ark/__init__.py` — the brand module.
6. `git worktree list` — current worktree inventory, before claiming a lane.
7. `gh pr list --state open` — current open PRs, before claiming a lane.

## Standing rules you must obey

- **Additive only.** (Standing rule #1.)
- **Squash-merge only.** (Standing rule #2.)
- **Atomic commits.** (Standing rule #3.)
- **N/A is a vacuum.** (Standing rule #4.)
- **No destroy without conductor auth.** (Standing rule #5.)
- **Reflog first.** (Standing rule #6.)
- **Local `npm run release:verify` is the ground truth.** (Standing rule #7.)
- **All review threads resolved before merge.** (Standing rule #8.)
- **Conductor fleet rule (new).** When more than one agent is
  active on this repo, no two agents may operate on the same
  branch or the same worktree simultaneously. Check `git worktree
  list` and the open PR list before claiming a lane. If your
  target lane is taken, **stop and report** — do not start a
  parallel session on the same lane. (Standing rule #9, added
  in the 2026-06-11 conductor-evolve session.)

## Blind spots (what you cannot do even if you think you should)

- **You cannot merge a PR.** Same as codex.
- **You cannot register a self-hosted runner.** Conductor decision.
- **You cannot touch a secret.** `secrets-map.md` is skeleton.
- **You cannot detect a peer-agent stepping on your work.**
  Standing rule #9 is enforced by `git worktree list` checks at
  session start, not by an automated gate. If you start a
  session and a peer agent has already advanced the same branch
  in a parallel worktree, your `git push` will fail with a
  non-fast-forward error — that is the gate, not a prevention.
- **You cannot detect a session-id collision.** The 0.2.0
  handoff's reference (`opencode -s <id>`) assumes the
  session-id scheme is unique per session. If you resume a
  session-id that a peer agent is also using, the two sessions
  will interleave their tool calls. The mitigation is in the
  cold-start protocol: check `git worktree list` *and* the
  session-id before claiming a lane.
- **You cannot detect a "named follow-up" that drifts.**
  Standing rule #4.

## Worktree convention (you are the only agent with this authority)

```
# Cross-host Desktop peer (the 0.2.0 closeout's convention)
git worktree add -b <branch> ~/Desktop/media-ark--<purpose> origin/main

# Workspace peer (the canonical AGENTS.md convention)
git worktree add -b <branch> ~/Workspace/4444J99/media-ark--<purpose> origin/main
```

- The Desktop peer is reserved for sessions that the conductor
  has explicitly asked to live there (the 0.2.0 closeout's
  `media-ark--container-2026-06-10` is the historical example;
  the new fleet surfaces use the workspace peer, e.g.
  `media-ark--pr-17-fleet`).
- The workspace peer is the default.
- The worktree name format is `media-ark--<purpose>` (double-hyphen,
  per the workspace's `4444J99/AGENTS.md` §"Project Structure &
  Module Organization" convention).
- After the worktree's branch is fully merged to `main` and
  untouched for 14+ days, an agent may *propose* the prune
  but may not execute (conveyor-only).

## What "lane-clean" means for an opencode session

An opencode session is lane-clean when:

- `git rev-parse HEAD` matches the expected branch tip.
- `git status --porcelain` for tracked files is empty.
- `npm run release:verify` returns `{"ok": true, ...}`.
- The session's work landed as one squash-merged PR (or is staged
  on a feature branch awaiting PR).
- If the session created a worktree, the worktree is named per
  the convention above and listed in `git worktree list`.
- The session's narrative names any named gaps it surfaced
  (per Rule #4).

## Cross-references

- [`../routing.toml`](../routing.toml) — the intent → agent map
- [`../fleet-standing-rules.md`](../fleet-standing-rules.md) — the shared invariants and per-agent override slots
- [`../../docs/handoff/media-ark-0.2.0-2026-06-10.md`](../../docs/handoff/media-ark-0.2.0-2026-06-10.md) — the canonical handoff
- [`../../MERGE_PATH.md`](../../MERGE_PATH.md) — the merge policy this projection extends
