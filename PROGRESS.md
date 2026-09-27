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
