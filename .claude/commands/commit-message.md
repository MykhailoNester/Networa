---
description: Writes a Conventional Commit message for the current changes, with the type inferred from the branch prefix. Outputs the message only — it does not commit.
allowed-tools: Bash(git branch:*), Bash(git status:*), Bash(git diff:*), Bash(git log:*), Read, Grep, Glob
---

Generate a git commit message for the current changes in Networa.

## Steps

1. `git branch --show-current` — the branch prefix determines the commit type:

   | Branch prefix | Commit type |
   |---|---|
   | `feature/` | `feat` |
   | `fix/` | `fix` |
   | `chore/` | `chore` |

   If the branch has no recognised prefix (or is `develop`/`main`), infer the
   type from the diff instead: new user-visible capability → `feat`, bug fix →
   `fix`, tooling/CI/deps/docs-only → `chore`. Never invent a ticket ID — this
   project tracks work by branch name, not by ticket.

2. `git diff --cached` for staged changes. If it is empty, `git diff HEAD` for
   unstaged ones. If both are empty, say so and stop.

3. Pick a scope from the area the diff actually touches. Use one, lowercase, and
   only when it genuinely narrows the change:

   `dashboard`, `assets`, `debts`, `cashflows`, `snapshots`, `sheets`, `import`,
   `exchange-rates`, `settings`, `schema`, `currency`, `security`, `templates`,
   `tests`, `ci`, `docs`, `deps`

   Omit the scope when the change spans several areas — `fix: …` is better than
   a scope that is only half true.

4. Write the summary line: lowercase, imperative, no trailing period, and
   specific about what changed. "show a flat period as +0.00%, not as an em
   dash" beats "fix percentage bug".

5. If the change spans several distinct pieces, add a blank line and one bullet
   per piece, each starting with `- ` and lowercase.

## Output rules — this is critical

- Output **only** the commit message. No explanation, no preamble, no markdown
  code fence around it.
- **Do not run `git commit`.** This command produces text; committing is the
  user's call.
- **Never add a `Co-Authored-By` trailer** — this project does not use them.

## Format

Simple change:

```
<type>(<scope>): <summary>
```

Change with several parts:

```
<type>(<scope>): <summary>

- <detail one>
- <detail two>
```

## Examples

```
fix(dashboard): show a flat period as +0.00%, not as an em dash
```

```
feat(debts): tailor the detail view to liabilities

- swap the value chart for a remaining-balance chart
- label the contributor row as principal paid, not gain
- hide the cost-basis and unrealised-gain fields
```

```
chore(ci): run the quality gate on pushes to develop
```
