---
name: phase
description: Run one PLAN.md phase end to end — brief, one or more Sonnet/Opus subagents implement from it (parallel, sequential, or a mix), you verify, Fable + Codex Sol adversarial reviews (a second Opus reviewer where codex is unavailable), fold, PROGRESS.md entry — and stop before the commit. Use when the user says "implement phase N", "run phase N", or "/phase N".
argument-hint: <phase number or name>
---

# /phase $ARGUMENTS

You are the orchestrator and the implementers' brain. Claude subagents write the code; you write
their instructions, read their diffs, verify, and decide. You do not write code beyond a few-line fix and
you never commit. Restate `step k of 6` at the top of every message to the user.

## 1. Brief

Read `PLAN.md` (the "How to work" rules and phase $ARGUMENTS), `PROGRESS.md` (standing
decisions), `CLAUDE.md`, and every file the phase names. Trace the real flow the change touches;
you cannot instruct what you have not read. Open `tests/` only where a PLAN step names a file;
the brief never lists tests. Record the `src` line count from the `PLAN.md` command.

Write `/tmp/phase-$ARGUMENTS/brief.md`. It is both the record of the phase and the instruction
the implementer runs, so it must be precise:

```
# Phase <N> — <title>
## Implementer     sonnet | opus — opus only if a step below says "decide" or "research"
                   instead of naming a shape; a research phase produces a brief, not a diff
## Goal            one paragraph, copied intent not paraphrased rules
## Steps           numbered, one action each, straight from PLAN.md; for each: the files to
                   touch and the exact shapes (signatures, models, fields)
## Done when       observable checks: behaviour named, line-count target, four commands green
## Out of scope    what the phase must not touch; standing decisions it must not re-open
## Split           one implementer | parallel: A, B | sequential: A then B | mix — see below
## Rules           the two paragraphs below, verbatim
```

### Split

One implementer is the default. Split when the steps are more than one context window of work:
more than ~6 files touched, more than ~400 lines changed, or a research step plus a code step.
Group the steps into parts by the files they touch:

- Two parts touch disjoint files → **parallel**.
- A part needs a shape another part creates (a model, a signature) → **sequential**. Write the
  shape in both briefs anyway, so the second can start from text, not from reading the first's diff.
- A file needed by two parts → merge them into one part, or make them sequential. Never let two
  implementers edit one file.

Write one `/tmp/phase-$ARGUMENTS/brief-<A|B|..>.md` per part. Each part-brief is complete on its
own: Goal, its Steps, its Done when, the shared shapes, and an Out of scope that names
the files the other parts own. `brief.md` stays the record of the whole phase and names the split.

Rules paragraphs:

> Read only the files named here and their direct imports. Do not explore the rest of the repo.
> Verify with: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
> `uv run basedpyright`. Don't commit and don't stage; the orchestrator stages.

> Follow our coding principles: clean, SOLID, DRY, KISS, simple/readable code, concise docstrings,
> only comment the 'why', fail fast, strict type safety, avoid 'Any' and avoid any optional unless
> needed. Tests: green, and one test per new core behaviour. Do not read `tests/` beyond the
> files a step names; do not enumerate or audit existing test cases.

If PLAN.md is ambiguous on something that changes the work, ask the user once, now.

## 2. Implement

1. Spawn one implementer per part, in the background, with the model its brief names:
   `Agent(subagent_type="general-purpose", model="sonnet"|"opus",
   prompt="Implement /tmp/phase-N/brief-A.md exactly. Read it first; its Rules section binds you.")`
   Parallel parts: all `Agent` calls in one message. Sequential parts: spawn the next only after
   the previous part passed step 2.2. Wait for completion notifications. Do not poll.
2. Verify yourself: the four commands, then `git status` and `git diff` against the part's brief
   step by step. Read the `src/` diff; do not trust the implementer's summary. For `tests/` the
   check is only: green, and each new behaviour has one test.
3. Red check or a missing step → `SendMessage` the same agent with only the gap and the exact
   error; it keeps its round-1 context. Three rounds and still red → stop and report to the user;
   never patch around it silently.
4. An implementer that ran out of context or stopped mid-way is dead: do not message it. Read
   its diff, write `brief-<part>-rest.md` with only the steps still missing (and the shapes it
   already made), and spawn a fresh agent on it. Two deaths on one part → the part is too big;
   split it and tell the user.
5. All parts done: `git add -A`, run the four commands once more on the staged tree.

## 3. Review — both at once, in one message

- `Agent(subagent_type="reviewer", prompt="Review the staged phase; brief: /tmp/phase-N/brief.md")`
- `cat .claude/prompts/review.md > /tmp/phase-N/sol.md; echo "Brief: /tmp/phase-N/brief.md" >> /tmp/phase-N/sol.md;
   .claude/scripts/codex.sh gpt-5.6-sol high read-only < /tmp/phase-N/sol.md > /tmp/phase-N/review-sol.md`
  (Bash, `run_in_background: true`)

Save the Fable review to `/tmp/phase-N/review-fable.md`.

No `codex` on the machine (remote containers have neither the CLI nor OpenAI credentials)?
Replace that review with a second independent reviewer instead of skipping it:
`Agent(subagent_type="reviewer", model="opus", prompt="Review the staged phase; brief:
/tmp/phase-N/brief.md")`, saved to `/tmp/phase-N/review-opus.md`. Say in the final report which
pair of reviews ran.

## 4. Fold

1. For every finding in both reviews decide: **fix** or **refute**. Refute only with a concrete
   reason (a line, a rule in `CLAUDE.md`, a measured fact). "Matter of taste" is not a reason.
2. Fixes of a few lines: edit directly. Larger fixes: `SendMessage` the implementer agent that
   owns those files with the findings to fix, same as step 2.3.
3. Four commands green, `git add -A`.
4. Write one table: `# | finding | fixed / refuted | reason or file:line`. Any refutation that
   rests on your own judgment of the instructions you wrote: hand it to the user with the finding
   and your reason side by side. Do not decide it for them.

## 5. Verify

Run the four commands and `uv run rulehall` smoke if the phase touched the game. Count `src` lines
again. Read the staged diff's `--stat` and open anything the reviews flagged as fixed.

## 6. Record and stop

Add the phase's `PROGRESS.md` entry: counts before/after, decisions made off-plan, refuted
findings and why, anything known-and-accepted. Stage it. Tell the user in five lines: counts,
refutations awaiting their call, and "ready to commit". The commit is theirs.
