# Tunnel Goons

A one-page 2d6 game by Nate Treme (Highland Paranormal Society): roll 2d6, add one ability and one point per relevant item, meet a Difficulty Score. On a dangerous action the margin is the damage.

## Official sources

- The SRD, the author's own reference text: <https://tunnelgoons.com/srd>. It carries the 1.1 rules. Read 2026-09-01.
- Official downloads on itch.io: <https://natetreme.itch.io/tunnelgoons>. Files: `Tunnel Goons 1.2.pdf` (2019-10-03), `Tunnel Goons 1.1.pdf` (2019-08-06), a print layout, two character sheets, and Portuguese, Italian and Spanish translations. Both rules PDFs were read 2026-09-01. Where the 1.1 PDF and the SRD page differ: the PDF says "Level up at the end of a game session" (SRD page and 1.2: "every 2 game sessions"), and "the endangered participant takes" the damage (SRD page and 1.2: "damage inflicted"); the SRD page otherwise prints 1.1's creation (3 points, choose 3 items) with 1.2's rules text.
- Devlog for 1.2: <https://natetreme.itch.io/tunnelgoons/devlog/102800/tunnel-goons-12>. The only change from 1.1 is character creation: random tables with an implied setting, and 2 ability points instead of 3. The author confirms in the comments that 2 is deliberate, "to make players rely more on equipment". 1.1 stays available as "the original version".
- Site index and hacks list: <https://tunnelgoons.com/>.
- The game was first printed inside the zine *The Eternal Caverns of Urk*.

This file holds no rules text. Build from the SRD page above, not from a summary of it.

## Licence and attribution

Every page says "released under a Creative Commons 4.0 International License" and nothing more. The itch.io page quotes the deed's "Share" and "Adapt ... for any purpose, even commercially" lines, which match CC BY 4.0, but no page links the deed or names the variant. Neither rules PDF carries a licence line at all (1.1: "Created by Nate Treme. Find more RPG stuff at NATETREME.COM"; 1.2: "by Nate Treme"), so the itch.io statement is the licence of record and the attribution below is final. One email to the author would settle the variant.

Attribution, as `rules.md` carries it:

> Tunnel Goons is © Nate Treme (Highland Paranormal Society), released under a Creative Commons
> 4.0 International License. <https://tunnelgoons.com/>

## Pack sources

None. The starting item list is in the SRD's character creation.

Packs. A Tunnel Goons pack holds items, factions, people with their `hp`, monsters and the setting kit every pack carries — its setting, names, locations, seeds and special rules. None ships. A written one is selected on the scenario, and offers its tables on the character page, the way Loner's packs are.

## The tools

Every tool makes one change, rolls dice, opens a decision, or ends the turn.

- `reveal`, `move_item`, `kill`, `leave_party`, `unlock_way` (open a locked way once the story has dealt with it) and `rest` (heal the player and every party member to full Health in a safe spot).
- `move` — carry the player, the party, and any NPCs named in `with_ids`, through an unlocked way listed in WAYS OUT.
- `meanwhile` — move a dweller, move a loose item and shut a known way, offscreen, on a turn ELSEWHERE is shown.
- `roll` — 2d6 plus an ability and helpful items, against a Difficulty Score or an npc; `actor_id` when a hired member acts instead of the player.
- `level_up` — raise one ability and either Health or Inventory by 1, once per game: the player first, then each hired member in turn.
- `join_party` — someone here travels with the player. With `terms`, the player hires them to work: the worldsmith writes their sheet once the turn ends, and they join the party.

## Deviations in this repo

1. Levelling up is a step the master calls once per game. The SRD page says "every 2 game sessions", the 1.1 PDF "at the end of a game session"; one game is the closest thing this app has to a session.

## What the AI game master adds

Every entity has `known`, and a `Way` is known once the player has walked it: what the player has found stays legible turn to turn without the master having to restate it. Every non-player character — friend or foe — is one shape, exactly as the SRD prints: an id, a name, a Health that is also its Difficulty Score, and whether it is still alive. The party follows the player through `move` on its own. A hired npc carries the same three abilities as the player and rolls, rests and levels beside them; one without a sheet still cannot roll on its own. The map's extension bar lets the worldsmith write a new region once the authored map is fully walked. `kill` ends a helpless npc outright, no roll needed.

## Where the rules live

`src/rulehall/engines/tunnelgoons/`, instructions in `rules.md`. The room machinery is `RoomEngine` in `src/rulehall/engines/rooms/`.
