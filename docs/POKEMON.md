# Pokemon

A Pokemon journey played as a tabletop RPG. No official Pokemon tabletop game exists, so this rule
set is our own: a light d20 layer for the trainer, and the real battle rules for the fights. The
master runs towns, routes, people and trainer checks on a map. When a fight starts, the fight runs
in the Pokemon Showdown simulator, and the player picks moves in Showdown's battle view.

## Sources

- **Pokemon Showdown**, the simulator: <https://github.com/smogon/pokemon-showdown>. The npm
  package `pokemon-showdown` is pinned at 0.11.11 in `showdown/package.json`. It runs every battle
  and supplies the species, moves, learnsets, abilities and items of the dex.
- **Pokemon Showdown client**, the battle view: <https://github.com/smogon/pokemon-showdown-client>.
  The setup fetches its built battle files and styles from <https://play.pokemonshowdown.com/>.
- **PokeAPI**: <https://pokeapi.co/>. The regional dexes of the packs, EV yields, ability texts and
  Pokedex entries. Item icons come from <https://github.com/PokeAPI/sprites>.
- **Pokemon Tabletop United** (PTU), a fan-made tabletop game. The catch roll follows its rule: a
  d100 against a rate built from level, HP, status and evolution stage. The d20 skill checks take
  after PTU and its older sibling PTA, in a much lighter form.

## Licence and attribution

Rulehall is free and open source. It sells nothing, shows no ads and has no paid tier. It is a fan
project in the same spirit as Pokemon Showdown itself.

Rulehall is not affiliated with, endorsed or sponsored by Nintendo, Creatures Inc., Game Freak or
The Pokemon Company. Pokemon and every Pokemon name are trademarks of their owners. Rulehall's MIT
licence covers Rulehall's own code only. It gives no rights to anything below that belongs to them.

| What | Where it comes from | Licence |
|---|---|---|
| The engine, the rules and the battle driver | This repo | MIT, Rulehall |
| The simulator | npm, installed at setup | MIT |
| The battle view (`battle*.js`), Showdown's data files | Fetched at setup | MIT. The file headers say "the battle replay/animation engine (battle-*.ts) by itself is MIT" |
| The rest of the Showdown client | Not used | AGPLv3. We fetch none of it and draw our own choice buttons |
| jQuery, html-sanitizer | Fetched at setup | MIT, Apache 2.0 |
| `dex.json` | This repo, built by `export-dex` | Numbers from Showdown's MIT data. The names, the ability texts and the Pokedex entries are the owners' text, through PokeAPI |
| Pokemon and trainer sprites, battle backgrounds, music, cries, item icons | Fetched at setup | © Nintendo, Creatures Inc., Game Freak, The Pokemon Company |

The git repo holds no Nintendo art or sound. The setup fetches them to your computer from the same
public servers that the Showdown website uses. The Docker image bundles that fetch, so the image
runs offline.

If you hold rights to anything here and want it removed, open an issue. It comes out.

## Pack sources

Ten packs, one regional dex each: Kanto (`srd.json`), Johto, Hoenn, Sinnoh, Unova, Kalos, Alola,
Galar, Hisui and Paldea. `export-packs` writes each pack's species list from PokeAPI's regional
dex. The three starters and the prose of each pack are ours.

Only the pack's species live in the region, and a Pokemon evolves only into a species of the
region's dex. A regional forme stands in for its base forme: the Alola pack has Alolan Rattata,
not Rattata.

## The tools

The map tools of Tunnel Goons stay: `move`, `move_item`, `unlock_way`, `meanwhile`, `reveal`,
`kill`, `join_party`, `leave_party` and `direct`. A locked way can be a Cut tree or a gym door.

- `check`: a d20 trainer check, with one team Pokemon as a helper.
- `start_battle`: fight a trainer who is here. It ends the master's turn.
- `start_wild_battle`: fight a species from the wild table of this place, or a random one.
- `heal_team`: a Pokemon Center heals the team and the box.
- `buy`, `gain_item`, `gain_money`: the bag and the wallet.
- `use_item`: a potion, a revive, a Rare Candy, a stone or another evolution item.
- `swap_mon`: swap a team Pokemon with a box Pokemon.

The player also acts without the master, from the Team tab and from decisions: hold an item, teach
a TM, relearn a move, send a Pokemon to the box or back, set the lead, learn a new move, raise a
skill after a badge, and pick an evolution.

## Our rules

- Six trainer skills, ranked 0 to 3: Athletics, Stealth, Perception, Nature, Lore, Charm. A check
  is d20 + 2 × rank, +2 with a helper, against DC 10, 15 or 20. Each badge gives one rank.
- EXP is `20 × foe level` per fainted foe, 1.5 times for a trainer's Pokemon. One growth curve
  for every species: `level³`. Showdown has no EXP data, so these rules stay simple.
- Stats use the formulas of gen 3 and later, and match Showdown's for the same IVs, EVs and
  nature.
- HP, status and PP carry over between battles. When the whole team faints, the player blacks
  out and loses half their money.
- In a wild battle, the player can throw one ball a turn for free, then still picks a move.

Left out: double battles, Terastallization, Mega Evolution, Dynamax, items in battle other than
balls, trades, breeding, eggs, shiny Pokemon and nicknames.

## Where the rules live

`src/rulehall/engines/pokemon/`: the master's instructions in `rules.md`, the numbers in
`rules.py`, the battle module in `battle/`, and the Node side in `showdown/`. The map machinery is
`RoomEngine` in `src/rulehall/engines/rooms/`.
