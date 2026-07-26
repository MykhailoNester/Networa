---
description: Runs the autonomous delivery pipeline over one or more tasks — worktree off develop, plan, plan review, implement, code review, quality gate, commit, worktree removed. Leaves one reviewed local branch per task. No push, no PR.
argument-hint: <tasks, in prose or by feature-gap-plan name> [as a workflow]
---

Deliver these tasks autonomously, each as its own committed local branch:

**$ARGUMENTS**

## How to run this

The protocol is `.claude/agents/dev-orchestrator.md`. **Read it now** and follow
it exactly — stage order, round limits and failure policy included. Run it here
in the main loop so progress is visible between stages, launching
`planner-agent`, `plan-reviewer`, `coder-agent`, `code-reviewer` and
`compiler-agent` as subagents at their stages.

## Mode

Default is **`default`** mode: drive the stages with direct subagent calls,
fanning each wave out concurrently.

Switch to **`workflow`** mode only if the request says so — "as a workflow", "run
this as a workflow", `mode=workflow`. Then do Stage 0 (intake and wave planning)
here, hand the resolved tasks to `.claude/workflows/ship-tasks.js` through the
Workflow tool, and do Stage 9 (plan-doc write-back) here from its return value.

## Reading the request

Tasks may arrive as prose, as feature names from a roadmap document, or as a
selection like "the remaining Phase 0 items".

Paths are never hardcoded — this command is committed to a public repository.
Resolve them with the constants block at the top of the protocol: the repo root
comes from git, and the roadmap document comes from `NETWORA_PLAN_DOC` in the
gitignored `.claude/pipeline.env` (see `.claude/pipeline.env.example` for every
available value).

When a roadmap document is configured, its `STATUS` map is the authority on what
is still to do — skip anything already `done` and say you skipped it. When it is
not configured, take the tasks straight from the prompt and skip the write-back
stage; that is a supported setup, not an error.

You decide which tasks run in parallel and which must be sequenced, per the
hard-dependency rule in the protocol. A task chained behind another is based on
that task's **branch**, not on `develop`.

## Before you start

Print the plan you intend to run — tasks, branch names, bases, and which are
parallel — then proceed **without waiting for approval**. This command is
autonomous by design; the human's checkpoint is reviewing the finished branches.

Stop only for the hard stops in the protocol's preflight: a target branch that
already exists, or a missing `$REPO/.venv`.

## When you are done

Report with the protocol's final-report table: task, branch, base, status,
commit, rounds. Say plainly what failed and what was skipped, name any chained
branches and the order to review them in, and give the `git checkout` lines.

Never push. Never open a pull request. Never merge or rebase onto `develop`.
