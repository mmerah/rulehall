---
name: feature
description: Take one feature from request to staged diff. Research, ask the user until the spec is exact, orchestrate Opus and Sonnet implementers, then run adversarial Opus reviews and a live check. Stops before the commit. Use when the user says "/feature <request>", "implement this feature", or gives a feature to build end to end.
argument-hint: <what to build>
---

# /feature $ARGUMENTS

You are the orchestrator. Subagents research, write code, and review. You read, decide, and verify.
Do not write code yourself, except a fix of a few lines. Do not commit. Write `phase k of 5` at the
top of each message to the user.

Keep all work files in `/tmp/feature-<slug>/`. `<slug>` is a short name for the feature.

## 1. Research

1. Read `CLAUDE.md`. Read the files that the feature touches. Trace the real flow from the UI to
   the core. You cannot write a spec for code that you did not read.
2. Find the sibling: the feature in the codebase that is most similar. The new code must follow
   its pattern: the same files, names, config shape, and layers.
3. Spawn 1 to 3 Opus agents in one message, in the background. Give each agent one topic:
   - External research: APIs, libraries, browser support, cost. Ask for exact request shapes
     and sources.
   - Codebase fit: the seams, new files, names, and the smallest cut. Use `subagent_type="Plan"`.
   - A second opinion on a hard decision, if there is one.
4. Wait for the notifications. Do not poll. Do not do the same research yourself.

## 2. Specify

1. List each decision that changes the work. For each decision, give your recommendation first.
2. Ask the user with `AskUserQuestion`. Ask at most 4 questions in one call. Ask again until no
   decision is open. Do not ask about a decision that the code or `CLAUDE.md` already makes.
3. Write `/tmp/feature-<slug>/spec.md`:

```
# <feature>
## Goal         one paragraph, in the words of the user
## Decisions    each answer of the user, one line each
## Steps        numbered, one action each: the files to touch and the exact shapes
                (signatures, models, fields, events)
## Done when    observable checks: the behaviour, and the four commands green
## Out of scope what the work must not touch
## Parts        the split, and the model for each part (see phase 3)
```

## 3. Implement

1. Split the steps into parts by file. One part is the default.
   - Two parts with no shared file: run them in parallel.
   - A part that needs a shape from a different part: run it after that part. Write the shape
     in both briefs.
   - Two implementers never edit one file.
2. Pick the model for each part:
   - Opus: new design, a hard flow, browser JavaScript, concurrency, or a step that says "decide".
   - Sonnet: a named shape to type in, config, wiring, a small UI change.
3. Write `/tmp/feature-<slug>/brief-<part>.md` for each part. Each brief is complete by itself: the
   goal, its steps, the shared shapes, its done-when, the files that other parts own, and the
   rules below, word for word.
4. Spawn each implementer in the background:
   `Agent(subagent_type="general-purpose", model="opus"|"sonnet", prompt="Implement
   /tmp/feature-<slug>/brief-<part>.md exactly. Read it first. Its Rules section binds you.")`
5. Verify each part yourself. Run the four commands. Read the `src/` diff against the brief, step
   by step. Do not trust the summary of the agent.
6. A red check or a missing step: `SendMessage` the same agent with only the gap and the exact
   error. After three rounds, stop and tell the user.
7. An agent that stopped mid-way is dead. Do not message it. Write `brief-<part>-rest.md` with
   only the missing steps, and spawn a new agent.
8. All parts done: `git add -A`. Run the four commands on the staged tree.

Rules for each brief:

> Read `CLAUDE.md`, the files named here, and their direct imports. Do not explore the rest of
> the repo. Verify with `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`,
> `uv run basedpyright`. Do not commit. Do not stage.

> Follow the codebase: clean architecture, SOLID, DRY, KISS. Copy the pattern of the sibling
> code. Use exact types. Use no `Any` and no optional value that is not necessary. Fail fast.
> Write no comments and no docstrings. The exceptions: a critical "why" in one line, and text that
> a model reads (tool docstrings, Field descriptions). Add a unit test only for minimal core
> behaviour. Do not read `tests/` beyond the files named here.

## 4. Review and test

1. Spawn 1 to 5 reviewers in one message, in the background. Each reviewer gets one angle:
   `Agent(subagent_type="reviewer", model="opus", prompt="Review the staged diff. Spec:
   /tmp/feature-<slug>/spec.md. Angle: <angle>.")`
   Angles: correctness; clean architecture and SOLID; names and readability; over-engineering,
   ceremony, and cuts. Use fewer reviewers for a small diff.
2. Spawn one Opus tester at the same time. It runs the real app and proves that the feature works:
   `Agent(subagent_type="general-purpose", model="opus", prompt="Prove that the staged feature
   in /tmp/feature-<slug>/spec.md works. Start the app with the QA harness (qa/README.md) or
   `uv run rulehall` on a free port. Drive it with Playwright. Check each done-when item.
   Mock only what needs a key or a device. Report pass or fail per item, with evidence.
   Do not edit files in the repo. Stop every process that you start.")`
3. Save each report to `/tmp/feature-<slug>/review-<angle>.md` and `test.md`.

## 5. Fold and stop

1. For each finding, decide: fix or refute. Refute only with a concrete reason: a line, a rule in
   `CLAUDE.md`, or a measured fact. "Taste" is not a reason.
2. Small fixes: edit them. Larger fixes: `SendMessage` the implementer that owns the file.
3. A failed test item: fix it, then run that check again.
4. Four commands green. `git add -A`.
5. Tell the user, in a short report:
   - A table: `# | finding | fixed or refuted | reason or file:line`.
   - The test result per done-when item.
   - Each refutation that rests on your own judgment. Give the finding and your reason. The user
     decides.
   - "Staged. Ready to commit."
