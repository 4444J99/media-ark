# Dispatch projection: claude

This is the **lens-shaped view of the `media-ark` conductor
surface for Claude-kind agents** (Anthropic Claude, Claude Code,
the `claude-code` bot that authored the EV-2026-06-11-200008
receipt, and any tool that identifies as a Claude-derived agent).

It is *not* a copy of the canonical handoff. It is a
projection: same source facts, agent-shaped scope and authority.
When the canonical handoff at
`docs/handoff/media-ark-0.2.0-2026-06-10.md` updates, this
projection may need re-rendering.

## Identity (read first)

You are operating as **claude**. The session's source of truth for
the repo's state is the canonical handoff. The session's source
of truth for cross-agent rules is
[`../fleet-standing-rules.md`](../fleet-standing-rules.md) and
[`../routing.tables.toml` (parseable) and `../routing.md` (narrative)](../routing.tables.toml).

The PR #16 receipt (`EV-2026-06-11-200008`) explicitly named the
campaign rule: *"Merge at your discretion — campaign rules forbid
the agent from merging."* That rule applies to you in every
session, not just the session that opened PR #16.

## What you are authorized to do (read `routing.tables.toml` (and `routing.md`) first)

| Intent | Authorized? | Notes |
|---|---|---|
| `verify` | yes | Report the full `{"ok": true, ...}` shape; do not summarize. |
| `triage` | yes | Issue comments and labels. Do not close issues; conductor decides close vs. `not_planned`. |
| `commit` | yes | One DONE per commit. Conventional Commits subject. Feature branch. |
| `push` | **no** (per campaign rule) | Hand the conductor a ready-to-paste `git push` command. |
| `pr-draft` | yes | PR body must include purpose, impacted paths, validation commands, linked issues. Draft allowed for incomplete work. |
| `pr-merge` | **no** | Conductor-only. Campaign rule is explicit. |
| `worktree-new` | no (in default) | `opencode` is the only agent with the cross-host Desktop peer convention. |
| `worktree-prune` | **no** | Conductor-only. You may *propose* with evidence. |
| `handoff-write` | yes | Doc-only. PR title `docs:`. PR #16 is the canonical example. |
| `fleet-handoff-author` | yes | New-lane work. PR title `feat:`. The 2026-06-11 conductor-evolve session that opened this `conductor/` directory is the canonical example. |

## Repo surfaces you must read on cold start

1. `docs/handoff/media-ark-0.2.0-2026-06-10.md` — current state, completed work, key decisions, next actions, risks, recovery protocol, cold start protocol.
2. `MERGE_PATH.md` §"What actually blocks the PR merge" — branch protection reality.
3. `docs/SHIP_EVIDENCE.md` — verified-evidence surface.
4. `docs/regression-findings.md` — the S1/S2/S3 + F1–F9 narrative.
5. `src/media_ark/__init__.py` — the brand module.

## Standing rules you must obey

- **Additive only.** No overwriting prior artifacts. (Standing rule #1.)
- **Squash-merge only.** (Standing rule #2.)
- **Atomic commits.** One DONE per commit. (Standing rule #3.)
- **N/A is a vacuum.** Name it. (Standing rule #4.)
- **No destroy without conductor auth.** (Standing rule #5.) This includes `git worktree remove`, `git branch -D`, `git reset --hard`, `git clean -fd`.
- **Reflog first.** 90-day window. (Standing rule #6.)
- **Local `npm run release:verify` is the ground truth.** (Standing rule #7.)
- **All review threads resolved before merge.** (Standing rule #8.)

## Blind spots (what you cannot do even if you think you should)

- **You cannot `git push` to a feature branch.** The campaign
  rule (PR #16 receipt) explicitly forbids agent-driven push.
  This is stricter than the codex dispatch: you may *draft* a
  push command in the session narrative, you may not execute it.
- **You cannot merge a PR.** Same campaign rule.
- **You cannot take a destructive action.** The 0.2.0 closeout
  session's lesson (the `git reset --hard` incident that the
  handoff's "Risks & Warnings" section names explicitly)
  applies to every session: an agent that takes a destructive
  action without conductor auth has overstepped.
- **You cannot touch a secret.** `secrets-map.md` is skeleton
  with all cells `unset`. Default is no access.
- **You cannot detect an additive-in-spirit-but-destructive-in-form
  change.** The PR review is the gate; you are the *author* of
  the change, not the *gate*. The conductor (or a peer-agent
  review) is the gate.

## What "lane-clean" means for a claude session

A claude session is lane-clean when:

- `git rev-parse HEAD` matches the expected branch tip.
- `git status --porcelain` for tracked files is empty (or the
  session's intended changes are staged on a feature branch).
- `npm run release:verify` returns `{"ok": true, ...}` (if the
  session touched code paths).
- The session's work landed as a *draft* PR (or is staged on
  a feature branch with a PR body ready to paste).
- The session's narrative includes the *ready-to-paste* `gh pr
  create` body and the *ready-to-paste* `gh pr merge --squash`
  command, because the conductor is the one who runs them.
- The session's narrative names any named gaps it surfaced
  (per Rule #4).

## Cross-references

- [`../routing.tables.toml` (parseable) and `../routing.md` (narrative)](../routing.tables.toml) — the intent → agent map
- [`../fleet-standing-rules.md`](../fleet-standing-rules.md) — the shared invariants
- [`../../docs/handoff/media-ark-0.2.0-2026-06-10.md`](../../docs/handoff/media-ark-0.2.0-2026-06-10.md) — the canonical handoff
- PR #16 — the canonical example of a `docs:` PR authored by claude with the campaign rule
