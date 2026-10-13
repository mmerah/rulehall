---
name: spec-run
description: Build a phased spec one item at a time. Runs the full /feature workflow on the next item of the spec's phase table, questions included, and stops with the item staged for the user to review and commit. After the last item, it deletes the spec and rewrites the rules doc in the shape of its siblings. Use when the user says "/spec-run <spec>", or wants to build a spec that has phases.
argument-hint: <path to the spec> [item]
---

# /spec-run $ARGUMENTS

One run builds one item of the spec. For that item, you are the `/feature` orchestrator: read
`.claude/skills/feature/SKILL.md` and follow it, with the changes below. Write
`item <id>, phase k of 5` at the top of each message to the user.

## 0. Start

1. Read `CLAUDE.md` and the spec. Read the rules file that the spec names, if any.
2. List the items of the spec's phase table, in build order. An item is one `/feature` run.
3. Find the item to build. `git log --oneline` shows the items done: each commit message starts
   with `<spec name> <item id>:`. Take the first item with no commit, or the item the user names.
4. Stop when the working tree has staged or unstaged changes in `src/` or `tests/`: the user has
   not committed the last item yet. Say so, and wait.
5. Show the user the item list, with the items done, and the item to build now.

## 1. The item

Run the five phases of `/feature` on the item, with these changes:

- **Research.** The spec section of the item is the request. Read the code that it names.
  Research only what the spec leaves open.
- **Specify.** The spec and the rules file already hold most decisions. Copy them into
  `/tmp/feature-<slug>-<item>/spec.md` as decided. Ask the user only about what is still open:
  what the code shows that the spec did not decide, a spec line that the code contradicts, or a
  choice between two clean shapes. Give your recommendation first, as `/feature` says.
- **Implement, Review and test, Fold.** As `/feature`. The run ends staged, not committed.

When the work shows that the spec is wrong, stop. Tell the user the spec line, the code fact, and
your fix. Edit the spec only after the user agrees, and stage that edit with the item.

## 2. The end of the run

Report as `/feature` does, then add:

- The commit message to use: `<spec name> <item id>: <item title>`. The next run reads it.
- The next item.
- When the item ends a spec phase (for example, phase 0 or 1a): what the user can now play or
  see in the app, and what to try.

Then stop. The user reviews, commits, and starts the next run.

## 3. The close

When every item of the phase table has a commit, the next run is the close. It builds no code.
The code is the reference now, and a spec beside it would drift.

1. Delete the spec. Keep nothing of it elsewhere.
2. Rewrite the rules file that the spec names, if any, in the shape of its siblings in `docs/`
   (for an engine: `docs/TUNNEL-GOONS.md`, `docs/LONER-4E.md`, `docs/24XX.md`). Read them first.
   - Keep: the sources, the licence and attribution, the pack sources, the scope in a few lines,
     the deviations from the source rules with their reasons, and what the AI game master adds.
   - Remove every implementation detail: file names, classes, fields, ids, commands, phases and
     tests. Point to the code where the rules live, as the siblings do.
   - Check each rule that stays against the code. The code wins. Tell the user each difference.
3. Remove any link to the spec from other docs.
4. Stage the result and stop, as for an item, with the commit message `<spec name>: close`.
