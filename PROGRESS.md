# Progress

## Phase 1 — Real fights and real stakes (2026-09-27)

- `src` lines: 17963 → 18664 (target ≤ 18750).
- Two Opus implementers, in sequence: part A (1.1–1.5, 1.10), then part B (1.6–1.9, 1.11). Two Opus reviewers. Pokemon and create QA smokes pass.

Off-plan decisions:
- `SIGNATURE_EXCLUDED` holds every move that fails, recharges, takes two turns, faints the user, strikes later or changes type in the dex, not only the plan's list. `signature_moves` falls back to the latest level-up moves when nothing is left (Unown).
- Greedy takes the first knock-out move offered. At team preview, the scripted pick (`team 1`) is used without an assess.
- The rival's other Pokemon are distinct after evolving, and never the ace's species. After a battle the rival goes to the last place visited, else an unlocked way out, else stays.
- A world holds one rival at most. A gym leader with no roster is refused. `beaten` is never set on the rival.
- Key trainers (`Trainer.is_key()`) refuse `kill` and `join_party` in `PokemonWorld`, not in engine tool overrides.
- The rival counter-picks the starter (`caught_species[0]`), not the current lead.
- The master sees a `Style` row on key trainers and a `POKEMON CENTERS` section of the known Centers.
- `encounters` and `caught_species` are kept in every challenge; only Nuzlocke acts on them. A Nuzlocke wipe writes the "has fallen" cards but moves no one and skips the blackout.
- `rules.md` and the tool text say the rival battles once before the first badge, then once after each badge.

Refuted review findings: none.

## Phase 2 — The evil team (2026-09-27)

- `src` lines: 18664 → 19141 (target ≤ 19150).
- One Opus implementer, two Opus reviewers. Six new tests in `tests/pokemon/test_scheme.py`; goldens drift only in the Pokemon master and worldsmith prompts and the region schema. The Pokemon QA smoke passes end to end: the first operation foiled, the next lost to a badge, two lost to their leaders, and the lair.

Off-plan decisions:
- `RosterSlot` and `SPECIES_ID` move to `rules.py`, so `rules.rescaled` returns roster slots without importing the world. `rules.is_legendary` serves the catch rate, `counter_pick` and the scheme check.
- Key-ness has one rule, `Trainer.is_key(named_ids)`: a badge, the rival, or a named id. The world names its ids with `key_ids()` (leaders and the boss); a proposal check names its operation's leader and its `boss_id`. The npc `Style` row shows whenever a style is set.
- `PokemonOpening.operation` is required and `PokemonRegion.operation` optional; `PokemonMap` holds neither, and `_check_proposal` takes the operation as an argument.
- The held-way refusal lives in `PokemonWorld.unlock_way`, beside phase 1's `kill` and `join_party`; the base tool calls it.
- `open_operation` moves every leader to the operation's place, a new one too, and clears `beaten`, so an earlier leader pays a prize again.
- `new_game` runs the Pokemon checks before the rooms map check, so `absorb` never opens an operation the check refuses.
- A shut way and the not-a-bridge check walk past ordinary locks but never through a held or cut way. A way is held only when the places reached from the player's place stay the same.
- A closed Center's card reads "{Center} has closed": a Center is a place of its own, so "The Pokemon Center at {X}" would repeat its name. The stage fact is the stage line alone.
- Only a foil teaches a leader: `counter_pick` at the ace level fought, as a slot at the roster's ace − `BELOW_ACE` (floor `LEVEL_FLOOR`); nothing changes when the roster already holds that species.
- With three successes, the legendary joins the boss at the ace level; a full rescaled roster keeps its five highest slots.
- The master's THE SCHEME shows the goal, only the stage lines told so far, the leaders, the open operation, its stake, the trigger, the rumour at an open Center and the final terms. The worldsmith's THE SCHEME shows the stages up to the next one, and the guidance forbids writing the goal or an untold stage into a place, a person or the recap.
- `TrainerSheet.table_level()` gives the next gym's ace level; `level_cap` uses it. The world validator rejects an operation at no place or with no leader, a scheme-less operation, boss or held way, a held way that is no way, and more than four stages.
- `Scheme.legendary_id` and `Operation.shut_to_id` default to null. The regular-trainer cap and the guidance say "besides the key trainers".
- QA: the scripted opponent takes its first choice, and the scripted worldsmith writes a Pokemon region with one chief who leads the owed operation or is the boss. The run feeds Charmander 25 Rare Candies in rounds (a new move to learn pauses every tool), waits for the battle choices before fighting, and loses to the later leaders by Forfeit. `drive.run` counts a crash as an issue.

Refuted review findings: none; all eleven were folded.
