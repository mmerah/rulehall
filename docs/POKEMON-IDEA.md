# Pokemon ideas

This file has two parts:

1. Changes that make the current Pokemon engine more fun. **Part 1 is decided.** Three advisers (player experience, architecture and cost, AI roles) reviewed the first brainstorm in three rounds on 2026-09-27. The decisions below are what they agreed on, with the few splits settled.
2. A separate game: a Pokemon Champions roguelite. It lives in its own project, not in Rulehall. Part 2 is still open.

## Part 1: the current engine

### Why it feels flat

The first brainstorm named three causes: nothing pushes back, battles have low stakes, and progress is only numbers. The review found the causes in the code:

- **Trainers play badly.** The default `battle.opponent` setting is `random` (`config.py:80`), so a trainer picks any legal move.
- **Trainers are built badly.** `Mon.new` gives every trainer Pokemon its last four level-up moves, a random nature, no item and no EVs (`world.py:181`). A gym leader plays like a wild Pokemon with a name.
- **The master has no reason to push.** `master.md` says "your notes never decide or script" a choice. `rooms/rules.md` says the arc "never says what must come". The scope says "no ending is written". Nothing in code adds pressure instead.
- **The master gets no turn after a battle.** The narrator tells the result. The master sees it only as a card in RECENT PLAY, one player turn later, with no reason to act on it.
- **Healing is free.** `heal_team` works anywhere (`engine.py:291`), so HP and PP never matter between fights.
- **Pokemon have no personality on the page.** The narrator sees "Charmander L5, 20/20 HP". It never sees a nature, a bond, or what a Pokemon has done.

### Already done

- **Shared EXP.** A Pokemon that did not fight gets half the EXP (`TrainerSheet.exp_shares`, `world.py:441`).
- **Set mode.** Showdown singles gives no free switch after a knock-out. Only the side whose Pokemon fainted switches.

### Decision 1: foes that fight

- **The badge table.** One table in `rules.py` gives the level of the gym ace for each badge count, for example 12, 18, 24, 30, 36, 42. Four things read it: the worldsmith guidance, the level caps, the rival and the boss.
- **Key trainers.** A gym leader, an admin, the rival and the boss are key trainers. The worldsmith writes each one with species, levels, an `ace` flag, one `style` line ("sets up rain, then sweeps"), an `on_win` line and an `on_loss` line.
- **Code builds key teams.** A pure `build_set(species, level)` picks strong same-type moves and coverage from the level-up moves and the TMs, a nature, fixed EVs and a held item. The ace goes last. The worldsmith never writes moves: illegal sets would spend its one retry. Regular trainers keep `Mon.new`.
- **Gym levels are checked.** A new gym's index is the count of badge trainers already in the world plus its order in the proposal. The check refuses a gym ace more than 2 levels away from the table.
- **Fewer trainers.** The guidance asks for a few meaningful fights. A check caps the regular trainers of one region.
- **Opponent policy by trainer.** The engine writes a `policy` into `BattleSetup`:
  - a wild Pokemon: random, as now;
  - a regular trainer: greedy;
  - a key trainer: the model, when the app passes an opponent role, else greedy.
- **Greedy.** A pure function of the `Assessment` and the offered choices: a move that knocks out, else the move with the most damage, else the best switch. A test runs it on the recorded fixture.
- **The setting.** `battle.opponent` becomes `scripted | model`, default `model`. Only the app reads it: it passes the opponent role or none. A saved battle with the `model` policy falls back to greedy when no role is passed.
- **The model's persona.** The opponent prompt adds the trainer's `style` line.
- **Trainer lines.** `end_battle` adds the `on_win` or `on_loss` line as a fact from the trainer, so the narrator speaks it at the end of the battle. A `Game.note` for the master carries only what the master must act on ("Vex fled north").

### Decision 2: stakes and attachment

- **A challenge step at character creation.** The pick is stored on `TrainerSheet`. It never changes during a game. It is not a live setting, because only the app and the UI read the settings.
  - `relaxed`: the game as it is today.
  - `hard`: level caps.
  - `nuzlocke`: level caps and the Nuzlocke rules.
- **Level caps.** The cap is the table level for the player's badge count. At the cap, EXP stops, a card says so, and a Rare Candy is refused. The Team page marks a capped Pokemon. Nothing is banked, so a raised cap never floods the player with level-ups, moves and evolutions.
- **Nuzlocke.** It starts at once, since the starting bag holds five Poke Balls.
  - A Pokemon that faints goes to the memorial. If the whole team faints, the team stays and the game ends.
  - Only the first wild battle at a place with WILD HERE offers balls.
  - `start_wild_battle` refuses a chosen species: the table decides.
  - The dupes clause: the roll skips a species the player has already caught. `caught_species` on the sheet tracks it.
- **Pokemon Centers.** `PokemonMap.centers` marks the places that heal. `heal_team` works only at an open Center. An opening map without a Center is refused. The guidance puts a Center in every town.
- **Nicknames.** A Team page action. A nickname is unique on the team and in the box, because the battle view keys its tags by name. Showdown shows the nickname.
- **A record of each Pokemon.** Code writes where the Pokemon was met and its wins against key trainers.
- **YOUR POKEMON for the narrator.** It holds the nickname, the species, a nature word, a friendship band (wary, warm, devoted), where the Pokemon was met and its key wins. A MEMORIAL section adds each fallen Pokemon and who it fell to. The narrator only gets facts the player already knows.

### Decision 3: the rival

- **Written once.** The worldsmith writes the rival in the opening map: one trainer marked `rival`, with `style`, `on_win` and `on_loss`, and no roster.
- **Its starter.** A pure `counter_pick(pool, target, level)` in `rules.py` picks the starter that beats the player's. It scores the super-effective same-type moves a species learns by that level, prefers species the target does not hit hard, and breaks ties by base stat total, then by id. A test covers it offline with `dex.json`.
- **Its team.** Code builds it at battle start, on the badge table: the ace at the table level, the rest a little lower. The ace is the starter line, evolved at its levels. The rest come from the wild tables of the places the player has visited. The team grows by one per badge, up to six. It never scales to the player's strongest Pokemon, which would punish training.
- **When it appears.** After each badge, code places the rival on the player's next move into a route or town with no gym and no open operation. A note tells the master. After the battle, the rival leaves.
- **The ledger.** One line per battle: the place, the badge count and who won. The master sees it. The narrator sees it too, since each line is a told fact.

### Decision 4: the evil team

- **The team.** The worldsmith writes it once, in the opening map: a name, a goal, four stage lines, a boss, two admins, and an optional `legendary_id` from SPECIES that must carry a legendary tag.
- **Operations.** One operation is open at a time. The opening map holds the first. While the track runs and no operation is open, code tells the extension request "this region carries the next operation", and the check requires one. Otherwise the check forbids it. An operation has:
  - `place_id` in the new region, reachable without a gate;
  - `leader_id`, an admin or a grunt with a roster;
  - `goal`;
  - `consequence`: `shut_way` or `close_center`.
- **Code moves the admin** to the operation's place when the operation opens.
- **An operation ends in one of two ways.** Either way, the stage goes up by one.
  - **Foiled:** the player beats its leader. A reveal fact tells a stage line.
  - **Succeeded:** the player earns a badge while it is open, or loses to its leader. The consequence applies. A loss to a grunt costs only money, as now.
  - Badges are the player's clock: "they strike when you earn your next badge". The player can see the clock and chooses when to beat it. An operation the player never touches stays open until the next badge.
- **Consequences.** `shut_way` never shuts the way at the player's place and never cuts a place off. When it cannot apply, it closes a Center instead. `close_center` shuts the nearest open Center. Both last until the boss falls.
- **Admins learn.** When an admin loses, code adds a `counter_pick` against the player's lead to the admin's roster, up to six.
- **The Center rumour.** At an open Center, the master's section shows the open operation's place and goal as a rumour to tell.
- **The climax.** After four operations, the next region must hold the lair and the boss. The boss's ace sits at the table level plus 2 for each operation that succeeded. With three or more succeeded, the legendary joins the boss's team. The boss uses `build_set` and the model. Reaching the end of the track is not a game over.
- **The ending.** When the player beats the boss, `end_battle` gives an epilogue cue and sets `boss_beaten`. `ending()` then ends the game. A post-game can come later.
- **Who sees what.**
  - **The page**, after the player first meets the team: its name, stage n/4, a tally of foiled and succeeded operations, and the goal of the open operation.
  - **The master:** the section THE SCHEME, with the goal, the stage, the open operation (place, leader, goal), its consequence if it succeeds, the trigger line and the final-act terms so far. The master owns no lifecycle call. It voices grunts and admins and calls `start_battle`.
  - **The narrator:** only told facts. It never sees the goal, the next stage, a consequence before it applies, or the final-act terms.
- **Tern Isles.** Rewrite the scenario by hand: its Centers, a small team, one admin, the first operation near Gull Cove with `shut_way`, and the boss offstage. It is the scenario people play first, and it gives the tests a scheme with no worldsmith call.

### Pacing

Pacing lives in `rules.md` and the worldsmith guidance: a cold open, one local problem, one key fight, a hook. While the track runs, the open operation is the region's one problem. There is no `local_problem` tool: it would be a tool with no rule behind it.

### Phases

Each phase ships a game that plays end to end.

| Phase | What ships | About |
|---|---|---|
| 1. Foes that fight | The badge table, key trainers, `build_set`, policies and greedy, the setting, the persona line, trainer lines, gym level check, trainer cap | 230 lines |
| 2. Stakes and attachment | The challenge step, level caps, Nuzlocke and the memorial, Centers (and Centers in Tern Isles), nicknames, the record, YOUR POKEMON | 300 lines |
| 3. The rival | `counter_pick`, the rival, its team, placement, the ledger | 130 lines |
| 4. The evil team | The scheme, operations, consequences, admins who learn, the rumour, the page, the climax, the legendary, the ending, Tern Isles rewritten, pacing text | 320 lines |

Phase 1 comes first because every later phase ends in a fight. Phase 4 reuses the pieces of phases 1 to 3: key trainers, Centers and `counter_pick`.

### Later

- Gates by field move: a way that opens when a team Pokemon knows Cut, Surf, Strength, Rock Smash or Flash. The dex has these moves.
- A dex goal: counts of seen and caught species, and rewards from the professor.
- Auto-resolve for lopsided wild battles, with greedy on both sides.
- Speed and knock-out flags in `assess.js`. They need a new recorded fixture.
- The race for the legendary: clues, and a catch after the climax.
- A gym leader taken by the team. The idea failed review: once its operation has succeeded, nothing can free the leader.
- Double battles: the rival as an ally, tag battles, a double-battle climax. The cost is 300 lines for a lite form and 600 or more for full doubles. Do them only if the climax needs them. The Champions project does not justify them.
- A strong bond that keeps a Pokemon at 1 HP. It needs a Showdown patch.
- A post-game after the ending.

### Cut

- A countdown in visits or moves for the team. It punishes exploring.
- Movesets written by the worldsmith.
- A pack template for the evil team. Ten packs would each need their own.
- Rival scaling to the player's strongest Pokemon.
- A `local_problem` tool.
- A banked EXP pool at the level cap.

## Part 2: a Pokemon Champions roguelite

### The pitch

A fun game, played to learn the Pokemon Champions doubles format. It is not practice for real tournaments: the Champions game itself, against people, is better for that. It is a top-down 2D or 2.5D roguelite, in its own project.

### Why it is not in Rulehall

- The two games grow in opposite ways. In the journey, the player's Pokemon get stronger. In Champions, every Pokemon is level 50 and its stats are fixed at the start, so the player gets better, not the team.
- Rulehall is a tabletop game with AI roles. This game is a real-time, top-down action game.

### The Champions rules

These rules come from the 2026 season. Check them again before any build.

- Every battle is a double battle at level 50.
- Each player shows 6 Pokemon and brings 4. Team lists are open: each side sees the other's species, moves, items and abilities.
- No IVs. Each Pokemon has 66 stat points to spend, at most 32 in one stat, and one point adds one stat point at level 50.
- Mega Evolution is allowed in the M regulation sets. Regulation M-C runs from 9 September 2026 to about 1 December 2026.
- Pokemon Showdown has Champions OU, VGC and BSS formats. The Pikalytics URL suggests `gen9championsvgc2026regmc` as a format id.

### What a run could look like

- **The start.** The player drafts 6 Pokemon from a pool and sets their moves, items and stat points.
- **The map.** The player walks a top-down map of nodes: battles, a shop, a tutor, events, a rest stop. A run can dress up as one tournament season: locals, then regionals, then internationals, then worlds.
- **The battles.** Each is a double battle, bring 4 of 6, in best-of-one or best-of-three.
- **Rewards.** A new Pokemon for the pool, a Mega Stone, an item, a move tutor, a token to spend stat points again. These are side-grades, not raw power.
- **The loss.** Two losses end the run.
- **The bosses.** Each act ends with a boss who plays a real tournament team.

### Progress between runs

Still open. Roguelites usually unlock things across runs:

- new species in the draft pool
- Mega Stones
- starting stat spreads
- a notebook of the teams already met

The other choice: each run stands alone, with nothing kept.

### Real teams for the bosses

- [Limitless VGC](https://limitlessvgc.com/teams) has the top teams of big tournaments, usually as Showdown pastes. It is the main source.
- [Pikalytics top teams](https://www.pikalytics.com/topteams) collects Champions tournament teams and links each to its Limitless source.
- [Victory Road rental teams](https://victoryroad.pro/champions-replica/) is a curated archive of teams ready to copy.

A maintainer script pulls the teams into a data file. The game reads the file and needs no network. Name each team by its style and placing, not by the player who used it, and credit the source. Read each site's terms before pulling from it.

### Engineering notes

- Showdown can run the battles as a local simulator. It is MIT licensed.
- An AI opponent in doubles must choose targets and plan for two Pokemon. A damage assessment in the style of `assess.js`, covering both targets, helps any opponent, scripted or model-driven.
- The engine, the art style and the platform are open. Pokemon sprites and sound belong to Nintendo, Creatures Inc., Game Freak and The Pokemon Company, the same limits as in [docs/POKEMON.md](POKEMON.md#licence-and-attribution).

### Open questions

- Which game engine, which platform, and which art: Showdown sprites, or the project's own art?
- Is the opponent scripted, model-driven, or a mix?
- What carries over between runs?
- How long is a run?

## Sources

- [Victory Road: Champions regulations](https://victoryroad.pro/champions-regulations/)
- [Bulbapedia: regulation sets in Pokemon Champions](https://bulbapedia.bulbagarden.net/wiki/Regulation_Sets_in_Pok%C3%A9mon_Champions)
- [Pokemon Showdown: Champions formats announced](https://x.com/PokemonShowdown/status/2042810836268519697)
- [Poketooling: Pokemon Champions stat points](https://poketooling.com/info/articles/pokemon-vgc/vgc-battle-mechanics/stat-points)
- [Limitless VGC teams](https://limitlessvgc.com/teams)
- [Pikalytics top teams](https://www.pikalytics.com/topteams)
- [Victory Road rental teams](https://victoryroad.pro/champions-replica/)
