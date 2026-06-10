# Regression findings — context for test_review_findings_regression.py

This file holds the narrative context for the regression tests in
`tests/test_review_findings_regression.py`. The tests themselves are
deliberately lean (assertion + setup, no prose). Long explanations
of why a test exists, what it pins, and how it might silently
break live here, not in the test bodies.

This file was created in the 2026-06-09 premortem-address pass (PR #10)
to address the F8 finding: the previous evolve pass had embedded ~141
lines of S1/S2/S3 prose in the test file, raising the per-test density
~3-4x above the file's prior average. The narrative was extracted here
so the test bodies could be skimmed for patterns, not read for prose.

---

## S1 — No unguarded persistent manifest['stats'] augmented assignment

- **Tests:**
  - `test_s1_no_unguarded_persistent_stats_aug_assign` (the invariant
    test: parse `process_captures.py`, walk the AST, assert zero
    forbidden patterns on the persistent-manifest surface).
  - `test_s1b_walker_catches_forbidden_pattern` (F2 positive control:
    assert the walker demonstrably catches a forbidden pattern when
    one is present, and does not false-positive on a per-call
    `run_stats` surface).

- **Walker helper:** `_walk_forbidden_stats_aug_assign(tree)` at
  module level in the test file. Both S1 tests call it.

- **What it pins:** No `AugAssign` on a `Subscript` whose `value` is a
  `Name` with id `stats` may exist in `src/capture_automation/process_captures.py`
  on the persistent manifest surface. The per-call `run_stats` dict
  is permitted to use `+=` because it is freshly constructed in
  `run_once`.

- **Why it matters:** The F4 latent-crash bug was an unguarded
  `stats['files_seen_total'] += len(all_files)` on a freshly
  `setdefault`-initialized `{}` dict, which KeyErrored on a
  fresh manifest.

- **Limits of the walker (F2 Blindspot A):** The walker does NOT catch
  the following equivalent spellings:
  - `local = manifest.setdefault('stats', {}); local[k] += n`
    (LHS is a Name rebind, not a Subscript on a Name called `stats`).
  - `stats = stats.get(k, 0) + n` then a separate `manifest['stats']
    = stats` (LHS is an `Assign` on a Name, not an `AugAssign`).
  - `manifest.setdefault('stats', {}).update({k: ...})` (no
    augmented assignment at all).
  - `setdefault(...).__setitem__(k, ...)` (no syntactic assignment).

  These are all *equivalent* to the F4 bug class. The walker
  catches the original spelling only. The premortem's F2 deep-dive
  surfaced this; the test_s1b third assertion (the `unrelated_src`
  case) demonstrates the gap exists by design and points at the
  manual-review path. A future contribution that introduces one of
  these equivalent spellings is a *manual review* concern, not an
  *automated gate* concern.

- **What to do if the walker fires:** Replace `stats[k] += n` with
  `stats[k] = stats.get(k, 0) + n`. The latter is safe because
  `get` returns `0` for missing keys. The walker has zero
  false-positives on the per-call `run_stats` surface (verified
  by `test_s1b`).

---

## S2 — Converse of the source-missing narrowing

- **Test:** `test_4b_run_once_source_missing_lands_in_skipped`
- **Converse of:** `test_4_run_once_inner_catch_narrows_to_source_missing`

- **What it pins:** A `FileNotFoundError` whose message contains
  `"source_missing"` lands in `run_stats['skipped']` (not
  `run_stats['failed']`) and is recorded in `manifest.errors` with
  `error: 'source_missing'`.

- **Why it matters:** Without the converse, the negative-only
  `test_4` would let a future agent delete the
  `'if "source_missing" not in str(exc)'` check entirely, and every
  FNE would land in `'failed'`. Both tests would pass green in
  that broken state (test_4 asserts the *non*-source-missing case
  goes to failed; the converse asserts the source-missing case
  goes to skipped; both can pass only if the narrowing still works).

- **F1 binding assertion:** Both `test_4` and `test_4b` include
  a `self.assertIs(pc.process_file, pc.run_once.__globals__
  .get('process_file'))` check before the monkeypatch is exercised.
  This is a future-trap guard: the assertion fails *before* `run_once`
  is called if the binding has drifted (e.g., a future refactor
  shadows the module's `process_file` with a closure-captured binding).
  See the S3 section below for the binding-drift failure mode in detail.

---

## S3 — Monkeypatch fragility (binding-drift failure mode)

- **Tests:** `test_4`, `test_4b`
- **What it documents:** Both tests monkeypatch `pc.process_file`.
  The monkeypatch works because `process_file` is defined at
  `src/capture_automation/process_captures.py:935` and `run_once`
  is defined at the same file at line 2717. `run_once` calls
  `process_file` by bare name at line 2850, which resolves through
  the module's `__dict__` (i.e., `pc.__dict__['process_file']`).
  Setting `pc.process_file = X` rebinds `pc.__dict__['process_file']`
  to `X`, and the next call to bare `process_file(...)` inside
  `run_once` resolves `X` because the resolution is by-name
  through `run_once.__globals__` (which IS `pc.__dict__` for
  module-level functions).

- **Failure mode (future trap):** A future refactor that does any
  of the following breaks the monkeypatch:
  1. Adds `from .helper import process_file` at the top of
     `process_captures.py` and changes `run_once` to call
     `process_file` via that import. In this case, `helper.process_file`
     is a different binding; the test's monkeypatch on
     `pc.process_file` is shadowed by the helper's re-export.
     (Caveat: if the module's `process_file` global is the re-export,
     the monkeypatch still works because `pc.__dict__['process_file']`
     IS the re-export.)
  2. Changes line 2850 from `process_file(...)` to
     `pc.process_file(...)` where `pc` was captured by an inner
     `import process_captures as pc` inside `run_once`. In this
     case, the inner `pc` is still a binding to the same module,
     so the monkeypatch still works *unless* the inner `pc` was
     bound to a snapshot of the module's `__dict__` (extremely
     unusual).
  3. Wraps `process_file` in a closure inside `run_once` (e.g.,
     `_process_file = process_file; _process_file(...)`). In this
     case, the closure captures the original `process_file` at
     definition time, and the test's monkeypatch is not seen.

- **Mitigation:** The F1 binding assertion in `test_4` and `test_4b`
  fails *before* `run_once` is called if `pc.process_file` is not
  the same object as `pc.run_once.__globals__.get('process_file')`.
  This is a smoke test, not a comprehensive check: the most likely
  failure mode (case 1 above, where the import is from a sibling
  module) is still a "passes the binding assertion but fails to
  exercise the patched path" scenario. The comprehensive check
  would be to verify the test's `pc.process_file` and the binding
  `run_once` actually resolves are the same; the current assertion
  does verify this for the bare-name-in-same-module case.

- **What to do if the F1 binding assertion fires:** The assertion
  message points at the two likely fixes: (1) fix the import
  pattern in `process_captures.py`, or (2) change the test to
  patch `run_once.__globals__['process_file']` directly instead
  of `pc.process_file`. The latter is the more robust fix because
  it patches the actual binding the call site resolves, not the
  module attribute.

---

## F1, F2, F3, F4, F5, F6, F7, F8, F9 — premortem closure map (2026-06-09)

The 2026-06-09 premortem of PR #9 surfaced 9 findings (F1–F9). The
2026-06-09 follow-up pass (PR #10) addressed each:

| Finding | Closure in PR #10 |
|---------|--------------------|
| F1 (binding-drift trap) | Added `self.assertIs(pc.process_file, pc.run_once.__globals__.get('process_file'))` in `test_4` and `test_4b`. Forward-looking guard, not corrective (the current code is safe). |
| F2 (AST walker self-check) | Refactored walker into `_walk_forbidden_stats_aug_assign` module-level helper. Added `test_s1b_walker_catches_forbidden_pattern` with three assertions: (a) walker catches a forbidden pattern, (b) walker does not false-positive on `run_stats`, (c) walker documents the F2 Blindspot A gap and points at manual review. |
| F3 (slimmer lost in-repo context) | Strengthened `.github/workflows/automation-ci.yml` lines 3-9. Replaced the loose pointer to `MERGE_PATH.md and docs/SHIP_EVIDENCE.md` with explicit anchors: `§"Post-merge runner-pickup hardening"` at known line numbers. Added the keyword `runner-pickup` for code-search bots that index `.yml` only. |
| F4 (self-triangulation) | Appended a "PR #9 closure re-derivation" section to `~/.Codex/plans/closeout-2026-06-09-final.md`. The section is an audit trail; it is itself single-pass (same caveat applies to the re-derivation as to the original closure). |
| F5 (closeout amendment invisible diff) | Created `~/.Codex/plans/closeout-2026-06-09-final-v1.md` with the reconstructed pre-amendment text. Sections 1-N are reconstructed to the best of session memory; the live file is the source of truth if any divergence is found. |
| F6 (OQ1 hedge downgrades F4 priority) | Amended line 37 of the live closeout. Replaced "preventive, not curative" with "preventive in deployment history; structural via test_s1." Makes the test-coverage artifact the priority signal, not the production-validation status. |
| F7 (issue #5 comment off-axis) | Posted an on-axis follow-up comment on issue #5 stating the runner-pickup pattern is unchanged and giving the close-criterion status (6 in-flight, 3 failure, 1 cancelled re-derived). |
| F8 (test file narrative density) | This file. Extracted the S1/S2/S3 prose to `docs/regression-findings.md`. Test file net change: -80 lines, density ~15.6 → ~12.6 lines/test. |
| F9 (release:verify local-only) | Created `tox.ini` with a `py311` and `py314` matrix. No wheel-install env (no `pyproject.toml` exists in the repo). The matrix exercises both Python versions against the source tree using `PYTHONPATH=src`. (Drift note: the PR #10 description said "py310, py312" but the actual `tox.ini` (line 32) was `envlist = py311, py314` from the start. The live closeout line 209 has always been correct; only the companion doc was wrong. Fixed in PR #12.) |

---

## Source-tree notes (F9 addendum)

The repo has no `pyproject.toml`, `setup.py`, `setup.cfg`, or
equivalent Python packaging config. Tests are run via
`python3 -m unittest discover` (see `package.json` `test` script),
which uses the source tree directly via `PYTHONPATH=src` semantics
(implicit, via the test's `from src.capture_automation import ...`
imports). This means:

- A wheel-install path is not applicable. Consumers do not
  `pip install` this repo; they clone it.
- A `tox` matrix that tests against the source tree covers the
  real consumer path.
- A `tox` matrix that tests against a wheel would be testing a
  non-existent path; the F9 premortem's `py312-wheel` env
  recommendation is therefore inapplicable here. The matrix
  envs in `tox.ini` are `py311` and `py314` only
  (`envlist = py311, py314` at `tox.ini:32`).

The hardcoded `src/capture_automation/process_captures.py` path in
the `PROCESSOR` constant in the test file is the canary the F9
deep-dive agent pointed at (the agent named the test body, but the
actual canary is the module-level `PROCESSOR` constant). The path
is correct as long as the package is run from the source tree; if
a future packaging change moves the source into a non-`src/`
layout, `PROCESSOR` will need to be updated.
