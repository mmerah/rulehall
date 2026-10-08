# Pokemon

Pokemon is one door with two modes. Journey is a Pokemon journey played as a tabletop RPG; Champions is a competitive circuit season, described under Champions mode below. This part and the rules up to Champions mode are the journey.

A Pokemon journey played as a tabletop RPG. No official Pokemon tabletop game exists, so this rule set is our own: a light d20 layer for the trainer, and the real battle rules for the fights. The master runs towns, routes, people and trainer checks on a map. When a fight starts, the fight runs in the Pokemon Showdown simulator, and the player picks moves in Showdown's battle view.

## Sources

- **Pokemon Showdown**, the simulator: <https://github.com/smogon/pokemon-showdown>. `showdown/package.json` pins `pokemon-showdown` to the tarball of commit `51ad80fa5b264a28416b0d78667519a97ba2d2ee` of its `master` branch, and its `postinstall` builds the simulator. It runs every battle and supplies the species, moves, learnsets, abilities and items of the dex.
- **Pokemon Showdown client**, the battle view: <https://github.com/smogon/pokemon-showdown-client>. The setup fetches its built battle files and styles from <https://play.pokemonshowdown.com/>.
- **PokeAPI**: <https://pokeapi.co/>. The regional dexes of the packs, EV yields, ability texts and Pokedex entries. Item icons come from <https://github.com/PokeAPI/sprites>.
- **Smogon usage statistics**: <https://www.smogon.com/stats/>. The bo3 "chaos" file of the newest Champions VGC format of the pinned Showdown, from the newest month that publishes it, gives the presets, assumed spreads, usage cards and teammate shares of `champions/data.json`.
- **Limitless VGC**: <https://play.limitlesstcg.com/>, through its public API. The top 8 decklists of the events with 64 players or more give the real teams of `champions/data.json`: every unique decklist of that format, and of the regulation before it when the decklist is legal in that format. Each team records its regulation, event, date, players and placing. No player name is stored.
- **championsroad**, MIT, the same author: the data pipeline that `export-champions` ports. The archetypes are rules of `showdown/champions-archetypes.json`: each names the mechanic of its setter, and the export derives the setter, cores and leads from the usage data. The workflow `champions-data` runs the export each month and opens a pull request. It moves the Showdown pin to `master` HEAD only when HEAD has a Champions VGC format the pin lacks; then it also runs `export-dex`, and the pull request says to play a journey and a Champions battle before merging. The repo setting "Allow GitHub Actions to create and approve pull requests" must be on. Checks do not run on a pull request that the workflow's `GITHUB_TOKEN` opens: a maintainer starts them, for example by closing and reopening the pull request.
- **Pokemon Tabletop United** (PTU), a fan-made tabletop game. The catch roll follows its rule: a d100 against a rate built from level, HP, status and evolution stage. The d20 skill checks take after PTU and its older sibling PTA, in a much lighter form.

## Licence and attribution

Rulehall is free and open source. It sells nothing, shows no ads and has no paid tier. It is a fan project in the same spirit as Pokemon Showdown itself.

Rulehall is not affiliated with, endorsed or sponsored by Nintendo, Creatures Inc., Game Freak or The Pokemon Company. Pokemon and every Pokemon name are trademarks of their owners. Rulehall's MIT licence covers Rulehall's own code only. It gives no rights to anything below that belongs to them.

| What | Where it comes from | Licence |
|---|---|---|
| The engine, the rules and the battle driver | This repo | MIT, Rulehall |
| The simulator | npm, installed at setup | MIT |
| `battle.js`, `battledata.js`, `battle-tooltips.js`, `data/graphics.js` | Fetched at setup | MIT, per file headers; move animations CC0 |
| `data/pokedex.js`, `moves.js`, `abilities.js`, `items.js` | Fetched at setup | MIT |
| `battle-sound.js`, `battle-log.css`, `data/teambuilder-tables.js`, `data/pokedex-mini*.js` | Fetched at setup, never stored in this repo or the image | No file header: the client's AGPLv3 applies. Source: <https://github.com/smogon/pokemon-showdown-client> |
| `battle.css` | Fetched at setup | GPLv2 (file header) |
| The rest of the client | Not used | AGPLv3 |
| jQuery, html-sanitizer | Fetched at setup | MIT, Apache 2.0 |
| `dex.json` | This repo, built by `export-dex` | Numbers from Showdown's MIT data. The names, the ability texts and the Pokedex entries are the owners' text, through PokeAPI |
| Presets, assumed spreads, usage cards and teammate shares in `champions/data.json` | This repo, built by `export-champions` from Smogon's usage statistics; its `source` names the format, month, cutoff and battle count | Derived numbers only. Smogon states no licence for the statistics |
| Real teams in `champions/data.json` | This repo, built by `export-champions` from Limitless decklists; each team credits its event and placing, and no player name is kept | Derived sets only. Limitless states no licence for decklists; their posters keep their rights |
| Pokemon and trainer sprites, battle backgrounds, music, cries, item icons | Fetched at setup, with the version in `showdown/assets-version`: in Docker, a new version fetches the new files on the next container start; locally, run the setup again | © Nintendo, Creatures Inc., Game Freak, The Pokemon Company |

The git repo holds no Nintendo art or sound files. It does hold game text: `dex.json` carries the English Pokedex entries and ability descriptions, game text © Nintendo/Creatures/Game Freak, through PokeAPI, and it ships in the repo and the image. The only Pokemon images in the repo are screenshots of play, in the demo video and the social card. The setup fetches the art and sound to your computer from the same public servers that the Showdown website uses. The Docker image holds none of them either: the container fetches them into its `/data` volume on its first start, and after that it runs offline.

If you hold rights to anything here and want it removed, open an issue. It comes out.

## Pack sources

Eleven packs: ten with one regional dex each, Kanto (`srd.json`), Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar, Hisui and Paldea, and the National pack. `export-packs` writes each regional pack's species list from PokeAPI's regional dex, and the National pack's list from every base species of the dex. The three starters and the prose of each pack are ours; the National pack has the Kanto starters.

On the scenario create page, extra dexes add the species of other packs to the chosen pack. The starters come from the main pack.

Only the pack's species live in the region, and a Pokemon evolves only into a species of the region's dex. A regional forme stands in for its base forme: the Alola pack has Alolan Rattata, not Rattata.

## The tools

The map tools of Tunnel Goons stay: `move`, `move_item`, `unlock_way`, `meanwhile`, `reveal`, `kill`, `join_party`, `leave_party` and `direct`. A locked way can be a Cut tree or a door the story opens. `move` also places the rival after a badge. While the rival waits at a place, `move` refuses every way but the way back; before the first move it refuses every way. `kill` and `join_party` refuse a key trainer.

- `check`: a d20 trainer check, with one team Pokemon as a helper. A success can earn an edge for the next battle here.
- `start_battle`: fight a trainer who is here, with an optional weather and terrain from the story, alone or as a tag battle beside a party member. It ends the master's turn. The rival battles once before the first badge, then once after each badge.
- `start_wild_battle`: fight a species from the wild table of this place, or a random one, with the same optional weather and terrain. In a Nuzlocke the table always decides. The Wild here panel does the same without the master: the player sees the wild table and picks a species or searches the grass, and in a Nuzlocke only the search.
- `heal_team`: heal the team and the box, only in a town, at its Pokemon Center.
- `nickname`: name a team or box Pokemon.
- `buy`, `gain_item`, `gain_money`: the bag and the wallet. `buy` works only in a town, at its mart.
- `use_item`: a potion, a revive, a Rare Candy, a stone or another evolution item.
- `swap_mon`: swap a team Pokemon with a box Pokemon.

The player also acts without the master, from the Team tab, the Wild here panel and decisions: hold an item, teach a TM, relearn a move, send a Pokemon to the box or back, set the lead, learn or forget a move, raise a skill after a badge, and pick an evolution. Learning or forgetting a move and raising a skill resolve at once, with no master or narrator turn. An evolution stays narrated.

## Our rules

- Six trainer skills, ranked 0 to 3: Athletics, Stealth, Perception, Nature, Lore, Charm. A check is d20 + 2 × rank + the helper's bonus, against DC 10, 15 or 20. Each badge gives one rank.
- The help bonus follows the helper's friendship: +2, +3 from 120, +4 from 200. Each help, won or lost, adds 3 friendship, up to 255; each level adds 5. The team chip shows both.
- A won check can earn an edge for the next battle at that place: the foe's lead asleep or paralysed, +1 Attack, Sp. Atk or Speed for the player's lead, Stealth Rock or Spikes on the foe's side, or bait (+15 to the catch rate, wild battles only, and only where a wild table exists). One edge waits at a time; a new one replaces it, the next battle there uses it, and leaving the place drops it.
- The master can set the battle's weather (rain, sun, sand, snow) and terrain (electric, grassy, misty, psychic) from the story. They last the whole battle unless a move changes them.
- Showdown's rules stay whole: code applies the conditions through one `>eval` input right after team preview, once both leads are out. So the status and the boost land on the leads, and the hazards hurt each foe that switches in later, not the foe's lead. The input rebuilds from the setup, so a battle reopened from its saved inputs replays the same.
- A gym leader has a trial, the task the challenger meets before the leader. The master plays it in the gym as checks or a scene, then the leader battles. A Pokemon's type and moves can open a way in the story, such as Cut, Surf or Strength, through a check with it as the helper.
- EXP is `20 × foe level` per foe that fainted or was caught, 1.5 times for a trainer's Pokemon, and doubled while a Pokemon's level is below the next gym's ace. Every able team Pokemon gets the full share, on the field or not; the box and fainted Pokemon get nothing, and a new catch gains nothing from its own capture. One growth curve for every species: `level³`. Showdown has no EXP data, so these rules stay simple.
- Stats use the formulas of gen 3 and later, and match Showdown's for the same IVs, EVs and nature.
- A trainer's challenge names its team and the Pokemon it leads with, as team preview shows them. The battle's end names the foes it sent out and which of them fainted.
- HP, status and PP carry over between battles. When the whole team faints outside a Nuzlocke, the player blacks out, loses half their money and heals where they stand.
- In a wild battle, the player can throw one ball a turn for free, then still picks a move.
- Double battles: the worldsmith can mark a trainer `double`, such as twins, a pair or a doubles gym, with a roster of two or more. That trainer always battles two-on-two in Showdown's Doubles Custom Game, and the player needs two Pokemon that can fight. Team preview lets the player pick both leads. The player picks one action for each active Pokemon in turn, then a target when the move needs one (a foe, or the ally); Back undoes the last pick, and the turn goes to Showdown as one joined choice once every slot has its action. A slot with nothing to do passes. The scripted opponent and the opponent role play both slots, with damage ranges to each foe. Wild battles stay one-on-one.
- Tag battles: `start_battle` with `tag` sets the first party member with a roster beside the player, against a foe with two Pokemon or more. The battle is doubles; Showdown's p1 team is the player's team then the companion's, and team preview sends the player's pick first and the companion's lead second. The player always plays the first slot and the companion the second, even when a move drags in the other's Pokemon; each switches only among their own. When none of the player's Pokemon can act, a Next turn choice lets the companion fight the turn; the companion plays the other slot through the opponent role, in its style and with its own line in the log, or picks greedily without the role. When one of them has no Pokemon left to send, Showdown fills the slot from the other's bench. Only the player's Pokemon gain EXP, carry HP and PP, and count for the blackout or the Nuzlocke; the companion's team fights fresh each battle. The prize and the key-trainer rules stay as they are.
- The badge table sets the levels: the ace of the first gym is level 12, then 18, 24, 30, 36, 42, 48 and 54. The worldsmith writes each gym leader's ace within 2 of it, at most three other trainers per map, and wild levels 8 to 3 below the ace of the next gym on the player's road (the first routes hold levels 2 to 6). The routes before each gym hold a wild species whose own type beats the gym's, so any starter can catch an answer to the leader.
- Key trainers, the gym leaders, the rival, the evil team's leaders and its boss, battle with teams code builds fresh at each battle: the roster's species and levels, the ace last with its type's booster, the others with a Sitrus Berry (held items only from the second badge), IVs of 15 plus 2 per badge (31 at most), a fitting nature, EVs of 32 per badge (252 at most) in its attack stat and Speed, and four moves picked from the level-up and TM moves. Each has a style, a line on a win and a line on a loss, which the battle's end speaks. The opponent role plays them from what a player would see: its own team in full, the foe's Pokemon, moves, abilities and items only once revealed, with damage estimates as a share of current HP, the speed order, the field and the last turns; it can say one short line in their style on a key turn, which the battle log shows; without the role, and for every other trainer, a scripted opponent picks the move that deals the most damage, a knock-out first. The opponent role stays in and attacks by default; it switches only to dodge a sure knock-out. A wild Pokemon picks at random.
- The battle screen frames Showdown's view. A header shows both trainers, and the companion in a tag battle, with each team as pips: able, fainted, or not sent out yet. Chips show the weather and the terrain; a move that changes the weather or the terrain changes its chip. A bubble shows the latest line of the foe and of the companion. Each place has a battle background: the worldsmith picks it for each new place with `battle_background_ids`, and a town without one gets a town background and any other place a route background. The music follows the foe's role: the rival, a gym leader, an evil-team leader or boss, or any other trainer; a wild battle plays the trainer track. The music plays at a lower volume than Showdown's default, under the speech. The moves are cards in their type's colour, with PP; a switch is a card with the Pokemon's HP bar; the balls and Run or Forfeit come last. In a double battle, the choices name the Pokemon they are for. Code builds the header from Showdown's state dump and the log.
- Battle lines do not survive reopening a saved battle: the log replays from the saved inputs, but the opponent's spoken lines are gone.
- The battle's end tells up to three highlights, read by code from the battle log: a knock-out and its move, a critical hit that knocked out, a win on a quarter of the HP or less, the last Pokemon standing, a catch with the first ball. The narrator may nod to one. The rival's record keeps the best one.
- The rival starts in the opening map with the starter that beats the player's. After each badge, the rival waits at the next place the player walks to and battles once, then leaves the map until the next badge; the rival's team grows from the wild Pokemon of the places the player has seen, its ace 2 levels below the next gym's. The master and the narrator read every rival battle.
- The challenge, picked at creation: Relaxed is the journey as it is; Hard caps levels at the ace level of the next gym, so EXP stops and a Rare Candy fails there; Nuzlocke keeps the caps, sends a Pokemon that faints to the memorial for good, offers balls only at the first wild battle of a place (whose roll skips species already caught, unless none would be left), and ends the journey when the whole team faints.
- The worldsmith gives each person an `avatar_id` from TRAINER LOOKS, which lists the looks in four labelled groups: classes; leaders, Elite Four and champions; evil team grunts, admins and bosses; and rivals and professors. A gym leader, Elite Four, champion, evil-team admin or boss, or rival look goes only to that very trainer; a grunt look goes to a grunt of the evil team; a professor look goes to a professor; everyone else takes a class.
- A town holds a Pokemon Center, which heals, and a mart, which sells; they are not places of their own, and the team heals and the player buys only in a town. The worldsmith lists every town in `town_place_ids`. A gym is its own place, reached from its town; a gym is not locked by default, and an operation never sits at a gym.
- The evil team: the opening map writes its scheme (a name, the boss's goal, four stages, each with a line for a foiled operation and a line for one that succeeds, and an optional legendary) and its first operation. One operation is open at a time, at a place with a leader. Beating its leader foils it. Earning a badge while it is open, or losing to its leader, makes it succeed; the map does not change. Either way a card tells the outcome and the stage line that matches it, and its leader leaves the map (an off-map place) until a later operation brings them back. The next operation is due once the player holds two more badges than when the last one opened, or two badges per operation so far, whichever comes first (at 2, 4 and 6 badges at the latest); the next region written after that carries it. A leader's roster is rescaled at each battle so that its ace sits 2 levels below the next gym's. After four operations, the next region holds the lair and the boss: the boss's ace sits 2 levels above the next gym's for each operation that succeeded, and with three successes the legendary joins as the ace. Beating the boss ends the journey. The master reads the goal, the stage lines told so far, the open operation and the final terms, and tells a rumour in a town; the worldsmith reads the stages told so far and both lines of the next one; the page shows the tally once the player meets a leader; the narrator hears only the stage lines once told.
- Legendary Pokemon: a legendary species never sits in a wild table. The worldsmith writes one as a person of a map with `legendary_id`, one of a kind in the world, never the scheme's legendary nor one already caught; it may be hidden and may roam. `start_battle` with its id battles it alone as a wild Pokemon at the table level, catchable. Caught or beaten, it leaves the map for good; after a run or a loss it stays and battles again on a later visit. It never dies and never joins the party.
- A Pokemon can carry a nickname of up to 12 letters, digits, spaces, apostrophes or hyphens, which the battle screen shows. It keeps a record: where it was met, and each key trainer it beat.

Left out: a post-game after the boss falls, the race to catch the legendary, Terastallization, Mega Evolution, Dynamax, items in battle other than balls, trades, breeding, eggs and shiny Pokemon.

## Champions mode

Champions is the second mode of the Pokemon door, beside Journey. It is a season of VGC doubles events at level 50, in the format of the pinned Showdown (`gen9championsvgc2026regmc` now; `champions/data.json` names it in `source`). Its engine id is `pokemon-champions`; the journey keeps `pokemon`, so old saves stay valid. The master narrates the circuit, the player builds six Pokemon, and every match is a one-game doubles battle in Showdown. Journey rules do not apply: no badges, gyms, EXP, wild battles, balls, Nuzlocke or evil team.

The player picks the mode on the Pokemon door and three things at creation: the roster, the starting team and the look. The map is the Tunnel Goons map machinery. Each map is the host city of one event, with its venue, and `extend_map` moves the story to the next city and event. While an event is under way, `extend_map` and the player's extend action refuse.

### The season

- Four tiers: Locals, Regionals, Internationals, Worlds. Every event is Swiss rounds, then a top cut. Every match is Bo1.
- The field is a power of two: 2 to the number of Swiss rounds.

| Tier | Swiss rounds | Field | Cut | Opens at |
|---|---|---|---|---|
| Locals | 3 | 8 | top 4 | 0 CP |
| Regionals | 4 | 16 | top 8 | 50 CP |
| Internationals | 5 | 32 | top 8 | 250 CP |
| Worlds | 6 | 64 | top 8 | 600 CP, the invite |

- A placing earns Championship Points (CP). A placing at or better than the row earns the CP, the best row that fits. No other placing earns CP.

| Tier | 1st | 2nd | 3rd to 4th | 5th to 8th |
|---|---|---|---|---|
| Locals | 50 | 40 | 25 | 0 |
| Regionals | 200 | 160 | 130 | 100 |
| Internationals | 500 | 400 | 320 | 250 |
| Worlds | 0 | 0 | 0 | 0 |

- Only the best four finishes of each tier count; the total is the sum over the tiers. A tier opens when the total reaches its number. Losing never ends the season, and events of an open tier repeat.
- Worlds earns no CP. It needs the invite, 600 CP, and the player plays it once. When its last match is done, the season is over: the game ends after a short epilogue.
- The worldsmith writes the event of each map: its tier, a name that carries the tier, the venue (a place of the map reached from the start without a lock) and the battle background. The first event is a Locals. Later events must be of a tier the player has open. The venue's matches use the event's background.
- Ranking in the Swiss rounds: wins, then the opponents' mean win rate (each opponent counts at 25% at least), then entry order. Round 1 pairs by the event's seed; later rounds pair down the ranking, each player with the next one they have not met. The cut is seeded 1 against the last, 2 against the one before. A loss in the cut places at the size of the bracket left: 8, 4 or 2. A player who misses the cut places at their Swiss rank, and code rolls out the rest of the cut. Once the cut is played, the standings rank the players by how far they went in the cut, then by their Swiss rank.
- Code rolls every match between other players: the first player wins with a chance of their strength over the sum of both. Strength is 2 for an archetype team, 3 for a top 8 team, 4 for a top 4 team, and 5 for a finalist team, a key trainer, the rival and the player.
- The Season panel shows the placing of the last event played, and the master reads every finish.

### Registration and the team

- `register_team` registers the player at the venue while the event is open and its tier is open to them. Code draws the field, pairs round 1 and locks the team. The locked team is the registered copy; every edit and `recruit` refuses until the event ends.
- A team is exactly six Pokemon, each a set: species, ability, item, up to four moves, a nature and Stat Points (SP).
- Showdown's legality for the format decides the species, abilities, moves and items. Each stat has 0 to 32 SP and a Pokemon has 66 SP at most. Any of the 25 natures is allowed.
- Stat Points take the place of EVs: the stat formula adds `2 × SP - 1` for a stat with SP, in the place of `EV / 4`. IVs are 31, friendship 255, level 50.
- Species clause: each species once, by base species, so a Mega and its base count as one. Item clause: each item once.
- A team may hold several Mega Stones. Only one Mega Evolution happens per battle.
- The team is checked at creation, on every edit and when a save loads.
- Between events the player edits the team without the master: `set_slot`, `move_slot`, `apply_preset` (a preset id such as `garchomp-a`, up to three per species from the Smogon usage), `load_template` (an archetype id or a real team id) and `save_team`. The Team page shows the six with their builds and SP; the team builder UI is not yet there.
- The roster is a creation setting. Open: every legal species is the player's. Story: the player starts with the six of the chosen archetype team and can build only with species they own. The master calls `recruit` once per event, when the story gives a species (a trade, a gift); it refuses while the team is registered, for a species already owned, and in an open roster. The next event resets it.
- The starting team is one of the nine archetype teams, picked at creation.

### The opponents

- A field team is a real team from `champions/data.json` or an archetype template. The real teams are the top 8 decklists of large Limitless events; each has a pool (top 8, top 4 or finalist) and carries its archetypes. The tier sets the pools: Locals draw archetype templates and top 8 teams; Regionals top 8; Internationals top 4 and top 8; Worlds finalist and top 4. A team the world has already used comes last in a draw, and the newest regulation comes first. The player's starting archetype counts as used from the start, and a field player never gets the team of this event's key trainers.
- Field players are named from the pack's names. Their Pokemon come from the team; a field team has a style, its archetype, and no more.
- Key trainers are players of an event the worldsmith writes, at most three per map. Each has an `archetype_id`, optionally an `ace_species_id`, a style, a win line and a lose line. Code builds the team: the newest unused real team of that archetype in the tier's pools, else the archetype template. With an ace, code swaps in one of the ace's presets for the member with the lowest teammate share, never the archetype's setter, unless the team already holds the ace's species. The worldsmith never writes a team; the map is refused when no team can be built.
- Each new game draws a fresh season seed, which shapes the rival's team and the key trainers' aces. The rival stands in the opening map. Code builds a team of six at the start from the player's six: two core Pokemon from the pool, none of a species the player has, filled from the archetype templates by teammate share. The same team enters every event the player enters. A key trainer or the rival who dies or joins is refused: the part in the season is theirs. The rival's record keeps a line for each match, with its best highlight.
- The opponent role plays every Champions match, on the key trainer's or field team's style. The scripted opponent, the same as in the journey, plays only when the role fails.
- A key trainer speaks their line after the match: the lose line when the player wins, the win line when the player loses.

### What each role sees

- The worldsmith reads SEASON (CP and the tiers allowed), ARCHETYPES (each with its setter and cores) and ACE SPECIES. It writes the event and the people, never a team or a sheet.
- The master reads SEASON with every finish, EVENT (tier, stage, round, the player's record, the standings of the top 8 and the player, and the next opponent: a key trainer by name and style, a field player as a field team), THE TEAM with full builds, OWNED in a story roster, THE RIVAL with the ledger, and the type chart. The master never sees a foe's team and never names a foe's Pokemon before the match shows them.
- The opponent role sees its own team in full and the foe's Pokemon only as the battle shows them, as in the journey. At team preview both sides show species and types.
- The narrator reads what happened: the result of the round, the highlights, the other tables, the record, and at the end the placing, the CP and the tiers it opened. The player watched the match, so the narrator does not tell it again.

### The battle

- `start_match` opens the next match at the venue. It is a doubles battle in the format of `source`, level 50, with the player's registered team against the opponent's. Showdown's Open Team Sheets rule is dropped. It ends the master's turn, and the battle screen plays the match.
- At team preview the player brings four of six: they pick four, the first two lead and the other two wait on the bench, and Back undoes a pick. The two left out sit the match out. The opponent role picks its four from the same screen, with a suggestion; the scripted pick ranks each Pokemon by its best move against each foe species and its type risk, and puts a Fake Out, Tailwind or Trick Room user among the leads.
- Mega Evolution: a Pokemon that holds its Mega Stone gets a Mega Evolve choice. It toggles, and the next move of that Pokemon goes with `mega`. Showdown offers it only while the team has not Mega Evolved, and only one Pokemon per turn may take it. The opponent role gets the same choice in its prompt, and its answer may hold one `mega`. The scripted opponent Mega Evolves as soon as it can.
- No HP or PP carries over, and no EXP, item or ball applies: every match starts fresh. A ball throw refuses.
- Win or lose, the result goes to the event: code records it, rolls the other tables, pairs the next round or seeds the cut. A loss in the Swiss rounds does not end the player's event.

Left out, and not yet: open team sheets, scouting, foe estimates that know SP, and the team builder UI.

## Where the rules live

The shared base is `src/rulehall/engines/pokemon/`: the stat, type, nature and item rules in `rules.py`, the dex in `dex.py`, the battle module in `battle/` (the driver, the choices, the opponent role, team preview and Mega), and the Node side in `showdown/`.

`src/rulehall/engines/pokemon/journey/`: the journey engine, with the master's instructions in `rules.md`, the journey numbers in `rules.py` and the packs in `packs/`.

`src/rulehall/engines/pokemon/champions/`: the Champions engine. `season.py` holds the tiers (`TIERS`), the CP rules and the event with its Swiss rounds and cut. `world.py` holds the world: registration, matches, results and recruiting. `rules.py` holds the team rules and the builders for key trainers, the rival and the field. `sheet.py` is the player's sheet and the trainer. `worldsmith.py` checks the worldsmith's event. `data.py` loads `data.json`, the legality, presets, usage and teams. `panels.py` builds the Team and Season panels, and `rules.md` is the master's instructions.

The map machinery is `RoomEngine` in `src/rulehall/engines/rooms/`.
