# Plan: a livelier Pokemon journey

The design is decided in `docs/POKEMON-IDEA.md`, Part 1. This plan is the implementation. The Loner 4e plan it replaces is done; it stays in git history (`bf3421b`).

## Goal

Make the Pokemon engine fun without the master remembering anything. Code owns every rule, count and trigger. The master voices people and calls the tools it already has.

- **Phase 1 — Real fights and real stakes.** Strong key trainers, a scripted opponent for everyone else, a challenge chosen at creation, Centers that heal, nicknames and a record per Pokemon, and a rival.
- **Phase 2 — The evil team.** A four-stage scheme moved by badges and battles, operations that the worldsmith writes on request, a climax and an ending.

Two phases, as few as the work allows: phase 2 builds on phase 1's key trainers, Centers and `counter_pick`. Each phase ships a game that plays end to end. Phase 1 is large; `/phase 1` splits it between implementers (see "Split" in each phase).

## Words used below

- **Key trainer**: a gym leader (has a `badge`), the rival, an operation leader, or the boss.
- **The badge table**: `BADGE_LEVELS` in `rules.py`. `level_for(badges)` reads it.
- **Table level**: `level_for(len(sheet.badges))`, the ace level of the next gym.

## How to work

- Read `CLAUDE.md` first. Every rule there binds this plan.
- Run each phase with `/phase N`, in order.
- Each phase ends with the four checks green: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run basedpyright`. Then smoke `uv run rulehall` with `qa/s_pokemon.py`. Do not set `UV_CACHE_DIR`.
- Goldens: regenerate with `RULEHALL_GOLDEN_REGEN=1 uv run pytest`, then run `uv run pytest` again. The golden diff shows only the drift the phase intends.
- **Prompts match tools.** After each phase, `pokemon/rules.md`, the worldsmith guidance in `pokemon/pack.py`, every tool docstring and every `Field` description name only what exists.
- **Docs.** Each phase updates `docs/POKEMON.md` ("Our rules", "The tools", "Left out").
- **Saves have no version.** Old saves may stop loading. Update `characters/kael/pokemon.json` and `scenarios/tern-isles/world.json` by hand.
- **Tests.** One test per core behaviour that the phase lists. No tests for prose or wiring. Use the scripted stub and `tests/support/showdown.py` (`ScriptedSimulator`). Never start a process.
- **Patterns.** A tool is an engine method marked `@tool`; its docstring is model text. A rule a tool cannot honour raises `Refusal`; nothing inside `settle_battle` raises on a legal state, it falls back instead. Value models are `Frozen`, state models `Mutable`. Ids end in `_id`. A property reads one value; a method computes. Imports inside the engine flow `dex, battle/models <- rules <- world <- args <- panels <- battle/opponent, battle/simulator <- engine`. Module layout: imports, constants, classes, public functions, private functions.
- **Line count.** Measure `src` before and after each phase:
  ```bash
  find src/rulehall -name node_modules -prune -o -type f \( -name '*.py' -o -name '*.md' \) -print0 | xargs -0 cat | wc -l
  ```
  Baseline at `83ac1c3`: **17963**. Soft targets: phase 1 ≤ 18750, phase 2 ≤ 19150. Record an overshoot and its reason in `PROGRESS.md`; never cut scope for it.
- Record each phase in `PROGRESS.md`: counts, off-plan decisions, refuted review findings.

---

## Phase 1 — Real fights and real stakes

Split: part A "fights and rival" (1.1–1.5, 1.10) then part B "stakes" (1.6–1.9), sequential: both touch `world.py` and `engine.py`. 1.11 goes with part B.

### 1.1 Levels (`rules.py`)

```python
BADGE_LEVELS = (12, 18, 24, 30, 36, 42, 48, 54)
LEVEL_SPREAD = 2     # a gym ace may sit this far from its table level
ACE_BELOW_TABLE = 2  # a rival's or leader's ace sits this far below the table level
BELOW_ACE = 2        # a built team's other Pokemon sit this far below its ace
REGULAR_TRAINERS_MAX = 3

def level_for(badges: int) -> int:   # clamps to the last entry past the table
def evolved(species_id: Slug, level: int, pool: Collection[Slug]) -> Slug:
    # follows `evos` while the next species is in `pool`, has `evo_type is None`,
    # and `evo_level <= level`; the first such evo, by id
```

### 1.2 Built teams (`rules.py`, `world.py`)

- `rules.SIGNATURE_EXCLUDED: frozenset[Slug]`: moves that fail, recharge, faint the user, strike later or change type in Showdown: `hyperbeam`, `gigaimpact`, `lastresort`, `focuspunch`, `selfdestruct`, `explosion`, `futuresight`, `doomdesire`, `dreameater`, `hiddenpower`, `round`, `snore`, `fling`, `beatup`, `naturalgift`, `belch`, `synchronoise`, `steelbeam`, `mindblown`. The implementer adds any like move met while testing real sets.
- `rules.signature_moves(species: Species, level: int) -> tuple[Slug, ...]`, pure, at most 4:
  1. Candidates: level-up moves learned at or below `level`, plus machine moves with `0 < power <= 5 * level`. None in `SIGNATURE_EXCLUDED`. A damaging move has `power > 0`.
  2. Score a damaging move `power * (accuracy or 100)`, halved when its category is not the species' better attack (Physical when base Atk ≥ base SpA, else Special).
  3. Pick the best same-type damaging move, then the best damaging move of another type, then the latest-learned status level-up move, then fill with the next best damaging moves. Ties break by move id.
- `rules.TYPE_BOOSTERS: dict[str, ItemId]`: Normal → `silk-scarf`, Fire → `charcoal`, … Fairy → `fairy-feather` (all 18 exist in `ITEMS`).
- `Mon.built(species_id, level, taken, *, ace: bool) -> Mon`, a classmethod beside `Mon.new`, with no `rng`:
  - moves from `signature_moves`; the first ability; IVs all 31;
  - nature `Adamant` when base Atk ≥ base SpA, else `Modest`; EVs 252 in that attack stat and in Spe, 4 in HP;
  - gender from the species, else `M` when `male_share >= 0.5`;
  - item: the ace holds its first type's booster, the others a `sitrus-berry`.
- `start_battle` builds a key trainer's team fresh at every battle with `Mon.built`, highest level last (the ace). A key trainer never uses `trainer.team`. A regular trainer keeps `Mon.new` and `trainer.team`, as now.

### 1.3 Trainer fields and checks (`world.py`, `engine.py`, `pack.py`)

- `Trainer` gains, each with a model-read `Field` description:
  - `style: str = ""`: one line on how they battle, such as "sets up rain, then sweeps".
  - `win_line: str = ""`: what they say when they beat the player.
  - `lose_line: str = ""`: what they say when the player beats them.
  - `rival: bool = False`: the one rival of the story, in the opening map.
- `PokemonEngine._check_wild_and_species` becomes `_check_proposal(pack_id, proposal, *, gyms_before: int, opening: bool)`. It keeps its checks and adds these refusals, all inside the worldsmith's retry:
  - A key trainer with an empty `style`, `win_line` or `lose_line`.
  - A gym ace outside `level_for(index) ± LEVEL_SPREAD`. `index` is `gyms_before` plus the gym's order among the proposal's badge trainers. `gyms_before` counts badge trainers in the world (0 for the opening).
  - More than `REGULAR_TRAINERS_MAX` regular trainers in the proposal. Regular: a roster, no badge, not the rival (from phase 2, not a leader and not the boss).
  - `opening`: not exactly one `rival`. Always: a rival with a `roster` (code builds it), a rival in a region.
- `WORLDSMITH_GUIDANCE` quotes the badge table ("the first gym's ace is level 12, the second's 18, …"), asks for a few meaningful trainers, the three lines on every key trainer, and one rival in the opening map.
- `PokemonEngine` overrides `kill` and `join_party` to refuse a key trainer ("{name} has a part to play; they do not die or join you"). A dead or travelling key trainer would break the rival, the operations and the ending.

### 1.4 Opponent policy (`battle/models.py`, `battle/simulator.py`, `battle/opponent.py`, `config.py`)

- `BattleSetup` gains `policy: Literal["random", "greedy", "model"]` and `foe_style: str`. `setup_battle` fills them: wild → `random`; regular trainer → `greedy`; key trainer → `model`.
- `ShowdownRun.start` downgrades `model` to `greedy` when no opponent role is passed; it keeps `opponent` only for `model`.
- `opponent.greedy_choice(assessment: Assessment, choices: Sequence[Choice]) -> str`, pure, returns only an offered, unrefused command:
  - team preview: the first `team` choice;
  - a forced switch: the bench Pokemon whose best move has the highest low `percent`; the first offered switch when no `percent` is known (both actives fainted);
  - else a move whose low `percent` ≥ the target's `percent` (a knock-out); else the move with the highest low `percent`; else a switch to the bench Pokemon with the best low `percent`; else the first offered choice.
- `_play` runs greedy through the same assess step the model uses (`assess_line`).
- The opponent `ROLE` adds `Your style: {style}` when `foe_style` is set.
- `BattleConfig.opponent: Literal["scripted", "model"] = "model"`, with its description updated. `app/session.py` already passes the role only for `model`.

### 1.5 Trainer lines and notes (`world.py`, `engine.py`)

- After a battle against a key trainer, `settle_battle` adds `trainer.card_fact(f'{name}: "{line}"')`: `lose_line` on a win, `win_line` on a loss. The narrator speaks it at the battle's end.
- `settle_battle` returns `tuple[list[Fact], list[str]]`: facts and notes for the master. `end_battle` calls `draft.note` for each note. Phase 1 writes no note from a battle; phase 2 does.

### 1.6 The challenge (`rules.py`, `world.py`, `engine.py`, `panels.py`)

- `rules.Challenge = Literal["relaxed", "hard", "nuzlocke"]`.
- A creation step `challenge` after the starter: Relaxed ("the journey as it is"), Hard ("level caps at each gym"), Nuzlocke ("level caps; a Pokemon that faints is gone; one catch per place"). `TrainerSheet.challenge: Challenge`, required.
- `TrainerSheet.level_cap() -> int`: `LEVEL_MAX` when relaxed or past the table, else `level_for(len(badges))`.
- `Mon.gain(exp, cap) -> tuple[list[int], bool]`: the levels reached, and whether the gain was clipped. A Pokemon at or above the cap gains nothing; otherwise EXP stops at `cap ** 3`. `settle_battle` shows the EXP actually gained and writes "{name} is at the level cap (L{cap})" when a gain is clipped.
- `Mon.item_refusal(item_id, species_pool, cap)` refuses a Rare Candy at or above the cap. Its callers pass `sheet.level_cap()`.
- The Team page shows a `Cap` tag on a capped Pokemon. The master sees a `CHALLENGE` section, such as "hard: level cap 18".

### 1.7 Nuzlocke (`world.py`, `engine.py`)

- It starts at once: the starting bag holds five balls.
- `TrainerSheet.caught_species: list[Slug]` (the starter at creation, then each catch) and `memorial: list[str]`. `PokemonWorld.encounters: list[Slug]` (places of a past wild battle).
- `settle_battle`, when `nuzlocke`:
  - Every fainted team Pokemon leaves the team for the memorial, as "Blaze the Charmander, caught at Gull Cove, fell to Captain Ines". The card says "{name} has fallen".
  - A whole-team wipe moves no one (the team keeps `min_length=1`) and skips the blackout heal. `ending()` returns "Your whole team has fallen. The journey ends." when `nuzlocke` and every team Pokemon has fainted. Box Pokemon do not save the run.
- `setup_battle` for a wild battle offers balls only when the current place is not in `encounters`; it then adds the place.
- `start_wild_battle` refuses a `species_id` in Nuzlocke ("the wild table decides"). On a first encounter the roll skips species in `caught_species`, unless that empties the table (the dupes clause).

### 1.8 Pokemon Centers (`world.py`, `engine.py`)

- `PokemonMap.centers: tuple[Slug, ...]`, place ids of this map, with a description. `PokemonWorld.centers: list[Slug]` gathers them in `absorb`.
- `heal_team` refuses away from an open Center: "No open Pokemon Center here". Its docstring says so.
- The check refuses a Center that is not a place of the proposal, and an opening map without a Center. The guidance puts one Center in every town.
- The blackout still heals the team where it stands.

### 1.9 Nicknames and the record (`world.py`, `engine.py`, `args.py`, `battle/simulator.py`)

- `Mon.nickname: str = ""` and a property `Mon.name` (the nickname, else the species name). Every card that names a player's Pokemon uses `name`. Cards about the species keep `species_name` ("evolved into {species}"). `Mon.line()` for the master shows "Blaze (Charmander)".
- `Mon.battler()` sets `Battler.name` to `name`, so Showdown shows the nickname. `SideMon` reads `ident` ("p1: Blaze"); its `name` comes from `ident`, so `choices_of` keeps matching its tags. `tests/support/showdown.py::_request` adds `ident`.
- A master tool `nickname(mon_id, name)` for a team or box Pokemon: "The player names a Pokemon." The design said a Team page action, but a page option carries fixed args and has no text box, so it is a tool. It refuses a name that is not 1 to 12 letters, digits, spaces, `'` or `-`, a name another team or box Pokemon has, and a species name.
- The record: `Mon.met: str = ""` and `Mon.wins: list[str]`. `build_character` writes "your first Pokemon"; a catch writes "caught at {place} at L{level}". A key-trainer win appends the trainer's name to each team Pokemon in `result.on_field`.
- `Mon.summary()` reads "Blaze (Charmander) L12, 30/36 HP, Brave, devoted; caught at Gull Cove at L9; 3 key wins, last Captain Ines". "devoted" shows at `friendship >= FRIENDSHIP_EVOLVE`. The narrator sees it through the `sheet` rows. `Trainer.rows()` adds a `Memorial` row when it is not empty.

### 1.10 The rival (`rules.py`, `world.py`, `engine.py`)

- `rules.counter_pick(pool: Iterable[Slug], target_types: Sequence[str], level: int) -> Slug`, pure:
  - Candidates: species in `pool`, not legendary (`LEGENDARY_TAGS`), with `evo_type is None` and `(evo_level or 0) <= level`.
  - Score: the number of target types that a candidate hits super-effectively with a same-type damaging level-up move learned by `level`.
  - Ties: prefer a candidate that the target's types do not hit super-effectively; then the higher base stat total; then the id.
  - Against Charmander at level 5 it picks Squirtle (Water Gun at 3 beats Fire; Bulbasaur's Vine Whip does not).
- `PokemonWorld.rival_starter_id: Slug | None = None`. `new_game` sets it: `counter_pick` over the pack's starters less the player's, or over the pack's species when no other starter exists, against the player's starter at `STARTER_LEVEL`.
- The rival's team, built at each `start_battle` (the rival skips the "no team" refusal):
  - no badge: its starter at `STARTER_LEVEL`;
  - else the ace is `evolved(rival_starter_id, level, pack species)` at table level − `ACE_BELOW_TABLE`, and up to `min(badges, 5)` others: the distinct species of the wild tables of visited places, by base stat total (highest first) then id, each `evolved` at the ace level − `BELOW_ACE`. Fewer visited species give a smaller team.
- `PokemonWorld.rival_fought_at: int = -1`, the badge count at the last rival battle. `start_battle` refuses the rival when it equals the badge count ("{name} will battle you again after your next badge"). The prize comes with every rival win.
- After a rival battle, code moves the rival to the player's previous place (a code move) with a told fact "{name} leaves".
- Placing: a new badge sets `PokemonWorld.rival_due = True`. The engine overrides the `move` tool: after the move, when `rival_due` and the new place holds no badge trainer (from phase 2, and is not the open operation's place), code moves the rival there and makes it known. It clears `rival_due`, adds a told fact "{name} is here", and notes "Your rival {name} waits here to battle. Voice them; call `start_battle` when the player agrees."
- `PokemonWorld.rival_ledger: list[str]`, one line per battle: "{place}, {n} badges: {winner} won". The master sees `THE RIVAL` (name, style, ledger). The narrator sees the ledger as a `Rival` row: `PokemonWorld` overrides `sheet_rows`.

### 1.11 Prompts, scenario, docs

- `rules.md`: the challenge; Centers; `nickname`; key trainers ("they battle with teams code builds; voice them"); the rival ("code places the rival"); pacing: a cold open, one local problem, one key fight, a hook.
- `tern-isles`: `centers: ["pokemon-center"]`; the three lines on Captain Ines; a rival npc at the Harbour Road with the three lines and no roster; Rook stays a regular trainer.
- Kael's sheet: `challenge: "relaxed"`, `caught_species`, the starter's `met`.
- `qa/s_pokemon.py`: pick a challenge, heal at the Center, name a Pokemon, meet the rival.

### Tests (phase 1)

1. `signature_moves` gives a same-type move and a coverage move, and no excluded move, for a real species and level.
2. `greedy_choice` picks the most damage on the recorded `assessment.txt` (Tackle), and the knock-out on a copy with the target's `percent` lowered.
3. A key trainer's battle uses a built team, ace last, with the `model` policy.
4. EXP stops at the cap, and a Rare Candy is refused there.
5. Nuzlocke: a fainted Pokemon goes to the memorial; a wipe ends the game.
6. Nuzlocke: the second wild battle at a place offers no ball.
7. `heal_team` refuses away from a Center.
8. `nickname` refuses a duplicate name.
9. `counter_pick` picks Squirtle against Charmander.
10. After a badge, the next move places the rival and notes it.

---

## Phase 2 — The evil team

Split: one implementer.

### 2.1 Models (`world.py`)

```python
Consequence = Literal["shut_way", "close_center"]

class Scheme(Frozen):          # written once, in the opening map
    name: str                  # "Team Tide"
    goal: str                  # what the boss wants in the end
    stages: tuple[str, str, str, str]   # what each operation, once it ends, reveals
    legendary_id: Slug | None  # a legendary species of the pack, or None

class Operation(Frozen):
    place_id: Slug             # a place of this proposal
    leader_id: Slug            # an npc of this proposal with a roster, or an earlier leader
    goal: str                  # what the team does here
    consequence: Consequence
    shut_to_id: Slug | None    # shut_way only: the way from place_id to this place
```

- `PokemonMap` gains `operation: Operation | None = None`.
- `PokemonOpening(PokemonMap)` becomes the engine's `opening` model and adds `scheme: Scheme`. `PokemonRegion` adds `boss_id: Slug | None = None`.
- `PokemonWorld` gains `scheme: Scheme | None = None`, `operation: Operation | None = None`, `foiled: int = 0`, `succeeded: int = 0`, `leader_ids: list[Slug]`, `held_ways: list[tuple[Slug, Slug]]`, `boss_id: Slug | None = None`, `boss_beaten: bool = False`. Methods `stage()` (`foiled + succeeded`) and `owed() -> Literal["operation", "lair"] | None` (an operation when `stage() < 4` and none is open; the lair when `stage() == 4` and `boss_id` is None).
- `absorb` sets `scheme` from a `PokemonOpening`, `boss_id` from a `PokemonRegion`, and opens the proposal's `operation` with `open_operation`. It runs for the opening and for every region.

### 2.2 The worldsmith writes on request (`engine.py`, `pack.py`)

- `PokemonEngine.write_next` appends the ask for `world.owed()` to the intent:
  - `operation`: "This region carries the team's next operation: write `operation`."
  - `lair`: "This region holds the team's lair: write the boss as an npc of this region with a roster, no badge and the three key lines, and name it in `boss_id`."
- `check_next` requires `operation` exactly when owed, and `boss_id` exactly when the lair is owed. The opening check requires `scheme` and `operation`. Both check:
  - `place_id` is a place of the proposal, reachable from its start without passing a lock;
  - `leader_id` is an npc of the proposal with a roster and no badge, or an id in `leader_ids`;
  - `shut_to_id` is set exactly for `shut_way`; an unlocked way leads from `place_id` to it; and the proposal stays connected from its start without that way (it is not a bridge);
  - `legendary_id` is a species of the pack with a legendary tag;
  - leaders and the boss carry the three key lines (1.3).
- The guidance describes the scheme, operations and both consequences in a few lines.

### 2.3 Operations open and leaders rescale (`rules.py`, `world.py`)

- `PokemonWorld.open_operation(operation)`: sets `operation`. A new leader joins `leader_ids`. An earlier leader moves to `place_id` (a code move: no way needed).
- `rules.rescaled(roster, ace_level, pool) -> tuple[RosterSlot, ...]`, pure: shifts every slot by `ace_level − highest level` (floor 2) and applies `evolved` to each.
- A leader's team is built at each battle from its roster `rescaled` to table level − `ACE_BELOW_TABLE`, with `Mon.built`.

### 2.4 Operations end (`world.py`, `settle_battle`)

- **Foiled**: the player beats the operation's leader. `foiled += 1`. A told fact reveals `scheme.stages[stage() − 1]`. Note: "The team's operation at {place} is foiled."
- **Succeeded**: the player earns a badge while the operation is open, or loses to its leader. `succeeded += 1`. A told fact reveals the stage line, and the consequence applies. Note: "The team's operation at {place} succeeded: {what changed}."
- Either way `operation = None`, and the next extension asks for what is owed.
- A loss to any other trainer of the team costs money only, as now.

### 2.5 Consequences (`world.py`, `engine.py`)

- `shut_way`: when the way `place_id → shut_to_id` is still unlocked and shutting it leaves every place reachable from the current place, code locks it both ways and adds it to `held_ways`. Otherwise it falls back to `close_center`. Card: "Grunts hold the way from {A} to {B}". It never raises.
- `PokemonEngine` overrides `unlock_way` to refuse a held way ("Grunts of {team} hold this way"). A held way stays shut for the rest of the game.
- `close_center`: removes from `centers` the open Center the player visited last, else the first open Center. It never removes the last one: then the card says only "The team tried to close a Pokemon Center". Card: "The Pokemon Center at {X} has closed".

### 2.6 Leaders learn, the climax, the ending (`world.py`, `engine.py`)

- When the player beats an operation leader, code adds `counter_pick(pack species, the player's lead's types, their ace level)` to their roster, replacing the lowest non-ace slot when the roster is full.
- At each boss battle, code builds the boss's team from its roster `rescaled` to an ace at `min(table level + 2 × succeeded, LEVEL_MAX)`. With `succeeded >= 3` and a `legendary_id`, the legendary joins as the ace at that level.
- Beating the boss sets `boss_beaten`, and `end_battle` returns the cue "The boss is beaten. Tell how it ended from WHAT HAPPENED, then close the story in a short epilogue." `ending()` returns "The team is beaten. Your journey is complete." when `boss_beaten`. Losing to the boss is a normal loss.
- The rival is never placed at the open operation's place (1.10).

### 2.7 What each role sees

- **Master**: a section `THE SCHEME`: name and goal; "stage n/4, foiled f, succeeded s"; the open operation (place, leader, goal, the consequence if it succeeds); the trigger ("it succeeds when the player earns a badge or loses to its leader; it is foiled when the player beats its leader"); the final terms so far. At an open Center, a line "RUMOUR: the team is at {place}: {goal}" to tell. `rules.md`: "Voice the team. Code moves the scheme; you never do."
- **Page**: a panel named after the team once the player knows any leader: stage n/4, foiled, succeeded, the open operation's goal.
- **Narrator**: only told facts: the stage lines, the consequence cards, the leaders it meets. It never sees the goal, a stage line before it is revealed, a consequence before it applies, or the terms.

### 2.8 Scenario, prompts, docs

- `tern-isles`: unlock `harbour-road ↔ gull-cove` and add a shore path `gull-cove ↔ tern-harbour`, so the shut way is not a bridge. Add a `scheme` (a name, a goal, four stages, `legendary_id: "articuno"`), and the first `operation` at Gull Cove led by a new admin, with `shut_way` to `harbour-road`. The scope line changes: the journey ends when the team falls.
- `rules.md`, the guidance and `docs/POKEMON.md` describe the scheme.
- `qa/s_pokemon.py`: foil the first operation; trigger a success by a badge; reach the lair with the scripted worldsmith.

### Tests (phase 2)

1. Beating the operation's leader foils it: `foiled` goes up and a stage line is revealed.
2. A badge earned with the Tern Isles operation open makes it succeed, and the way is held: `unlock_way` refuses it.
3. `shut_way` falls back to `close_center` when it would cut a place off.
4. `check_next` refuses a region without the operation that is owed.
5. The boss's ace level grows with `succeeded`, and the legendary joins at three.
6. Beating the boss ends the game.

---

## Log

- 2026-09-27: Plan written from `docs/POKEMON-IDEA.md`, Part 1.
- 2026-09-27: Adversarial review folded. Rejected: splitting phase 1 into two phases (the user asked for as few phases as possible; `/phase 1` splits it between implementers instead).
