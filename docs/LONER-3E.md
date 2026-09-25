# Loner 3e

A solo oracle-driven system: Chance d6 against Risk d6, six outcomes, a Twist Counter, Harm
resolved against Luck.

## Official sources

- Core rules SRD: <https://lonersrd.zotiquestgames.com/core/loner-3e.html>
- Site index: <https://lonersrd.zotiquestgames.com/>
- Document source (`content/core/loner-3e.md`): <https://github.com/zotiquestgames/lonersrd>
- The deleted extraction was taken from the v.3.0 page as it stood at commit `2946f2f` (2026-08-13);
  the site carries no version pin of its own, so re-read the live page rather than trusting that.
- Explanatory guide, covering Loner **2e** rather than 3e — the mechanics differ, e.g. it prints
  the equal result as *Yes, and...*, where 3e prints *Yes, but... +1 Twist*:
  <https://keeper.farirpgs.com/resources/zotiquest-games/loner/introduction/>

This file used to hold a near-verbatim extraction of the 3e core rules. It was deleted so that no
pack is ever transcribed out of a copy: build from the official page above. The old text is in git
history.

## Licence and attribution

Loner v.3.0 © 2025 Roberto Bisceglie, licensed under Creative Commons Attribution-ShareAlike 4.0
International (<http://creativecommons.org/licenses/by-sa/4.0/>). Site footer: © 2021-2026 Roberto
Bisceglie, Zotiquest Games. ShareAlike binds the adaptations — this repo's packs and `rules.md`,
which carry it. The required attribution:

> Loner v.3.0 © 2025 Roberto Bisceglie. This work is licensed under the Creative Commons
> Attribution-ShareAlike 4.0 International License.

The SRD credits, as printed: [Recluse Engine](https://gravenutterance.itch.io/recluse) (CC BY 4.0)
by Graven Utterance and Tiny Solitary Soldier Oracle for the main resolution and scene mechanics;
[Freeform Universal](https://www.perilplanet.com/freeform-universal/) (CC BY 4.0) by Nathan Russell
for the character traits; harm mechanics from [6Q System](https://chaosmeister.itch.io/6-q-system)
(CC BY 4.0) by Marcus Burggraf; Tana Pigeon for [Mythic](https://www.wordmillgames.com/mythic.html);
S. John Ross for [Risus](https://www.risusrpg.com/); the Adventure Maker setup is inspired by
*The Instant Game* by Animalball Partners (2007).

## Pack sources

- `packs/srd.json` — written for this repo; only its twist columns come from the core rules
  page above (deviation 4).
- `packs/ap01-fantasy.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP01_fantasy.html>.
- `packs/ap02-space.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP02_space.html>.
- `packs/ap03-superheroes.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP03_superheroes.html>.
- `packs/ap04-crime.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP04_crime.html>.
- `packs/ap05-mystery.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP05_mystery.html>.
- `packs/ap06-horror.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP06_horror.html>.
- `packs/ap07-action-adventure.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP07_action_adventure.html>.
- `packs/ap08-spy.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP08_spy.html>.
- `packs/ap09-postapoc.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP09_postapoc.html>.
- `packs/ap10-pirates.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP10_pirates.html>.
- `packs/ap11-western.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP11_western.html>.
- `packs/ap12-cyberpunk.json` — <https://lonersrd.zotiquestgames.com/adventure_packs/AP12_cyberpunk.html>.
- The twelve packs are checked in; each pack's `source` field names the SRD page it was taken from,
  and the four trait tables' ids are the labels' slugs with diacritics folded (`Naïve` → `naive`).

**Open question, carried from `README.md`:** the AP01 page carries no CC declaration at all — only
the site-wide footer "© 2021-2026 Roberto Bisceglie" — while the site index declares CC BY-SA 4.0.
It is treated as covered by the site's licence. All twelve pages read the same way: the site
index declares CC BY-SA 4.0 and every pack page carries only the copyright footer. One email to
the publisher would settle it.

## The tools

Every tool makes one change, rolls dice, opens a decision, or ends the turn.

- `reveal`, `enter`, `leave`, `kill`, `join_party`, `leave_party`,
  `change_tags` (an actor's gear or condition tags), `drive` (goal, motive, nemesis),
  `restore_luck` (refill an actor's Luck and clear their defeat once the conflict is behind them)
  and `spend_luck` (pay a cost the chosen pack's special rules print, such as a spell).
- `next_scene` — offer the player the way on at a stopping point; or say that they left this
  place, and the worldsmith writes where they land; or hand the worldsmith a complication to
  bring down on this place. The last two end the turn.
- `roll` — Chance against Risk for one closed dramatic question; an advantage or disadvantage
  adds one die to that side; a tie outside a conflict counts on the Twist Counter and may roll a
  twist; in a conflict the losing side's Luck pays.

## Deviations in this repo

Every divergence between `src/rulehall/engines/loner3e/` and the official rules, with the reason it
stands. Nothing diverges silently: a rule not listed here is implemented as printed. The SRD's
optional tools are not deviations by their own text: the Adventure Maker, the 5W+H frame and the
open-ended inspiration tables are offered "if you need inspiration" and stay authoring-time —
scenarios here are authored ahead of play; the next-scene mood roll is for when "you're unsure",
and deciding when to ask the Oracle is the player-seat judgment — the game master holds that seat.
Appendix A is by its own words a *version* of Loner that removes dice — an alternative game, not
a rule of this one.

1. **A twist fires inside the question that rolled it.** The SRD has a twist interrupt the scene
   the moment it fires; here the tie that calls one is inside a resolved question, so the
   narration shows the twist arriving in that same turn rather than cutting the question short.
   The pairing reaches the game master in that call's own answer, and it develops what arrived in the
   same interaction.
2. **One Twist Counter, `Loner3eState.twist`, beside the world.** The SRD's counter belongs to the
   solo player, who is the only one rolling. Here any character can be the subject of a question,
   so a single tally covers every roll: a tie anywhere moves that one counter.
3. **The Twist Counter is hidden from the player.** The SRD's solo player keeps the tally
   themselves; here it stays off the player's view, paces the game master, and is never recited —
   rising tension shows only in the fiction.
4. **`packs/srd.json`'s starter tables are this repo's, not the SRD's.** The concepts, skills,
   frailties and gear in that pack are written for this repo; Loner 3e publishes no such tables.
   Only the twist subject and action columns are the SRD's, and the pack's `license` line already
   says so. A creation table is the SRD's entries followed by the chosen pack's, so the starter
   tables are offered beside an Adventure Pack's.
5. **The party.** The solo SRD has no party; here `join_party` and `leave_party` mark who
   travels with the player, and the party follows into the next scene. Post-game growth is the
   SRD's own step, written with `change_tags` and `drive` when the adventure closes: no advance is
   counted or owed.
6. **Trait labels carry no meaning of their own.** The SRD prints its d66 tables bare; a
   converted pack's `concept`, `skill`, `frailty` and `gear` labels are exactly what it prints,
   with no rules meaning attached. The glossary the game master reads (`pack_meanings`) lists only
   the entries that do carry a `detail`, which the SRD's own tables never do.

## Readings where the SRD is open

- **Luck pools other than 6.** The SRD prints "Start with 6 Luck" and every example character,
  the alley thug included, carries 6. The one place it leaves the size open is "Treat the
  Opponents as a Single Entity", where a group gets "a single Luck pool that represents their
  overall strength" with no number. This repo reads that latitude as covering any opposition,
  not only groups, so the worldsmith sizes a pool to how long that character should hold out.
  A player character starts at 6 as printed. The group half is the SRD's own; extending it to a
  lone minor opponent is this repo's reading, recorded here rather than in the deviations above
  because it changes no printed rule.

## What the AI game master adds

Fields and tools that exist for the app around the rules, not the rules themselves — each earns
its keep for a reason the SRD has no need of.

- `known` and `hidden` — the told-fact gate: no unknown name reaches the narrator.
- `alive` and `kill` — the SRD leaves death to narration; the gate needs a flag.
- `defeated` — the SRD's solo player simply remembers they won; Luck resets at once, so the
  engine needs a flag to refuse a duel reopened after the reset. Only `restore_luck` clears it:
  a defeat is settled by the game master, never slept off by moving to the next place.
- `next_scene` and the scene's `offered` flag — a stopping point the player may stay at.
- No mood roll — the SRD offers it "when unsure"; the game master holds that judgment.

## Where the rules live

Mechanics are in `src/rulehall/engines/loner3e/`; the scene machinery shared with the other
scene engines is `SceneEngine` in `src/rulehall/engines/scenes/`. `packs/srd.json`'s twist columns —
not this file — are the transcription of record.
