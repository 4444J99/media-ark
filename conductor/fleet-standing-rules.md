# Fleet standing rules

This file is the **cross-agent extension of `MERGE_PATH.md`**. It
carries the rules that apply to *every* agent kind working on
`media-ark`, plus the per-agent override slots where an agent's
authority differs from the default.

It does **not** duplicate `MERGE_PATH.md`. The merge policy
(squash-only, linear history, conversation-resolution-required,
no-force-push, no-direct-push-to-main) lives there. This file
extends that policy into the agent-fleet axis: which agent kind
may take which action, what the shared invariants are, and where
the per-agent blind spots are.

## Shared invariants (apply to every agent, every session)

These are the rules that come from the repo's actual closeout
discipline (see `docs/SHIP_EVIDENCE.md`, `docs/regression-findings.md`,
and the 15-PR squash-merge history). They are not negotiable.

| # | Invariant | Source | Blind spot (what this rule cannot enforce) |
|---|---|---|---|
| 1 | **Additive only.** No overwriting prior artifacts (CHANGELOG entries, commit SHAs, branch names, prior handoff content). | House rule; 0.2.0 closeout narrative; `docs/SHIP_EVIDENCE.md` | Cannot detect "additive in spirit but destructive in form" (e.g. rewriting a CHANGELOG entry to *add* a section that contradicts a prior section's meaning). Manual review path. |
| 2 | **Squash-merge only.** All PRs land via squash, matching the #1–#15 pattern. | `MERGE_PATH.md`; branch protection `required_linear_history: true` | Cannot detect squash-merge commits that *contain* a non-squash history inside them (e.g. a rebase-and-squash of a previously-merged branch). Visible only in `git log --graph` post-merge. |
| 3 | **Atomic commits (one DONE per commit).** | 0.2.0 closeout narrative; `docs/regression-findings.md` discipline | Cannot detect a single commit that *bundles* inseparable work items under one subject line. The S1 walker's "name what you can't enforce" pattern applies: the rule is enforced by commit-message discipline, not by an automated gate. |
| 4 | **N/A is a vacuum — name it, don't paper over it.** Missing propagation, missing infrastructure, missing authority boundaries become named follow-up work, never silently absorbed. | House rule; closeout narrative §"Key Decisions" | Cannot detect "named follow-up" that drifts into the indefinite future. A named gap with no owner and no deadline is paper-over with a TODO comment. Manual review path; see `docs/regression-findings.md` §"F2 Blindspot A" for the discipline pattern. |
| 5 | **No destroy without conductor auth.** Never `git worktree remove`, `git branch -D`, `git push --force`, `git reset --hard`, or `gh repo delete` without explicit conductor authorization in the session. | 0.2.0 closeout narrative §"Risks & Warnings"; `docs/handoff/media-ark-0.2.0-2026-06-10.md` recovery protocol | Cannot detect "soft destroy" (e.g. `git restore` on a tracked file that an untracked file was meant to extend; `git clean -fd` on a directory containing untracked-but-precious artifacts). The 0.2.0 closeout's own lesson: `git reset --hard` removes both tracked changes AND staged-but-not-committed untracked files. |
| 6 | **Reflog is recoverable for 90 days.** Never claim work is "lost" without checking `git reflog` and `git fsck --unreachable` first. | 0.2.0 closeout narrative; `MERGE_PATH.md` §"Runner-group diagnostic probes" | Cannot detect work that was *never committed* (e.g. a file written to a worktree that was then `git worktree remove`'d without commit). Untracked-then-deleted is gone. The 0.2.0 closeout had 677 dangling commits — recoverable. A scratch file in a worktree that got removed is not recoverable. |
| 7 | **Local `npm run release:verify` is the ground truth.** The `capture-automation-ci` GitHub Actions check is informational only under the current branch protection (no required status checks, zero required approvals, conversation-resolution-required). | 0.2.0 closeout narrative; `MERGE_PATH.md`; `docs/SHIP_EVIDENCE.md` | Cannot detect a `release:verify` that passes locally but is not reproducible in a clean checkout. The PR #1 fix (deterministic smoke workflow) and the F9 addendum (`tox.ini` matrix on py311 + py314) are the mitigations. |
| 8 | **All review threads resolved before merge.** Required by `required_conversation_resolution: true`. The 0.2.0 squash-merge used `--admin` override only *after* both Gemini review threads were resolved via GraphQL. | `MERGE_PATH.md`; 0.2.0 closeout narrative | Cannot detect a thread that is "resolved" on GitHub but whose underlying code change was not actually made. Resolution is a state change, not a verification. |

## Branch and PR discipline (extends `MERGE_PATH.md`)

These are the rules that govern how an agent's work *lands* on
`main`. They are already enforced by branch protection; this
section is the human-readable form for agents.

| # | Rule | Source | Blind spot |
|---|---|---|---|
| B1 | Branch names: `chore/`, `feat/`, `fix/`, `docs/`, `ci/`, `evolve/` prefix; kebab-case suffix. 0.2.0 closeout session used `session-closeout-2026-06-10` (unprefixed) and the new fleet surfaces use `docs/2026-06-10-0.2.0-fleet-handoff` (date-suffixed). The convention is *not* rigid; agents should match the prefix to the intent. | 15-PR history; `MERGE_PATH.md` | Cannot detect a branch name that is technically well-formed but semantically misleading (e.g. `chore/...` for what is actually a `feat/...`). |
| B2 | One PR per DONE. Multiple inseparable items in one squash-merge are acceptable if the items *cannot* be merged independently (see Rule #3 atomic-commits). | 0.2.0 closeout narrative | Cannot detect a PR that claims inseparability but whose commits could actually land independently. Manual review. |
| B3 | No direct push to `main` (even admins). Branch protection `enforce_admins: true` rejects it. The 0.2.0 handoff's parity gap was caused by an attempt to direct-push a doc-only change. | `MERGE_PATH.md` §"What actually blocks the PR merge"; 0.2.0 handoff §"Key Decisions" | Cannot detect a direct-push *attempt* that the agent does not surface in the session narrative. The branch-protection hook is the only enforcement. |
| B4 | All PRs target `main`. The repo's branch protection only protects `main`; feature branches have no protection. | Branch protection settings (live) | Cannot detect a feature-branch-only push that the agent does not intend to land (e.g. an experiment). The rule applies to "PRs that will land on main," not to all branch activity. |

## Per-agent override slots

This is where an agent's authority differs from the default. The
default for any unlisted agent is **read-only on the repo, no
secrets, no push, no gh comment, no force, no destroy**.

| Agent kind | Read scope | Write scope | Force / destroy | Secrets | gh comment | `git push` | Source |
|---|---|---|---|---|---|---|---|
| `codex` | full | commits on feature branches | no | TBD (`secrets-map.md` is skeleton) | yes (after own-PR) | feature branches only, never `main` | inferred from PR #15 (Codex review-thread fixes), 0.2.0 closeout narrative |
| `claude` | full | draft PR bodies, draft docs | no | TBD | yes | no (per `EV-2026-06-11-200008` campaign rule) | PR #16 PR body, the "campaign rules forbid the agent from merging" line |
| `gemini` | full | code review comments only | no | none | yes (review only) | no | PR #15 review-thread participation; gemini-code-assist bot activity |
| `opencode` | full | full | TBD (the only agent with `git worktree add` peer-to-Desktop privilege per session narrative) | TBD | yes | feature branches only | 0.2.0 handoff §"Critical Context" (opencode CLI reference); this conductor session |
| `jules` | full | ticket-level work | no | none | no (per default) | no (per default) | inferred from the "100 daily tasks" drain pattern; not yet observed in this repo's history |
| `gpt-scheduled` | full | read-only token, comment-only | no | none | yes (comments) | no | inferred from the scheduled-task pattern; not yet observed in this repo's history |
| `conductor` (human) | full | full | yes (with explicit session auth) | full | yes | yes, including `main` (via squash-merge button) | the 0.2.0 squash-merge at `f5ff0da`; standing rules |

**Cells marked `TBD` are pending `secrets-map.md` resolution. The
conductor must fill the secrets-map matrix before any agent is
authorized to touch a secret in a way the standing rules do not
already permit.**

## What the per-agent override slots cannot do

- They cannot grant an agent authority the human has not
  explicitly authorized. The matrix above is descriptive (what
  has been *observed*), not prescriptive (what an agent *may*
  take). The prescriptive version is the conductor's call, made
  per-session.
- They cannot override the shared invariants. Even if the
  conductor authorizes an agent to take a destructive action in
  a specific session, the shared invariants (atomic-commit,
  N/A-is-a-vacuum, no-claim-of-loss-without-reflog-check) still
  apply. Authorization is for *what* the agent does, not for
  *how* the agent does it.
- They cannot survive a session boundary. An authorization
  granted in session N is not portable to session N+1 unless
  re-confirmed. This is the cold-start protocol's reason for
  existing: every new session re-reads this file and
  re-confirms the override slots against the conductor.

## Cross-references

- [`MERGE_PATH.md`](../MERGE_PATH.md) — canonical merge policy
- [`docs/handoff/media-ark-0.2.0-2026-06-10.md`](../docs/handoff/media-ark-0.2.0-2026-06-10.md) — the 0.2.0 closeout handoff (the agent session this conductor surface extends)
- [`docs/regression-findings.md`](../docs/regression-findings.md) — the S1/S2/S3 + F1–F9 pattern this file imitates (lean facts, dense context, named blind spots)
- [`docs/SHIP_EVIDENCE.md`](../docs/SHIP_EVIDENCE.md) — the verified-evidence surface for releases
- [`routing.tables.toml`](./routing.tables.toml) (parseable data) and [`routing.md`](./routing.md) (narrative) — the intent-verb-to-agent-kind map
- [`dispatch/<agent>.md`](./dispatch/) — the per-agent-kind projections
