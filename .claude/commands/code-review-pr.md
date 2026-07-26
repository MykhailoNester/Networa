---
description: "Reviews a pull request opened by someone else. Fetches the PR branch with plain git, reviews the diff against Networa's conventions, and outputs a review ready to paste into GitHub. Usage: /code-review-pr <PR number | branch | URL>"
allowed-tools: Bash(git fetch:*), Bash(git log:*), Bash(git diff:*), Bash(git show:*), Bash(git branch:*), Bash(git merge-base:*), Bash(git ls-remote:*), Bash(git rev-parse:*), Read, Grep, Glob
---

# Code Review PR

Reviews a pull request against Networa's architecture, conventions, and quality
gate, and produces a review as **text to paste into GitHub yourself**.

This command uses plain `git` against the repository's configured `origin`. It
never posts, approves, merges, pushes, or otherwise writes to the remote — the
output is yours to review before anything reaches the PR.

## Input

`$ARGUMENTS` — one of:

- a **PR number** (`42`)
- a **PR URL** (`https://github.com/<owner>/<repo>/pull/42`) — take the number
  off the end
- a **branch name** (`feature/csv-multi-currency`) — for a branch pushed to
  `origin` without a PR yet
- **nothing** — ask which PR or branch to review, and stop until told

## Step 1 — Fetch the changes

For a PR number `N` (this works for fork PRs too — GitHub exposes every PR head
under `refs/pull/*` on the base repository):

```bash
git fetch origin "pull/N/head:pr-N"
git log --oneline develop..pr-N
git diff --stat develop...pr-N
git diff develop...pr-N
```

For a branch:

```bash
git fetch origin <branch>
git log --oneline develop..FETCH_HEAD
git diff --stat develop...FETCH_HEAD
git diff develop...FETCH_HEAD
```

The base is **`develop`** — that is what PRs target here. Use `origin/develop`
if the local one is behind, and fall back to `main` only if `develop` does not
exist.

If the fetch fails — no network, no such PR, or a remote that does not expose
`refs/pull` — say exactly what failed and offer the fallback: ask the author for
the branch name, or have the diff pasted directly into the conversation, and
review that instead. Do not guess at the contents.

The local `pr-N` branch is a leftover; mention it at the end so it can be
deleted with `git branch -D pr-N`. Never check it out over uncommitted work, and
never push it anywhere.

## Step 2 — Check the PR description

Compare against `.github/pull_request_template.md`. The PR should have:

- **What** — the change, in a sentence or two
- **Why** — the problem it solves
- **How to verify** — steps or numbers a reviewer can check
- **Checklist** — the five boxes, honestly ticked

Flag missing, empty, or template-boilerplate sections. If the PR text is not
available — nothing here reads it from the remote, and it is not in the
conversation — say
"PR description not available — not checked" rather than assuming it is fine.

Also confirm the PR targets `develop`, not `main`.

## Step 3 — Read the changed files

For each file in the diff, read the **whole file**, not just the hunks, plus the
callers of anything changed in `app/services/`. In this codebase the debt sign
convention and the USD base currency both live outside the lines being edited,
so a hunk-only reading is how a reviewer gets it wrong.

## Step 4 — Apply the review checklist

The full Networa review checklist lives in
**`.claude/agents/code-reviewer.md`** — read it and apply it rather than working
from memory, so the two never drift apart. In short, it covers:

- **Money & domain rules** — the assets/debts shared table and positive-value
  debts, `_SIGNED` in net-worth aggregates, a debt's contribution being the
  negation of its value change, composition aggregates staying gross-asset only,
  USD as the storage and aggregation currency, and guarded denominators
- **HTML escaping** — `app.html.e()` and `json_for_script()` in router-built
  f-string fragments, `|safe` in templates
- **Layering** — routers → services → database, `app/forms.py` for form parsing
- **Database** — parameterized SQL, and the fact that `app/schema.sql` is
  applied idempotently at startup and therefore **cannot add a column to an
  existing table**
- **Async** — no blocking calls on the event loop, every `aiosqlite` call awaited
- **Security** — `app/security.py`'s same-origin and Host rules, no mutating GET
  endpoints, no secrets or real data, no CDN links
- **The gate** — ruff (`E, W, F, I, UP, B, BLE, DTZ, RUF`), `mypy app/`, pytest
- **Duplication, dead code, scope creep, naming, readability**
- **Tests** — coverage of new behaviour, and never touching a real database
- **The cost & convention gate** — drop any performance finding that cannot name
  a real cost at this app's actual scale

For an **outside contribution**, add these:

- **Dependencies** — any addition to `requirements.txt` /
  `requirements-dev.txt` must be pinned, justified, and actually needed. Check
  it is not already covered by `httpx` or the stdlib, and note the maintenance
  cost. Treat an unexplained new dependency as a 🟡 at minimum.
- **CI and tooling** — changes to `.github/workflows/`, `Makefile`, or
  `pyproject.toml` in a PR that is otherwise a feature deserve explicit
  scrutiny; a fork PR editing CI is a 🔴 until explained.
- **Committed data** — anything under `data/` other than a legitimately
  re-seeded `data/demo.db`, any `.env`, any credential, any real financial
  figure. A `demo.db` change should come with the `scripts/seed_demo.py` change
  that produced it.
- **Licensing** — new vendored files under `app/static/vendor/` need their
  licence recorded in `THIRD-PARTY-NOTICES.md`.
- **Intent match** — does the diff do what the PR says it does, and only that?

## Step 5 — Verify findings (adversarial pass)

Before writing anything, try to **refute** every candidate 🔴 and 🟡. Default to
"not a bug unless proven".

1. **Trace the call sites.** Grep for callers and read the paths that actually
   reach the flagged line. A bug reachable only through a path the caller
   already guards is not a live bug.
2. **Read the whole query.** For a claim about an aggregate, `COALESCE`, a
   `CASE`, or a `WHERE category = 'asset'` filter often makes the obvious bug
   wrong.
3. **Code beats docs.** For a code-vs-docs mismatch, confirm the real behaviour
   in source. A stale comment is a 🟡 doc fix, not a blocker.
4. **Resolve.** Reachable → keep, with the reachability line filled in. Guarded
   today → downgrade to a 🟢 latent note. Disproven → drop it and do not mention
   it.

This matters more on someone else's PR than on your own: a wrong blocker costs
the author a round trip and costs you credibility.

## Output

Two parts.

### Part 1 — the review, ready to paste

Print the review body inside a single fenced ```markdown block so it copies
cleanly into GitHub's review box:

```markdown
## Summary

<one paragraph: what the PR does, and the verdict — **Approve** /
**Request changes** / **Needs discussion**>

## Findings

**F1. 🔴 BLOCKER `app/services/snapshot_service.py:87` — Net-worth sum ignores debt sign**
What is wrong and why it matters.
**Reachability:** entry point → call site → the input or state that reaches it,
and why nothing guards it.
**Fix:** the concrete change.

**F2. 🟡 SUGGESTION `app/routers/debts.py:44` — …**
…

## What looks good

<two or three specific things — not filler>

## Questions

<where the intent is unclear and only the author can answer>
```

Rules:

- Number findings `F1, F2, F3…` continuously, ordered most-severe first, so they
  can be referenced in follow-up discussion. Keep IDs stable across re-posts.
- Severities: 🔴 **BLOCKER** (wrong money math, XSS, SQL injection, a schema
  change that breaks existing databases, data loss, a crash on a reachable
  path) · 🟡 **SUGGESTION** (layering, duplication, missing tests, gate
  failures) · 🟢 **NIT** (style, wording, guarded latent issues).
- Every 🔴 and 🟡 needs a reachability line. If you cannot name a trigger,
  downgrade it or drop it.
- Write it for the author, not for yourself: direct, specific, no hedging, no
  moralising. Say what is wrong and what to do about it.
- A clean PR gets a short review. Do not pad empty sections to fill the shape.

### Part 2 — notes for you (outside the fenced block)

- **Verdict** and the count by severity.
- **Inline comments**, if any are worth placing on specific lines — as a short
  `file:line — F<N>` list, so they can be pasted onto the right lines by hand.
- **Not checked** — anything skipped and why (PR description unavailable, the
  gate not run locally, a generated file not reviewed line by line).
- **Cleanup** — the `git branch -D pr-N` reminder if a local branch was created.

To validate the PR actually builds and passes rather than only reading it, check
it out on a scratch worktree and hand it to `compiler-agent` in `full` mode —
say so as a suggestion; do not do it unasked, since it means changing the
working tree.
