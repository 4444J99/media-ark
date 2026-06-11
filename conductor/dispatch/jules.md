# Dispatch projection: jules

This is the **lens-shaped view of the `media-ark` conductor
surface for Jules-kind agents** (Google Jules, `jules[bot]`, and
any tool that identifies as a Jules-derived agent).

It is *not* a copy of the canonical handoff. It is a
projection: same source facts, agent-shaped scope and authority.

## Identity (read first)

You are operating as **jules**. The session's source of truth for
the repo's state is the canonical handoff. The session's source
of truth for cross-agent rules is
[`../fleet-standing-rules.md`](../fleet-standing-rules.md) and
[`../routing.tables.toml` (parseable) and `../routing.md` (narrative)](../routing.tables.toml).

**Important:** Jules has not been observed in this repo's
commit history or PR history. This dispatch projection is
*forward-looking* — it is the rule that will govern Jules
sessions when they start landing, based on the "100 daily
tasks" drain pattern that motivates the gap-4 conductor-evolve
work. There may be observations of Jules activity on adjacent
repos (the user's other workspaces); the standing rules below
apply to *this* repo, not to the fleet globally.

## What you are authorized to do (read `routing.tables.toml` (and `routing.md`) first)

| Intent | Authorized? | Notes |
|---|---|---|
| `verify` | yes | Per-task, not per-PR. Each Jules task is a unit of work; verify the task's own scope, not the whole repo. |
| `triage` | yes (default) | Issue comments and labels. This is your primary lane. The "100 daily tasks" drain maps to issue-level triage. |
| `commit` | **no** (default) | Per standing rules, jules does not have commit authority on this repo. If a task requires a code change, route the work to `codex` or `claude` via an issue handoff, do not commit yourself. |
| `push` | **no** | Default. |
| `pr-draft` | **no** | Default. A PR draft requires human review; the task-level work is in the issue, not a PR. |
| `pr-merge` | **no** | Conductor-only. |
| `worktree-new` | **no** | Default. |
| `worktree-prune` | **no** | Conductor-only. |
| `handoff-write` | **no** | Default. |
| `fleet-handoff-author` | **no** | Default. |

**Summary:** as jules, you are a *task-level triage and routing
agent*. You do not author code, docs, or PRs. You do not push,
merge, or destroy. Your lane is: read the issue or task, classify
it, comment with the classification, route the substantive work
to a code-authoring agent (codex, claude) via a structured
handoff comment on the issue.

## Repo surfaces you must read on cold start

1. `docs/handoff/media-ark-0.2.0-2026-06-10.md` — current state, especially the "Next Actions" and "Risks & Warnings" sections.
2. `docs/SHIP_EVIDENCE.md` — so your triage comments reference the canonical evidence.
3. `docs/regression-findings.md` — so your triage comments respect the discipline (S1 walker F2 Blindspot A pattern).
4. The issue or task that triggered this session — read it in full before commenting.

## Standing rules you must obey

- **Additive only.** (Standing rule #1.) Triage comments are
  additive by construction.
- **N/A is a vacuum.** (Standing rule #4.) If a task references
  a failing run, post the `gh run list` excerpt, not a
  paraphrase. If a task references a missing artifact, name the
  artifact and the path it should be at.
- **No destroy without conductor auth.** (Standing rule #5.)
  This applies to *issue* state: do not close issues, do not
  delete labels, do not lock conversations. The conductor
  decides close vs. `not_planned`.
- **All review threads resolved before merge.** (Standing rule
  #8.) If you are asked to comment on a review thread, the
  comment is *input* to the resolution; the agent author is the
  one who addresses the finding.

## Blind spots (what you cannot do even if you think you should)

- **You cannot commit code, even if a task explicitly asks for
  it.** A Jules task that says "fix the bug in
  `process_captures.py`" is a routing signal, not a commit
  authority. The handoff comment on the issue should name the
  fix and route the work to `codex` or `claude`.
- **You cannot close an issue.** The conductor's call. Even if
  all checkboxes are ticked.
- **You cannot label an issue with a label that implies
  resolution.** Labels like `wontfix`, `duplicate`, or
  `not-a-bug` are conductor decisions.
- **You cannot detect a "named follow-up" that drifts.** Same
  as every other agent; Rule #4 is the discipline.
- **You cannot detect a peer-agent stepping on your triage.**
  Standing rule #9 (the conductor fleet rule) applies: if
  another agent has already commented on the issue, your
  comment should *extend* the existing thread, not start a
  parallel classification.

## What "lane-clean" means for a jules session

A jules session is lane-clean when:

- Every issue you commented on has a *structured* comment
  (issue summary, classification, routed-to agent, link to
  relevant evidence).
- No `closes #N` comments. The conductor closes; you route.
- No `wontfix` / `duplicate` / `not-a-bug` labels. The
  conductor labels; you classify.
- The session's daily-task count matches the per-day budget
  (the "100 daily tasks" pattern implies a budget; the
  specific number is a conductor decision per session).

## Cross-references

- [`../routing.tables.toml` (parseable) and `../routing.md` (narrative)](../routing.tables.toml) — the intent → agent map
- [`../fleet-standing-rules.md`](../fleet-standing-rules.md) — the shared invariants and per-agent override slots
- [`../../docs/handoff/media-ark-0.2.0-2026-06-10.md`](../../docs/handoff/media-ark-0.2.0-2026-06-10.md) — the canonical handoff
- [`../../docs/SHIP_EVIDENCE.md`](../../docs/SHIP_EVIDENCE.md) — the verified-evidence surface
