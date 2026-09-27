# Pokemon ideas

Nothing here is decided. This file collects ideas from one brainstorm, so that a later session can pick, cut and order them. The file has two parts:

1. Ideas to make the current Pokemon engine more fun.
2. A separate game: a Pokemon Champions roguelite. It lives in its own project, not in Rulehall.

## Part 1: the current engine

### Why it feels flat

- **Nothing pushes back.** The scope of play says the journey runs island by island with no written ending. No one works against the player, and nothing runs out of time. The rooms engine has a hidden `arc` and a `meanwhile` tool, but no rule ties them to a threat that grows.
- **Battles have low stakes.** Early fights take one button. A blackout costs half the money, and a Pokemon Center undoes everything else.
- **Progress is only numbers.** Levels and badges go up. The world does not change because of what the player did.

The ideas below each answer one of these problems. They are not in a fixed order. The brainstorm leaned toward the evil team first, then the rival, the challenge settings and double battles.

### Idea: an evil team

An evil team that grows toward a world-ending danger, with people who come back again and again. The key choice: **code tracks the team's progress, not prose.** Then the master cannot forget the plot or stall it.

- **The scheme track.** The team has one goal, such as waking a legendary, draining the sea or stopping the ferries. The goal has 4 to 6 stages.
  - The track moves forward when the player leaves an operation alone for N visits, or loses to the team.
  - It moves back when the player foils an operation.
  - Code owns the track. The master sees the current stage and the next step. The narrator sees only what the player has uncovered.
- **Operations.** A new region from the worldsmith can carry one operation: a place, a goal and a deadline counted in visits.
  - An operation the player ignores changes the world: a Pokemon Center shuts, grunts hold a route, a gym leader goes missing, someone's Pokemon is stolen.
  - `meanwhile` gets a real job here: it moves admins and grunts offscreen.
- **A recurring cast.** Grunts, two or three admins and a boss. Each is a lasting trainer who remembers the player.
- **Counter-picks.** When an admin loses, code adds a Pokemon to their roster that the type chart picks against the player's lead or strongest Pokemon. They come back having learned. The pick is deterministic, so a test can cover it offline.
- **A race for the legendary.** The team and the player chase the same legendary. The player finds clues through Lore checks and hidden facts.
- **The climax.** A final battle against the boss, possibly a double battle. Then the legendary itself, as a fight the player can win or a catch.
- **An ending.** Beating the boss ends the game, or at least the chapter.

Open questions:

- What moves the track: visits, badges, or both?
- Can the team win? If the track reaches its end, is that a game over, or a harder final act?
- Does the worldsmith write the team at the start of play, or does the pack hold a template for it?
- The brainstorm leaned toward keeping the track in the Pokemon world. Other engines could use a threat track too. By CLAUDE.md, it stays in Pokemon until a second engine needs one.

### Idea: a rival

A classic Pokemon rival.

- The rival starts with the starter that beats the player's.
- Code scales the rival's team to the level of the player's strongest Pokemon. The master does not choose it.
- The rival appears at milestones: after each badge, and before the climax.
- The rival can turn into an ally and fight beside the player against the team. That needs double battles.

### Idea: challenge settings

Settings for a player who wants stakes. The relaxed journey stays the default.

- **Nuzlocke.** A Pokemon that faints is gone for good. It goes to a memorial, and the narrator can mourn it. The player may catch only the first wild Pokemon they meet in each place, and places already have wild tables. The rules are small and all in code.
- **Level caps.** Each badge sets a cap, at the level of the next gym leader's strongest Pokemon. The player cannot grind past a fight, so gym leaders become real tests.
- **Set mode.** No free switch after the player knocks out a foe.

Open question: code applies a setting, and CLAUDE.md says only the app and the UI read the settings. So the choice probably belongs in character creation or in the new game, not in a live setting.

### Idea: double battles

Doubles makes new fights possible:

- gyms that battle in doubles
- two admins against the player
- **tag battles:** a party member's Pokemon fights beside the player's. Today's rule, "their Pokemon do not battle for the player", would change.
- the climax as a double battle

Cost: the largest on this list.

- The simulator driver, the choice buttons, the battle models and the opponent prompt all assume one active Pokemon a side.
- `assess.js` looks only at `active[0]`.
- Targeting needs its own buttons and its own opponent answer.

The separate Champions game needs the same doubles work. Doing it here first teaches the lessons once.

### Idea: less busywork

- **Auto-resolve.** A button that lets Showdown play out a lopsided wild or trainer battle for both sides, and shows only the result.
- **Fewer, stronger trainers.** The worldsmith is told that three meaningful fights on a route beat ten filler ones.
- **Shared EXP.** The whole team gets some EXP, so the player spends less time on grinding.

### Idea: exploration gated by the team

Cut already gates some ways. This idea makes the gates a rule:

- Surf to reach an island.
- Rock Smash for a cave.
- Strength for a boulder.
- Flash for a dark tunnel.

The worldsmith places gates, and a gate opens for a team Pokemon that knows the move or has the type. The Pokemon the player catches then decide where the player can go. The d20 checks with a helper get a reason to happen.

### Other approaches

- **Episode pacing.** Each session plays like an anime episode: a cold open, one local problem, one battle at the peak, a hook for next time. This is mostly guidance in the master prompt.
- **A campaign that ends.** Four islands, one evil team, one legendary, and an ending. A game the player can finish is often more fun than one that never ends.
- **A bond with Pokemon.** Friendship already exists. The narrator could show personality from nature and friendship. A high bond could matter in battle, like in the games: a Pokemon holds on at 1 HP. Showdown would need a small change for that. Keep it low on the list.

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
