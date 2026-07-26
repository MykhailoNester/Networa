export const meta = {
  name: 'ship-tasks',
  description: 'Deliver N Networa tasks as reviewed, gated, committed local branches — one isolated worktree each, removed on success',
  whenToUse: 'Workflow mode for /ship. Use for larger batches where deterministic fan-out and resumability beat per-stage narration. Tasks must already be resolved into waves by Stage 0 of .claude/agents/dev-orchestrator.md.',
  phases: [
    { title: 'Setup', detail: 'worktree off base + venv symlink, one per task' },
    { title: 'Plan', detail: 'planner-agent, then plan-reviewer until APPROVED (max 2 revisions)' },
    { title: 'Implement', detail: 'coder-agent executes the approved plan' },
    { title: 'Review', detail: 'code-reviewer, then coder-agent fixes blockers (max 2 rounds)' },
    { title: 'Gate', detail: 'compiler-agent full (+ smoke), fixes until green (max 2 rounds)' },
    { title: 'Finalize', detail: 'drop venv symlink, commit, remove worktree, branch survives' },
  ],
}

/* Stage 0 (intake, wave planning, plan-doc resolution) and Stage 9 (plan-doc
   write-back) are NOT here — they belong to the caller. This script starts at an
   already-resolved task list and ends at committed branches. */

/* The Workflow tool sometimes flattens `args` to a JSON string before the
   script sees it, in which case `args.repo` is undefined on a string primitive
   and the guard below rejects a run whose arguments were in fact perfectly
   correct. Parsing that back is not guessing — it is the same payload in a
   different wrapper — so accept it rather than making the caller wrap this
   script just to hand it an object. A bound local, not a reassignment: `args`
   is runtime-provided and may not be writable. */
const input = typeof args === 'string' ? tryParse(args) : args

function tryParse(raw) {
  try {
    return JSON.parse(raw)
  } catch {
    return null // fall through to the guard, which reports it properly
  }
}

/* A workflow script has no filesystem access: it cannot read
   .claude/pipeline.env and cannot derive the repo root from git. The caller
   resolves both in the constants block of .claude/agents/dev-orchestrator.md and
   passes them in. Fail loudly rather than guess — a default here would bake
   somebody's home directory into a public repository. */
if (!input || !input.repo || !input.wtRoot) {
  throw new Error(
    'ship-tasks: args.repo and args.wtRoot are required absolute paths, resolved by the caller. ' +
      `Received ${typeof args}${typeof args === 'string' ? ' (unparseable as JSON)' : ''}. ` +
      'See the Modes section of .claude/agents/dev-orchestrator.md.',
  )
}

const REPO = input.repo
const WT_ROOT = input.wtRoot
const TASKS = input.tasks || []

if (TASKS.length === 0) throw new Error('ship-tasks: args.tasks is empty — nothing to deliver.')

const LIMITS = input.limits || {}
const MAX_PLAN_REVISIONS = LIMITS.planRevisions ?? 2
const MAX_REVIEW_FIXES = LIMITS.reviewFixes ?? 2
const MAX_GATE_FIXES = LIMITS.gateFixes ?? 2

const RULES = `
Networa — the rules that matter, all binding:
- Layering: routers -> services -> database. Money math lives in app/services/, never in a router.
- Assets and debts share one table. assets.category is 'asset' or 'debt'; a debt's value is stored
  POSITIVE. Net worth is assets - debts, and net-worth aggregates sign debt rows -1 (the _SIGNED
  constant in snapshot_service). A debt's period contribution is the NEGATION of its value change.
  Composition aggregates (allocation by class/sheet, investable tiers, top holdings) stay
  category = 'asset' on purpose and are denominated by GROSS assets.
- Router-built HTML bypasses Jinja autoescaping: every interpolated DB value goes through
  app.html.e(), embedded JSON through app.html.json_for_script(). Prefer a Jinja partial.
- No CDN. Fonts, HTMX and Chart.js are vendored under app/static/vendor/.
- app/schema.sql is the single, idempotent schema source and CANNOT add a column to an existing
  table. A new column needs an explicit migration step.
- USD is the base denomination; conversion goes through currency_service.
- Tests run against a copy of data/demo.db made by tests/conftest.py. Never write to data/.
- The gate is 'make check-all': ruff format --check, ruff check, mypy app/, pytest -q.
`

const wtOf = t => `${WT_ROOT}/${t.slug}`
const artOf = t => `${WT_ROOT}/_artifacts/${t.slug}`

/* Every agent works inside its task's worktree, never in the main checkout. */
const envFor = t => `
REPO (main checkout — DO NOT EDIT ANYTHING HERE): ${REPO}
WORKTREE (your repo root for this task, all paths absolute under it): ${wtOf(t)}
ARTIFACTS (plan, reviews, gate output, commit message): ${artOf(t)}
BRANCH: ${t.branch}   BASE: ${t.base}

Run every shell command from ${wtOf(t)}. ${wtOf(t)}/.venv is a SYMLINK to the real
virtualenv — that is expected and correct; never delete it (except where the Finalize
stage explicitly does) and never report it as an environment failure.
Never create a branch or worktree. Never push, never open a PR, never merge or rebase.
`

const pass = (prev, extra) => Object.assign({}, prev, extra)
const failed = p => p && p.failed

const SETUP_SCHEMA = {
  type: 'object',
  required: ['ok'],
  properties: {
    ok: { type: 'boolean' },
    head: { type: 'string', description: 'branch name HEAD resolves to in the new worktree' },
    error: { type: 'string' },
  },
}

const PLAN_SCHEMA = {
  type: 'object',
  required: ['plan_path', 'summary'],
  properties: {
    plan_path: { type: 'string' },
    summary: { type: 'string' },
    files_touched: { type: 'array', items: { type: 'string' } },
    needs_migration: { type: 'boolean' },
    new_dependencies: { type: 'array', items: { type: 'string' } },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
}

const PLAN_REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'summary'],
  properties: {
    verdict: { type: 'string', enum: ['APPROVED', 'REVISE'] },
    blocking: {
      type: 'array',
      items: {
        type: 'object',
        required: ['where', 'gap', 'fix'],
        properties: { where: { type: 'string' }, gap: { type: 'string' }, fix: { type: 'string' } },
      },
    },
    notes: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
}

const IMPL_SCHEMA = {
  type: 'object',
  required: ['ok', 'summary'],
  properties: {
    ok: { type: 'boolean' },
    summary: { type: 'string' },
    files_changed: { type: 'array', items: { type: 'string' } },
    diverged_from_plan: { type: 'boolean' },
    divergence_reason: { type: 'string' },
    error: { type: 'string' },
  },
}

const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'summary'],
  properties: {
    verdict: { type: 'string', enum: ['Approve', 'Request changes', 'Needs discussion'] },
    blockers: {
      type: 'array',
      description: 'Only 🔴 BLOCKER findings, plus 🟡 that name a missing test or a layering violation',
      items: {
        type: 'object',
        required: ['id', 'where', 'what', 'fix'],
        properties: {
          id: { type: 'string' },
          severity: { type: 'string' },
          where: { type: 'string' },
          what: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
    summary: { type: 'string' },
  },
}

const GATE_SCHEMA = {
  type: 'object',
  required: ['overall', 'summary'],
  properties: {
    overall: { type: 'string', enum: ['pass', 'fail'] },
    failing_stage: { type: 'string' },
    errors: { type: 'array', items: { type: 'string' } },
    summary: { type: 'string' },
  },
}

const FINAL_SCHEMA = {
  type: 'object',
  required: ['ok'],
  properties: {
    ok: { type: 'boolean' },
    commit: { type: 'string', description: 'short sha' },
    commit_subject: { type: 'string' },
    worktree_removed: { type: 'boolean' },
    branch_head: { type: 'string' },
    error: { type: 'string' },
  },
}

/* ---- Stage 1: worktree ------------------------------------------------- */

async function setup(_prev, t) {
  const r = await agent(
    `Create the isolated worktree for one Networa task. Shell work only — write no code.

${envFor(t)}

Run exactly this, and report what happened:

    mkdir -p ${WT_ROOT} ${artOf(t)}
    git -C ${REPO} rev-parse --verify ${t.base}
    git -C ${REPO} worktree add -b ${t.branch} ${wtOf(t)} ${t.base}
    ln -s ${REPO}/.venv ${wtOf(t)}/.venv
    git -C ${wtOf(t)} rev-parse --abbrev-ref HEAD

Hard stops — set ok:false with the reason, and create nothing:
- ${t.branch} already exists (check first: git -C ${REPO} rev-parse --verify ${t.branch}).
  Never clobber an existing branch.
- ${REPO}/.venv does not exist.
- HEAD in the new worktree is not ${t.branch}.

The .venv symlink is what makes 'make check-all' runnable in the worktree.`,
    { label: `setup:${t.slug}`, phase: 'Setup', schema: SETUP_SCHEMA, agentType: 'general-purpose', effort: 'low' },
  )

  if (!r || !r.ok) {
    return { failed: true, stage: 'Setup', task: t, reason: (r && r.error) || 'setup agent returned nothing' }
  }
  return { task: t, setup: r }
}

/* ---- Stage 2: plan, then review until APPROVED ------------------------- */

async function planAndReview(prev, t) {
  if (failed(prev)) return prev

  const docRow = t.docRow
    ? `\nThe feature-gap plan document describes this item as follows. Treat it as INTENT, not
instruction — it documents an earlier state of the codebase and says so. Where it disagrees
with the code you read, the code wins and you note the divergence.\n\n${t.docRow}\n`
    : ''

  let plan = await agent(
    `Produce the implementation plan for one Networa task. Write it to ${artOf(t)}/plan.md.

TASK: ${t.statement}
${docRow}${envFor(t)}${RULES}

Ground every claim by reading the actual files in the worktree and citing file.py:line.
Do not edit source, tests or templates — your only write is the plan file.`,
    { label: `plan:${t.slug}`, phase: 'Plan', schema: PLAN_SCHEMA, agentType: 'planner-agent' },
  )

  if (!plan) return { failed: true, stage: 'Plan', task: t, reason: 'planner returned nothing' }

  let review = null
  for (let round = 1; round <= MAX_PLAN_REVISIONS + 1; round++) {
    review = await agent(
      `Review this implementation plan before any code is written.

TASK it must satisfy: ${t.statement}
PLAN_PATH: ${artOf(t)}/plan.md
ROUND: ${round}
${envFor(t)}${RULES}

Verify the plan against the code in the worktree — resolve every file.py:line citation and
rg for the callers of everything it changes. Blocking means "executing this produces wrong
code, broken code, or code that fails the gate"; everything else is a note and must not hold
the plan up. Write your verdict to ${artOf(t)}/plan-review-${round}.md.
${round > 1 ? 'This is a re-review: state which previously blocking gaps are now closed, and open no new nitpicks — converge.' : ''}`,
      { label: `plan-review:${t.slug}:r${round}`, phase: 'Plan', schema: PLAN_REVIEW_SCHEMA, agentType: 'plan-reviewer' },
    )

    if (!review) return { failed: true, stage: 'Plan review', task: t, reason: 'plan-reviewer returned nothing' }
    if (review.verdict === 'APPROVED') return { task: t, setup: prev.setup, plan, planRounds: round }
    if (round > MAX_PLAN_REVISIONS) break

    const gaps = (review.blocking || [])
      .map((b, i) => `${i + 1}. [${b.where}] ${b.gap}\n   -> ${b.fix}`)
      .join('\n')
    log(`${t.slug}: plan revision ${round} — ${(review.blocking || []).length} blocking gap(s)`)

    plan = await agent(
      `Revise your implementation plan at ${artOf(t)}/plan.md in place.

TASK: ${t.statement}
${envFor(t)}
REVISION — address every blocking gap below. If you believe one is not a real gap, say so in a
short "## Reviewer disagreements" section with your reasoning; never silently ignore it. Keep
what was already sound — do not start over.

${gaps}`,
      { label: `replan:${t.slug}:r${round}`, phase: 'Plan', schema: PLAN_SCHEMA, agentType: 'planner-agent' },
    )
    if (!plan) return { failed: true, stage: 'Plan revision', task: t, reason: 'planner returned nothing on revision' }
  }

  /* Never implement a plan known to be broken — that is what this stage is for. */
  return {
    failed: true,
    stage: 'Plan review',
    task: t,
    reason: `plan still REVISE after ${MAX_PLAN_REVISIONS} revisions: ${review.summary}`,
    blocking: review.blocking,
  }
}

/* ---- Stage 3: implement ------------------------------------------------ */

async function implement(prev, t) {
  if (failed(prev)) return prev

  const r = await agent(
    `Implement one Networa task by executing an approved plan.

PLAN (read it first, it is the spec): ${artOf(t)}/plan.md
TASK: ${t.statement}
${envFor(t)}${RULES}

Rules for this stage:
- Every path you touch is absolute under ${wtOf(t)}. Never edit anything under ${REPO}.
- Do NOT commit, and do not stage anything. A later stage owns the commit.
- Do NOT run 'make format' or 'ruff format' — the gate checks formatting and the reviewer
  needs to see what you actually wrote.
- Do not delete ${wtOf(t)}/.venv.
- Write the tests the plan commits to. A fix ships with a test.
- If the plan turns out to be wrong once the code is in front of you, diverge deliberately and
  report it in diverged_from_plan / divergence_reason. A silent divergence is a defect.`,
    { label: `implement:${t.slug}`, phase: 'Implement', schema: IMPL_SCHEMA, agentType: 'coder-agent' },
  )

  if (!r || !r.ok) {
    return { failed: true, stage: 'Implement', task: t, reason: (r && (r.error || r.summary)) || 'coder-agent returned nothing' }
  }
  return pass(prev, { impl: r })
}

/* ---- Stage 4: review, then fix blockers -------------------------------- */

async function reviewAndFix(prev, t) {
  if (failed(prev)) return prev

  let review = null
  for (let round = 1; round <= MAX_REVIEW_FIXES + 1; round++) {
    review = await agent(
      `Review the change on this branch: everything in 'git -C ${wtOf(t)} diff ${t.base}...HEAD'
plus everything still uncommitted.

TASK the change implements: ${t.statement}
PLAN it was built from: ${artOf(t)}/plan.md
ROUND: ${round}
${envFor(t)}${RULES}

Report findings by severity as you normally do (🔴 BLOCKER / 🟡 SUGGESTION / 🟢 NIT) and write
the full review to ${artOf(t)}/review-${round}.md.

In the structured payload, put in 'blockers' ONLY: every 🔴, plus any 🟡 that names a missing
test or a layering violation. Leave 🟢 out entirely — style does not hold up this pipeline.
Check the debt-sign convention and the manual-escaping rule explicitly; they are this repo's
two most likely silent defects.`,
      { label: `review:${t.slug}:r${round}`, phase: 'Review', schema: REVIEW_SCHEMA, agentType: 'code-reviewer' },
    )

    if (!review) return { failed: true, stage: 'Code review', task: t, reason: 'code-reviewer returned nothing' }

    const blockers = review.blockers || []
    if (blockers.length === 0 && review.verdict !== 'Request changes') {
      return pass(prev, { review, reviewRounds: round })
    }
    if (round > MAX_REVIEW_FIXES) break

    log(`${t.slug}: review fix round ${round} — ${blockers.length} blocker(s)`)
    const list = blockers.map(b => `${b.id} [${b.severity || 'BLOCKER'}] ${b.where} — ${b.what}\n   fix: ${b.fix}`).join('\n')

    const fix = await agent(
      `Fix the review findings on this branch. Do not refactor beyond them.

${envFor(t)}${RULES}

${list}

Fix each one. If a finding is wrong, say so in divergence_reason instead of changing code you
believe is correct. Do not commit. Do not run 'make format'.`,
      { label: `review-fix:${t.slug}:r${round}`, phase: 'Review', schema: IMPL_SCHEMA, agentType: 'coder-agent' },
    )
    if (!fix || !fix.ok) {
      return { failed: true, stage: 'Review fix', task: t, reason: (fix && (fix.error || fix.summary)) || 'coder-agent returned nothing' }
    }
  }

  /* Never commit over a known blocker. */
  return {
    failed: true,
    stage: 'Code review',
    task: t,
    reason: `blockers still open after ${MAX_REVIEW_FIXES} fix rounds`,
    blocking: review.blockers,
  }
}

/* ---- Stage 5: gate, then fix until green ------------------------------- */

async function gate(prev, t) {
  if (failed(prev)) return prev

  const touched = ((prev.impl && prev.impl.files_changed) || []).join(' ')
  const needsSmoke = /templates\/|app\/routers\/|app\/__init__\.py|\.html/.test(touched)

  let result = null
  for (let round = 1; round <= MAX_GATE_FIXES + 1; round++) {
    result = await agent(
      `Validate this Networa change. mode=full${needsSmoke ? ', then mode=smoke' : ''}.

${envFor(t)}

The repo root for this run is ${wtOf(t)} — run 'source .venv/bin/activate && make check-all'
from there, NOT from ${REPO}. ${wtOf(t)}/.venv is a symlink to the real virtualenv: that is
expected, it works, and it is not an environment failure. Do not delete it and do not create
a new one.
${needsSmoke ? 'This change touched templates/routes, so also run mode=smoke — Jinja render and HTMX target errors are runtime errors the other stages will not catch.' : ''}

Report results only. Never edit source, never run 'make format' or 'ruff check --fix'.`,
      { label: `gate:${t.slug}:r${round}`, phase: 'Gate', schema: GATE_SCHEMA, agentType: 'compiler-agent' },
    )

    if (!result) return { failed: true, stage: 'Gate', task: t, reason: 'compiler-agent returned nothing' }
    if (result.overall === 'pass') return pass(prev, { gate: result, gateRounds: round })
    if (round > MAX_GATE_FIXES) break

    log(`${t.slug}: gate fix round ${round} — ${result.failing_stage} failed`)
    const fix = await agent(
      `The quality gate is red on this branch. Make it green.

${envFor(t)}${RULES}

Failing stage: ${result.failing_stage}
${(result.errors || []).join('\n')}

Fix the cause, not the symptom — never weaken a test or add a blanket ignore to silence the
gate. You may run 'source .venv/bin/activate && make lint' etc. from ${wtOf(t)} to check your
work. Do not commit.`,
      { label: `gate-fix:${t.slug}:r${round}`, phase: 'Gate', schema: IMPL_SCHEMA, agentType: 'coder-agent' },
    )
    if (!fix || !fix.ok) {
      return { failed: true, stage: 'Gate fix', task: t, reason: (fix && (fix.error || fix.summary)) || 'coder-agent returned nothing' }
    }
  }

  /* There is no "commit anyway". */
  return {
    failed: true,
    stage: 'Gate',
    task: t,
    reason: `gate still red after ${MAX_GATE_FIXES} fix rounds: ${result.failing_stage} — ${result.summary}`,
  }
}

/* ---- Stage 6: commit, then remove the worktree ------------------------- */

async function finalize(prev, t) {
  if (failed(prev)) return prev

  const type = t.branch.startsWith('fix/') ? 'fix' : t.branch.startsWith('chore/') ? 'chore' : 'feat'

  const r = await agent(
    `Commit this finished task and remove its worktree. The branch must survive.

${envFor(t)}

STEP 1 — write the commit message to ${artOf(t)}/commit-msg.txt.
Follow .claude/commands/commit-message.md and these rules exactly:
- Header: ${type}(<scope>): <summary>. The type is ${type}, from the branch prefix. Scope is one
  lowercase area (dashboard, assets, debts, cashflows, snapshots, sheets, import, exchange-rates,
  settings, schema, currency, security, templates, tests, ci, docs, deps) — omit it when the
  change spans several.
- Summary: imperative, lowercase, UNDER 50 CHARACTERS, no trailing period.
- Then a blank line, then a body wrapped at 72 characters saying WHAT and WHY, never HOW.
  Short bullets are fine.
- NO 'Co-Authored-By' trailer. This project does not use them.
Base it on 'git -C ${wtOf(t)} diff ${t.base}...HEAD' plus the uncommitted work, and on
${artOf(t)}/plan.md for the why.

STEP 2 — commit, in this exact order. The order matters:

    rm ${wtOf(t)}/.venv
    git -C ${wtOf(t)} status --porcelain
    git -C ${wtOf(t)} add -A
    git -C ${wtOf(t)} commit -F ${artOf(t)}/commit-msg.txt
    git -C ${wtOf(t)} status --porcelain

The 'rm' is FIRST and is mandatory: .gitignore has '.venv/', a directory-only pattern, so the
symlink is NOT ignored — leave it and it lands in the commit and blocks teardown. The tool
caches (.mypy_cache, .pytest_cache, .ruff_cache) are properly ignored; leave them alone.
Before 'add -A', check the status output really is only this task's work. The final status must
be empty. One commit unless the diff holds genuinely separate concerns deserving different types.

STEP 3 — teardown:

    git -C ${REPO} worktree remove ${wtOf(t)}
    git -C ${REPO} worktree prune
    git -C ${REPO} log --oneline -1 ${t.branch}

NEVER pass --force to 'worktree remove'. If it refuses, something is still uncommitted: stop,
leave the worktree in place, and return ok:false with what 'git status' shows. Forcing it would
delete work.

Do not push. Do not open a pull request. Do not merge or rebase. Do not touch ${artOf(t)} —
those artifacts are the audit trail for the human review.`,
    { label: `finalize:${t.slug}`, phase: 'Finalize', schema: FINAL_SCHEMA, agentType: 'general-purpose' },
  )

  if (!r || !r.ok) {
    return { failed: true, stage: 'Finalize', task: t, reason: (r && r.error) || 'finalize agent returned nothing', partial: r }
  }
  return pass(prev, { final: r })
}

/* ---- Drive the waves --------------------------------------------------- */

const waveNumbers = [...new Set(TASKS.map(t => t.wave || 1))].sort((a, b) => a - b)
const results = []
const okSlugs = new Set()

for (const w of waveNumbers) {
  const all = TASKS.filter(t => (t.wave || 1) === w)

  /* A chained task is based on its predecessor's BRANCH. If that predecessor never
     committed, the base is not usable — skip rather than build on sand. */
  const runnable = []
  for (const t of all) {
    const dep = t.dependsOn
    if (dep && !okSlugs.has(dep)) {
      log(`wave ${w}: skipping ${t.slug} — predecessor ${dep} did not complete`)
      results.push({ failed: true, skipped: true, stage: 'Blocked', task: t, reason: `predecessor ${dep} did not complete` })
    } else {
      runnable.push(t)
    }
  }
  if (runnable.length === 0) continue

  log(`wave ${w}: ${runnable.length} task(s) in parallel — ${runnable.map(t => t.branch).join(', ')}`)

  const waveResults = await pipeline(runnable, setup, planAndReview, implement, reviewAndFix, gate, finalize)

  waveResults.forEach((r, i) => {
    const t = runnable[i]
    if (r && !r.failed) okSlugs.add(t.slug)
    results.push(r || { failed: true, stage: 'Unknown', task: t, reason: 'pipeline returned nothing for this task' })
  })
}

/* Report shape the caller turns into the final table, and drives Stage 9 from:
   only 'committed' tasks get a plan-doc write-back, and never to 'done'. */
return {
  tasks: results.map(r => {
    const t = r.task || {}
    return {
      slug: t.slug,
      title: t.title,
      branch: t.branch,
      base: t.base,
      docKey: t.docKey || null,
      chainedOn: t.dependsOn || null,
      status: r.failed ? (r.skipped ? 'skipped' : 'failed') : 'committed',
      failedStage: r.failed ? r.stage : null,
      reason: r.failed ? r.reason : null,
      blocking: r.blocking || null,
      commit: r.final ? r.final.commit : null,
      commitSubject: r.final ? r.final.commit_subject : null,
      worktreeRemoved: r.final ? r.final.worktree_removed === true : false,
      worktreePreserved: r.failed && !r.skipped ? wtOf(t) : null,
      artifacts: t.slug ? artOf(t) : null,
      rounds: { plan: r.planRounds || null, review: r.reviewRounds || null, gate: r.gateRounds || null },
      planSummary: r.plan ? r.plan.summary : null,
      newDependencies: r.plan ? r.plan.new_dependencies || [] : [],
      needsMigration: r.plan ? r.plan.needs_migration === true : false,
    }
  }),
  committed: results.filter(r => !r.failed).length,
  failed: results.filter(r => r.failed && !r.skipped).length,
  skipped: results.filter(r => r.skipped).length,
}
