---
description: Prepares pull request text locally — title and body filled into the repo's PR template, ready to copy into GitHub. It does not create the PR.
allowed-tools: Bash(git branch:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git merge-base:*), Read, Grep, Glob
---

# Pull Request Text Generator

Produces the title and body for a pull request on the current branch, filled
into `.github/pull_request_template.md`, so it can be pasted straight into
GitHub's "New pull request" form.

**This command is local preparation only.** It does not push, does not open a
PR, and does not talk to GitHub. No ticket references — Networa tracks work by
branch name.

## Input

None. Everything comes from the current branch and its diff. If the caller
passes `$ARGUMENTS`, treat it as extra context about intent (the "Why") rather
than as a ticket ID.

## Steps

### 1. Establish the branch and base

```bash
git branch --show-current
git status --short
git log --oneline develop..HEAD
git diff --stat develop...HEAD
git diff develop...HEAD
```

The base is **`develop`** — every `feature/`, `fix/`, and `chore/` branch
targets it, never `main`. If `develop` is not present locally, use
`origin/develop`. If the current branch *is* `develop` or `main`, say that a PR
from it is not the intended flow and stop.

If there are uncommitted changes, note them — they will not be in the PR — and
carry on with what is committed.

### 2. Understand the change

Read the commits and the diff. Where the diff alone does not explain the intent,
read the changed files. The "Why" section has to say something the diff cannot.

### 3. Write the title

Same shape as the project's commit messages: `<type>(<scope>): <summary>`, with
the type from the branch prefix (`feature/` → `feat`, `fix/` → `fix`, `chore/` →
`chore`) and an optional lowercase scope (`dashboard`, `debts`, `import`,
`schema`, `ci`, `docs`, …). Lowercase, imperative, no trailing period.

Example: `feat(debts): tailor the detail view to liabilities`

### 4. Fill the template

The body follows `.github/pull_request_template.md` exactly — the same headings
in the same order. Read that file rather than trusting this list, in case it has
changed:

```markdown
## What

<one or two sentences: the change itself>

## Why

<the problem it solves — the part the diff cannot show>

## How to verify

<steps a reviewer can follow, or the numbers they should see>

## Checklist

- [ ] `make check-all` passes (ruff format, ruff check, mypy, pytest)
- [ ] Branch is named `feature/…`, `fix/…`, or `chore/…` and targets `develop`
- [ ] No real personal or financial data, secrets, or database committed
- [ ] Schema changes (if any) went into `app/schema.sql` and the demo DB was re-seeded
- [ ] Docs updated if behaviour, structure, or setup changed
```

Tick a checklist box only when it is **verifiably true**:

- `make check-all` — tick only if it has actually been run and passed in this
  session (or via `compiler-agent`). Otherwise leave it unticked and say so.
- Branch naming and base — checkable from `git branch --show-current`.
- No real data or secrets — check the diff for anything under `data/` other than
  `demo.db`, for `.env` files, and for credentials.
- Schema — if the diff touches `app/schema.sql`, confirm `data/demo.db` was
  re-seeded in the same branch; if it adds a column to an existing table, call
  that out in **How to verify**, because the startup schema init cannot apply it
  to an existing database.
- Docs — if behaviour, structure, or setup changed, check `README.md`,
  `CONTRIBUTING.md`, `CLAUDE.md`, and `docs/` were updated.

Drop a heading only if the template drops it. If a section genuinely has nothing
to say, write one honest line rather than deleting it.

## Writing guidelines

❌ Avoid marketing filler — "improves the user experience", "ensures expected
behaviour", "enhances the flow".

✅ Be factual and technical. Problem → change → observable result. Name the
files, the functions, and the numbers a reviewer can check.

For anything touching the money math, spell out the invariant in **How to
verify** — e.g. "on the demo DB the dashboard shows net worth $412,300, and the
contributor rows still sum to the period change".

## Output

Print, in this order and nothing else:

1. The title on its own line, prefixed with `Title:`.
2. The body inside a single fenced ```markdown block, so it copies cleanly into
   GitHub.
3. One short line after the block noting anything the author must fix before
   opening the PR — unticked checklist items, uncommitted work, an unpushed
   branch. Skip the line entirely if there is nothing to flag.

Do not add commentary, a summary of your own work, or next-step suggestions
beyond that one line.
