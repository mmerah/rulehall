# Plan: Loner 4e, the scenes family, and 24XX fidelity

## Goal

Move Loner 3e to Loner 4e (engine id `loner4e`). Make Loner 4e and 24XX play as their SRDs intend.

- Loner is emergent, as the SRD's first principle says: no pre-written story; the oracle discovers the world. What is established (told, a sheet or scene tag, or in Settled) stands; everything else is open to the oracle. The worldsmith writes premises, places, people and loose pressure, never secrets or planned twists.
- Code owns the Loner loop and rolls every die. The Loner master frames questions, cites tags and interprets. The worldsmith frames scenes. The player acts and asks.
- The 24XX master stays a GM who decides the world. What changes is the moment before a roll: the player commits or revises.
- This is a refactor, not a patch. No old concept survives beside its replacement. Old saves, old sheets and packs written under `packs/loner3e/` may stop loading.
- Size: about today's, shaped differently. The estimate is about +5% on `src` (15657 → ≤ 16450; +~12% on the touched areas), all of it the 4e rule surface and the 24XX commit, defence, advancement and newcomer steps. The budget is soft: never cut scope for it.

Nothing in scope is deferred. Every phase ships a game that plays end to end.

## Licence and attribution

- Loner 4e: Core Rules © 2026 Roberto Bisceglie, licensed CC BY-SA 4.0 (<http://creativecommons.org/licenses/by-sa/4.0/>).
- Source page: <https://lonersrd.zotiquestgames.com/core/loner-4e.html>. Document source: <https://github.com/zotiquestgames/lonersrd>, file `content/core/loner-4e.md`.
- ShareAlike binds our adaptations: `loner4e/rules.md`, `tables.py`, the packs. Each carries the attribution line.
- The SRD credits stay as `docs/LONER-3E.md` prints them today (Recluse Engine, Freeform Universal, 6Q System, Mythic, Risus, The Instant Game), copied into `docs/LONER-4E.md`.
- 24XX stays CC BY Jason Tocci, v1.4, <https://24xx-srd.carrd.co/>.
- Required attribution line, used in `rules.md`, `tables.py` and the docs:
  `Loner 4e: Core Rules © 2026 Roberto Bisceglie. Licensed under CC BY-SA 4.0.`

## The target play loop

### Loner 4e: who sees and decides what

| Role | Sees | Decides |
|---|---|---|
| Player | Scene title, situation, goal, detail tags, sheet, Twist Counter, Luck, Status Track, tracks, leverage, every question card (question, dice, answer, tags cited), the Living World at the end | What the protagonist does. The scene's goal when their first words set another aim. Their own oracle questions. The aim of a breather. Leverage: bank, replace, spend, arm. Press on or break away in a conflict. Whether the adventure ends and what the protagonist learned. |
| Code | Everything | Dice, luck, Twist Counter, scene phase, transition kind, conflict start and end, tag netting, track boxes, Settled, refusals, the close a twist forces. |
| Master | Everything established, the arc (loose pressure), Settled, frame, conflict, tracks, leverage, the player's question | Whether a question is needed; what is not established is the oracle's, never the master's. Its text. Which tags bear on it. What the answer means. When the goal is resolved, blocked or abandoned. The cost of withdrawing. The status tag after a defeat. When leverage stops applying. When to open a track. |
| Narrator | Told facts only: scene, goal, details, who is here, the sheet, question cards, history | Prose. |
| Worldsmith | Source, whole cast, arc, tracks, scenes so far, the transition kind, the player's last words, the ally roll, what the protagonist carries forward from earlier adventures | The next scene (place, who, goal, details, `track_id`; never `hidden`). The opposition's tag updates off screen. The Living World at the end. |

### A Loner scene, start to finish

1. **Frame.** The worldsmith writes `place_id`, `location`, `title`, `situation`, `present`, `goal`, `details` and (Challenge Tracks on) `track_id`. Code installs it with the kind it rolled. The opening is dramatic. Code refuses a scene without a goal, and a Loner scene with anything `hidden`. The narrator tells the arrival. If the player's first words set another aim, the master rewrites the goal with `drive(actor_id="scene", goal=...)` before the first question.
2. **Turn loop.** The player types an action, or types a question and presses **Ask the oracle**.
   - Action: the master reads SCENE, the sheet, the tags here, SETTLED, CONFLICT. Obvious outcome: tools, then `direct`. Uncertain: `ask(question, helps, hinders, untrained, against_id)`. Code checks each tag, nets them, rolls Chance against Risk, reads the answer, ticks the Twist Counter on doubles while no conflict is open, moves luck in a conflict, and records the answer in Settled.
   - Question: code stores the player's words. THE PLAYER ASKS shows them. The master calls `ask(question=null, ...)` and only cites tags. A non-null question is refused while the player's waits.
   - Leverage (a module, on in every game): on a Yes-and, or a No/No-and while holding, code withholds the card and pauses for the player. The option's action writes the final card, and the master interprets that final result on the option's turn. A pause that belongs to a result always withholds the card, so the master never interprets a result the player then changes, and always interprets the one that stands.
3. **Pressure.** SCENE ends with the SRD's closing test. `dead_end()` rolls the fixed question; a No adds "close as blocked". `inspire()` rolls a verb, a noun and an adjective.
4. **Close.** `close_scene(reason)`: `resolved`, `blocked`, `abandoned`, `turning_point`, `unclear`. Code rolls every die in the tool, ends an open conflict, moves the focused track, sets `frame.next` and tells "Scene closes: {reason}. Next: {kind}". The master calls it before `direct` (after `direct` no tool runs). Afterwards `ask` is refused; every other tool still works.
5. **After the turn.** `end_turn` runs on every played turn. With `frame.next` set it hands over: Dramatic → request `dramatic`; Quiet → the breather (the page swaps the send button for **Take the breather**; the player's words become the next scene's goal; a master turn then plays that aim); Meanwhile → request `meanwhile`. A failed write leaves `frame.next`; the next played turn retries with no new die. A quiet scene after a Meanwhile shows what moved off screen where it touches the aim.
6. **Conflict.** The first `ask(against_id=X)` opens a conflict and refills both sides. Each such ask is one exchange (Yes hurts X, No hurts the protagonist; 3/2/1). The master interprets each exchange and directs; one exchange per turn; the player's next words press on, change tack or break away (no code pause). A second opponent joins with its own pool. It ends at 0, on `withdraw(cost)`, when the last opponent leaves or dies, or when the scene closes. Each end refills everyone.
7. **Twist.** At 3 doubles code rolls the pair and notes the beat with the intensity line. Leverage expires. "Ends the scene": the same ask closes the scene exactly as `close_scene` would. "Changes the goal": `drive(actor_id="scene", goal=...)`. "Alters the location": `change_tags(actor_id="scene", kind="detail", ...)`.
8. **End.** `end_adventure(why)` opens one decision. A text answer confirms and says what the protagonist learned; a player who declines in words is answered by the master's `play_on`. The master writes the growth once. `end_turn` sets the `living-world` request. The worldsmith writes what became of people, places and events. Code tells it as the closing card and sets `ended`. The app writes the grown sheet back, and the sheet carries the Living World into the character's next Loner game.

### One lifecycle call

Every lifecycle step the master must remember is a step it will forget. So the master owns one lifecycle call per scene and code owns the rest.

1. The scene opens. The master did nothing: the worldsmith wrote it, code installed it, the narrator told it. SCENE shows `goal: lose the tail` and the closing test.
2. Turn 1: the player runs. The master calls `ask` and directs.
3. Turns 2-4: more asks. SETTLED lists each answer, so the master never re-asks.
4. Turn 5: the oracle says the tail is lost. The master calls `close_scene(reason="resolved")`. This is the one lifecycle call, made before `direct`. Code rolls, ends any conflict, moves the track and tells "Scene closes: resolved. Next: quiet". The narrator tells both.
5. After the turn code turns the recorded roll into the request or the breather. The master is not involved.

Zero lifecycle calls when a twist ends the scene. No offer, confirm, transition or frame call. The master never picks the next kind and never asks the worldsmith. If it forgets to close, SCENE repeats the test every turn.

### 24XX after the fixes

1. The player says what they do.
2. The master rules. Impossible: `direct`. A cost or extra steps: `direct` names it and asks; the master applies it only once the player's next words accept it (rules text). Risky: `roll(..., committed=false)`. Code validates the pool and the defences and opens a decision that shows the dice, the stakes, deadliness and the actor's hindrances: Commit, or revise in your own words. It tells no fact, so no narrator runs.
3. **Commit** rolls at once; the next master turn applies consequences. A text answer is a revision. The master passes `committed=true` itself only when the player's own words for this action name this danger and accept it ("I jump even if I fall"; never a bare "I shoot him").
   After a disaster or setback the player may break an item to turn the hit into a brief hindrance (a pause, as the SRD's defence).
4. `job find`: the result line tells the master what to do (see phase 9). The find result goes into Settled.
5. `ship_emergency`: the master names the functions in play and the skill each uses; the player picks one; the pick is the commit.
6. `test_luck` is the SRD's bad-luck test; its answer goes into Settled.
7. After a job the player picks their own skill raise. A death with no hired crew left brings in a new operator, never a game over ("favor inclusion over realism").
8. The way on, departure and complication belong to 24XX alone. **Move on** is always on the page.

## How to work

- Read `CLAUDE.md` first. Every rule there binds this plan.
- Run each phase with `/phase N`. One phase at a time, in the order below.
- Each phase ends with a game that plays end to end and the four checks green:
  `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run basedpyright`. Then smoke `uv run rulehall`. Do not set `UV_CACHE_DIR`.
- Goldens: regenerate with `RULEHALL_GOLDEN_REGEN=1 uv run pytest`, then run `uv run pytest` again (the regen run checks nothing). Read the golden diff: it must show only the drift the phase intends.
- **Prompts match tools.** In every phase `rules.md`, `master.md`, the worldsmith texts, every tool docstring and every `Field` description name only tools, sections and fields that exist after that phase. Each phase updates its own part of the prompts. A phase that changes a flow also updates the `qa/` script that drives it.
- The rules below agree with the `/phase` skill's Rules paragraph, which every brief copies:
  - **Coding principles.** Clean, SOLID, Clean Architecture, DRY, KISS, simple and readable code consistent with the codebase's patterns. Fail fast. Strict type safety. Avoid `Any`, and avoid any optional unless needed.
  - **No comments and no docstrings**, except a critical "why" (one line at most) or text a model reads (tool docstrings, `Field` descriptions). Delete comments and docstrings that the new code makes stale.
  - **Tests.** Green, and unit tests only for the minimal core behaviour: one test per new core behaviour, as each phase lists. No tests for prose, wiring, or every branch. Move or delete tests of deleted concepts; do not rewrite them for coverage. Use the scripted stub for roles. Never start a process in a test.
- **Codebase patterns to follow.**
  - A master tool is an engine method marked `@tool`; its docstring is the model text; every arg field carries a description. A player action is marked `@action`. A method may carry both (24XX `drop_item`).
  - A rule a tool cannot honour raises `Refusal` inside the tool, as `spend_luck` does with its pack flag (`loner3e/engine.py:217`). A module tool refuses the same way when its module is off.
  - A `Refusal` is the only exception a message becomes. Any other exception is a bug; do not catch it.
  - Value models subclass `Frozen`; state models subclass `Mutable`. Validate at each boundary with strict models. A worldsmith answer is checked fully inside its check (the one retry sees every need); a handler never raises on a checked answer.
  - An id field ends in `_id`. Same names for the same things.
  - A decision in flight rides in `PendingOption.args`, never in a world field.
  - Engine package layout: `engine.py`, `world.py`, `args.py`, `pack.py`, and `rules.py`, `panels.py`, `tables.py` where needed. Imports inside Loner flow `tables <- rules <- world <- args <- panels <- engine`; `pack` imports `rules` only. Across packages: `core <- engines <- app <- ui`. No cycles.
  - In Loner, worldsmith intents live in `pack.py`; notes, narrator cues, told facts and `PendingOption` constants live in `args.py`.
  - Module layout: imports, constants, classes, public functions, private functions. `__init__.py` files stay empty.
  - A property reads one value. A method builds or renders.
  - Do not add an abstraction before two things need it. Do not build for future needs.
- **Line count.** Measure `src` before and after each phase with:
  ```bash
  find src/rulehall -name node_modules -prune -o -type f \( -name '*.py' -o -name '*.md' \) -print0 | xargs -0 cat | wc -l
  ```
  Baseline at `af3f624`: **15657**. Soft targets after each phase (an overshoot is recorded in PROGRESS.md with its reason, never fixed by cutting scope):

  | After phase | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | Target (≤) | 15665 | 15715 | 15870 | 15985 | 16060 | 16090 | 16200 | 16270 | 16470 | 16450 |

- Record each phase in `PROGRESS.md`: counts before and after, decisions made off-plan, refuted review findings, anything known and accepted.

---

## Phase 1 — Core reshaping

**Goal.** Replace the way-on hook with the composer option, reshape `count_turn` into `end_turn`, and move the meanwhile clock into the rooms family. Behaviour is unchanged for every engine.

**Depends on:** nothing.

**Steps.**

1. `core/views.py` `PlayerView`: replace `way_on: DecisionOption | None` with `composer_option: PendingOption | None = None` and `composer_only: bool = False`. `composer_only` true means the option replaces the plain send.
2. `engines/args.py`: add `class Words(Frozen): words: str = Field(min_length=1)`. It is the args model of every composer action.
3. `engines/engine.py`: delete the abstract `take_way_on`. Replace `count_turn(draft)` with `def end_turn(self, draft: Game[W], /, *, acted: bool) -> None` that does nothing. Delete the `meanwhile_every` check from `__init__`.
4. `engines/entities.py` `World`: delete `meanwhile_every`, `turns_since_meanwhile`, `meanwhile_due`, `count_turn`, `clear_meanwhile`.
5. `engines/rooms/world.py` `RoomWorld`: add `meanwhile_every: ClassVar[int]`, `turns_since_meanwhile: int = Field(default=0, ge=0)`, `meanwhile_due: bool = False`, `clear_meanwhile()`, and one `count_turn()` that merges today's `World.count_turn` with today's `RoomWorld.count_turn` override (the armed turn is spent once).
6. `engines/rooms/engine.py`:
   - `__init__` raises `ValueError` when `self.world.meanwhile_every < 2` (moved from `Engine`).
   - `end_turn(draft, *, acted)`: `if acted: draft.world.count_turn()`.
   - `MORE_MAP = PendingOption(id=EXTEND, name="More map", brief="The map runs out here: say where you push on.", action_name="extend")`.
   - `take_way_on` becomes `@action def extend(self, draft, args: Words, _rng) -> list[Fact]`: refuse while `frontier()` is non-zero; set `WorldsmithRequest(kind=EXTEND, detail=args.words)`; return `[]`.
   - Rename the request handler `extend` to `write_region` (an action and a handler cannot share a name).
   - `player_view`: `composer_option=MORE_MAP if world.frontier() == 0 else None`.
7. `engines/scenes/engine.py`:
   - `MOVE_ON = PendingOption(id="move-on", name="Move on", brief="Keep playing, or say where you go and move on.", action_name="move_on")`.
   - `take_way_on` becomes `@action def move_on(self, draft, args: Words, _rng) -> list[Fact]`: refuse unless `scene.way_offered`; `draft.note(MOVING_ON)`; return `[]`.
   - `player_view`: `composer_option=MOVE_ON if world.scene.way_offered else None`.
   - `render_next`: drop the `meanwhile_due` branch. `install`: drop `world.clear_meanwhile()`.
   - `scenes/world.py`: delete `meanwhile_every = 6`. `scenes/worldsmith.py`: delete `MEANWHILE_NUDGE`.
8. `engines/twentyfourxx/pack.py` `WORLDSMITH_GUIDANCE`: add "People the player left behind move on without them." (the one idea of the deleted nudge).
9. `app/session.py`: `take_way_on` becomes `async def use_composer_option(self, option: PendingOption, words: str) -> None`:
   - first `self._require_free()` (no composer option runs while a decision waits);
   - refuse with "the page changed; try again" unless `option == self.player_view().composer_option`;
   - run `self.engine.play_option(draft, option.model_copy(update={"args": {**option.args, "words": words}}), self.rng)`; a composer action changes state only and returns no facts;
   - then as `take_way_on` does today: a set `draft.request` is saved, written (`intent = words`), and a turn with the words follows when it grew; otherwise the turn opens at once on the draft.
10. `app/turn.py` `Turn.finish`: `if self.played: self.engine.end_turn(self.draft, acted=bool(self.facts))`.
11. `ui/game.py` and `ui/theme.css`: the way-on banner becomes the composer banner. Rename `way_on`/`way_on_button`/`take_way_on` to `composer_banner`/`composer_button`/`use_composer_option`; the banner label `"way on"` becomes `"next"`; the CSS class `game-way-on` becomes `game-composer-option`. The banner shows `composer_option.name` on the button and `brief` as text, with the fixed icon `sym_r_explore`. With `composer_only` the send button is hidden and `submit` (Enter included) sends through `session.use_composer_option`. The snapshot compares `composer_option` and `composer_only`.
12. `qa/s_loner.py`, `qa/s_mobile.py`, `qa/s_requests.py`: the banner label and the renamed session call.

**Prompts.** Only the 24XX guidance line. No tool name changes.

**Tests.**
- Update call sites: `tests/support/table.py` (`play_turn(way_on=...)` becomes `composer=` taking the option), `tests/tunnelgoons/*`, `tests/twentyfourxx/test_play.py`, `tests/app/test_master_tools.py`, `tests/engines/test_scenes.py`, `tests/ui/test_game.py`.
- New, one each: a stale composer option is refused (`tests/app/test_game_service.py`); `end_turn` runs on a played turn with no facts (`tests/app/test_turn.py`, stub engine); the rooms clock counts only when `acted` (`tests/engines/test_rooms.py`).
- Regenerate goldens.

**Done when.** No `way_on`, `take_way_on`, `count_turn` or `meanwhile` symbol remains outside `engines/rooms/` and its engines, except `SceneWorld.offer_way_on` and `Scene.way_offered` (deleted in phase 3). Tunnel Goons "More map" and 24XX/Loner "Move on" play as before. Four checks green. `src` ≤ 15665.

---

## Phase 2 — Straight move to `loner4e`

**Goal.** Rename the engine to Loner 4e and take the 4e wording. Behaviour otherwise unchanged. Old `loner3e` saves, sheets and written packs stop loading.

**Depends on:** phase 1.

**Steps.**

1. `git mv src/rulehall/engines/loner3e src/rulehall/engines/loner4e`. Rename every `Loner3e*` symbol to `Loner4e*`. `id = EngineId("loner4e")`, `title = "LONER 4E"`. Update `engines/registry.py`.
2. `git mv characters/kael/loner3e.json characters/kael/loner4e.json`; set `engine_id`; empty `goal` and `motive` (4e: they emerge from play). `scenarios/whispering-vault/world.json`: `engine_id: loner4e`.
3. Rename every remaining reference: `README.md` (Loner 4e line, the notes link, the attribution line), `qa/*.py`, `tests/` (move `tests/loner3e/` to `tests/loner4e/`; golden fixture dirs `tests/core/fixtures/{prompts,schemas}/loner3e` and `turn/loner3e.json` to `loner4e`; `tests/support/{game,table,golden_turn}.py`).
4. New `engines/loner4e/tables.py`: the attribution line, then `TWIST_SUBJECTS` and `TWIST_ACTIONS` (Appendix A), each `tuple[str, ...]` of six. Constants `ENDS_THE_SCENE = "Ends the scene"`, `CHANGES_THE_GOAL = "Changes the goal"`, `ALTERS_THE_LOCATION = "Alters the location"` name the three action entries code keys on.
5. Delete `twist_subjects`, `twist_actions` and `_twist_columns_pair_up` from `Loner4ePack`; delete both keys from `packs/srd.json` and the twelve AP packs (all `null` today). The engine builds `self.twists` from `tables.py`; delete the SRD-column check in `__init__`. `tables.py` is the only twist table, because code keys on the action wording (phases 3-4).
6. `packs/srd.json`: `source` and `license` name the 4e page and "Twist table from the Loner 4e SRD, CC BY-SA 4.0 © 2026 Roberto Bisceglie".
7. `core/creation.py`: `CreationStep.optional: bool = False`. `check_picks` accepts a blank answer for an optional step. `loner4e/engine.py`: the `goal` and `motive` steps set `optional=True` and `hint="Leave empty to let play decide"` (the create page already shows `hint` as the placeholder).
8. `loner4e/rules.md`: title `# LONER 4E RULES` and the 4e attribution line. The twist paragraph says "The Protagonist".
9. `git mv docs/LONER-3E.md docs/LONER-4E.md`. Rewrite its sources and licence for 4e (section "Licence and attribution" above). Keep the deviations that still hold (twist inside the question; one counter; starter tables are ours; the party; trait labels) and drop "counter hidden". The full list is written in phase 10.

**Prompts.** `rules.md` header and twist wording. `pack.py` guidance: "LONER 4E AUTHORING".

**Tests.** Rename only. New, one: an optional creation step accepts a blank answer (`tests/core/test_creation.py`). Regenerate goldens.

**Done when.** `git grep -i -e loner3e -e "loner 3e" -e LONER-3E -- ':!PLAN.md' ':!PROGRESS.md'` finds nothing. A new Loner 4e game with Kael plays. Four checks green. `src` ≤ 15715.

---

## Phase 3 — The scene loop and the family split

**Goal.** Loner scenes get a goal, detail tags and a code-owned lifecycle: `close_scene`, the rolled transition, the dramatic request, the breather and the turning point. In the same phase the scenes family sheds everything place-based and every authored-secret rule to 24XX, `way_offered` dies, and Loner turns emergent: no `hidden`, no `reveal`, no surprise from the worldsmith. Loner keeps `roll` for one more phase.

**Depends on:** phase 2.

**Steps — the family (`engines/scenes/`).**

1. `world.py`: delete `Scene.way_offered`, `WAY_OFFERED`, `offer_way_on`. Rename the free function `settled()` to `built_scene()`.
2. `worldsmith.py`:
   - `OPENING` drops "A scene ends when the player leaves the place, so a place farther on belongs to a later scene."
   - `check_opening(proposal, *, read: str)` and `check_next(proposal, world, *, read: str, needs: Sequence[str] = ())`: the leak scan reads `title`, `situation` (and `recap` for next) plus `read`; `needs` are the caller's own needs, gathered with the rest so the one retry sees them all. Delete `moving` and its location rule.
   - Move `CROSSING`, `COMPLICATING`, `TURNING` to `twentyfourxx/pack.py`.
3. `args.py` keeps `Enter`, `Leave`. Move `NextScene`, `MOVING_ON`, `SCENE_LEFT` to `twentyfourxx/args.py`.
4. `engine.py` `SceneEngine`:
   - delete `next_scene`, `move_on`, `depart`, `complicate`, `request_handlers`, `MOVE_ON`, `DEPARTURE`, `COMPLICATION`, `WAY_UNWRITTEN`, `COMPLICATION_UNWRITTEN` (they move to 24XX);
   - add the hook `def composer(self, state: Game[W]) -> tuple[PendingOption | None, bool]` returning `(None, False)`; `player_view` fills `composer_option` and `composer_only` from it, and shows no composer option while `state.pending` is set;
   - add the hook `def scene_text(self, state: Game[W]) -> str` (today's SCENE body); `master_sections` uses it, and shows `HIDDEN HERE` through `section_if` (empty in Loner);
   - `new_game` calls `check_opening(proposal, read=self.opening_read(proposal))`, a hook returning `""` (Loner returns goal and details);
   - `render_next(draft, intent, answer_model: type[BaseModel]) -> Prompt` and `async def write_next[P: BaseModel](self, draft, intent: str, worldsmith: RoleAnswer, answer_model: type[P], check: Callable[[P], None]) -> P`: generic over the answer, so Loner's meanwhile answer reuses it;
   - `install(draft, proposal: NextProposal[C], *, card: str) -> list[Fact]`: the told card is the caller's.
5. `rules.md`: keep "The arc" and "The party". Move "The way on" to `twentyfourxx/rules.md`.
5a. `engines/engine.py`: the `reveal` tool leaves `Engine` for a mixin `class Revealing` (in `engines/engine.py`, beside `Engine`) that `RoomEngine` and `TwentyFourXXEngine` inherit, as `Joining` and `Hiring` are mixed in. Loner has nothing hidden, so it publishes no `reveal`. `rooms/rules.md` and `twentyfourxx/rules.md` keep their `reveal` lines and gain "Call `reveal` before you tell a hidden thing."; the `Engine.direct` docstring drops "Use reveal first for hidden entities."
6. `worldsmith.md` becomes the neutral shared text: the first paragraph is "You are the WORLDSMITH of a tabletop roleplaying game. You write the next scene the player walks into." Delete, and move to 24XX guidance (step 7): the "WHAT COMES NEXT holds the player's own words…" paragraph; "A complication changes that place. Keep what the brief does not move."; the `hidden` paragraph ("Put something in `hidden` when…" through "…ties one hidden thing to another. The player never reads `arc`.", keeping only "The player never reads `arc`." in the arc paragraph); and "Surprise the player. Turn an established fact against the player…". `OPENING` says "List under `present` only who is here now" (no `hidden`). The rest (placement and ids, `situation`, `location`, `arc`, SCENES SO FAR outranks the arc, the source) stays shared. Each engine's own worldsmith text is its `WORLDSMITH_GUIDANCE` plus its intents.

**Steps — 24XX takes the place-based scene (`engines/twentyfourxx/`).**

7. `pack.py`: `CROSSING`, `COMPLICATING`, `TURNING`; `WORLDSMITH_GUIDANCE` gains the moved `hidden` paragraph and the "Surprise the player" paragraph word for word, and "A scene is one place. A scene ends when the player leaves the place.", "WHAT COMES NEXT holds the player's own words about where they go and what they are after. Build the scene the player asked for. Give the player what they went to look for, or the reason they cannot have it." and "A complication changes that place. Keep what the brief does not move."
8. `args.py`: `NextScene`, `SCENE_LEFT`, `WAY_OFFERED = Fact(told=True, trace=...)` (today's text), and `MOVING_ON` reworded: "The player moves on. PLAYER ACTION says where the player means to go. Play the leaving if nothing stops the player. Then call `next_scene` with `pursuit` in the player's own words. The worldsmith writes the crossing after this turn."
9. `engine.py`: `DEPARTURE`, `COMPLICATION`, `WAY_UNWRITTEN`, `COMPLICATION_UNWRITTEN`, `MOVE_ON = PendingOption(id="move-on", name="Move on", brief="Say where you go and move on.", action_name="move_on")`.
   - `@tool next_scene` with today's three modes; nothing set returns `[WAY_OFFERED]` only (no flag, no refusal).
   - `@action move_on(draft, args: Words, _rng)`: `draft.note(MOVING_ON)`; returns `[]`. `composer()` returns `(MOVE_ON, False)`.
   - `request_handlers`: `{**super().request_handlers(), DEPARTURE: ..., COMPLICATION: ...}` (hire stays from `Hiring`).
   - `depart` and `complicate` as today, calling `write_next(draft, intent, worldsmith, self.next_proposal, check)`. The complication check passes `needs=["no new `location`: a complication happens where the player is; leave it empty"]` when `proposal.location not in ("", world.scene.location)`.
   - `install(..., card=f"New scene: {proposal.title}")`.
10. `twentyfourxx/rules.md`: "## The way on" from the family text, edited: `next_scene` with nothing set tells the narrator to ask where next; **Move on** is always on the page.
11. `docs/24XX.md`: `next_scene` lives in 24XX; drop "the scene's `offered` flag".

**Steps — Loner 4e.**

12. `loner4e/rules.py`: add
    ```python
    SCENE_ID = "scene"
    CLOSING_TEST = "Close when the goal is resolved, blocked or abandoned; when unreadable, close_scene(unclear)."
    RUN_ITS_COURSE = "Has this scene run its course?"
    type SceneKind = Literal["dramatic", "quiet"]
    type Transition = Literal["dramatic", "quiet", "meanwhile"]
    type CloseReason = Literal["resolved", "blocked", "abandoned", "turning_point", "unclear"]
    type ClosedBy = CloseReason | Literal["twist"]
    def transition_for(face: int) -> Transition   # 1-3 dramatic, 4-5 quiet, 6 meanwhile
    ```
    `TagKind` stays entity-only (`detail` is not a `TagKind`).
13. `loner4e/world.py`:
    ```python
    class Framing(Frozen):
        goal: str = Field(min_length=1, description=...)        # what the protagonist is here for, one line
        details: tuple[ShortName, ...] = Field(min_length=1, max_length=4, description=...)  # "two to four tags on the place"
    class Loner4eOpening(Framing, SceneProposal[Loner4eEntity]): ...
    class Loner4eNext(Framing, NextProposal[Loner4eEntity]): ...
    type Handover = tuple[()] | tuple[SceneKind] | tuple[Literal["meanwhile"], SceneKind]
    class Frame(Mutable):
        kind: SceneKind = "dramatic"
        goal: str = ""
        details: list[str] = []
        next: Handover = ()
        closed_by: ClosedBy | None = None
        # properties: open (next == ()), breather (next == ("quiet",)), closing (next and not breather),
        #             coming -> SceneKind: narrow with `match self.next`: () → "dramatic"; (*_, kind) → kind
    ```
    `Loner4eWorld.frame: Frame = Field(default_factory=Frame)`. The world validator refuses a cast id equal to `SCENE_ID` and a scene with anything in `here` that is unmet (Loner scenes hold nothing hidden). `absorb(proposal)` replaces the frame from a `Framing` proposal with `kind = frame.coming`. `close(reason: ClosedBy, rng) -> list[Fact]`: roll the transition (`turning_point`: `("dramatic",)`, no die), set `next` and `closed_by`, return the dice fact and the told card `"Scene closes: {reason}. Next: {kind}"`. Until phase 5, `close` reads a 6 as dramatic. The kind of the next scene is derived from `next`, so no install takes a kind argument. `details` takes 1..4 because a refused answer costs the worldsmith's one retry; the description asks for two to four.
14. `loner4e/args.py`:
    - `CloseScene(reason: CloseReason)` with a `Field` description listing the five reasons.
    - `ChangeTags.actor_id` and `Drive.actor_id` accept `SCENE_ID` (description: "Exact id of the player or a character here, or `scene`"). `ChangeTags.kind: TagKind | Literal["detail"]`: `change_tags` on the scene takes `detail` only and edits `frame.details`; `detail` on an entity is refused. `drive` on the scene takes `goal` only and edits `frame.goal`.
    - `TAKE_BREATHER = PendingOption(id="breather", name="Take the breather", brief="Say what you do with this quiet window.", action_name="take_breather")`.
    - `SCENE_UNWRITTEN = Fact(told=True, trace="the next scene could not be written", card="The next scene could not be written. You are still where you were.")`.
    - `ARRIVING = "The player arrives in the place in SCENE. The player's last words: \"{words}\". Tell the arrival and end on what presses. The player has not acted here, so settle nothing."` (a narrator cue).
    - `ARRIVING_QUIET = "The protagonist has just arrived in SCENE to pursue their aim. Direct the arrival with your first result."` (a note for the master).
15. `loner4e/engine.py`:
    - `opening = Loner4eOpening`, `next_proposal = Loner4eNext`; `opening_read` returns goal and details.
    - Every Loner scene check (opening, dramatic, quiet, and phase 5's meanwhile scene) adds the need "an empty `hidden`: in Loner the oracle discovers what is here; put who may turn up in `cast` unmet, and bring them in with `present` later" when `hidden` is non-empty. One private helper `_loner_needs(proposal, world) -> list[str]` holds this and the `SCENE_ID` need.
    - `@tool close_scene(draft, args: CloseScene, rng)`, docstring: "Close the scene: its goal is resolved, blocked or abandoned; `turning_point` in a quiet scene; `unclear` asks the oracle. Call it before `direct`. The engine opens what comes next." Refuse unless `frame.open`; `turning_point` only when `frame.kind == "quiet"`. `unclear` rolls `RUN_ITS_COURSE` (neutral Chance vs Risk); any Yes closes, a No returns the dice and "the scene runs on" and keeps it open. Then `world.close(args.reason, rng)`.
    - `end_turn(draft, *, acted)`, one order for every phase: (1) `if draft.pending is not None or draft.request is not None: return`; (2) the ending (phase 8); (3) `frame.closing` → `WorldsmithRequest(kind="dramatic", detail=frame.closed_by)`. The breather needs no request.
    - `@action take_breather(draft, args: Words, _rng)`: refuse unless `frame.breather`; set `WorldsmithRequest(kind="quiet", detail=args.words)`; return `[]`. `composer()` returns `(TAKE_BREATHER, True)` in the breather, else `(None, False)` (phase 6 adds the oracle).
    - `request_handlers`: `dramatic` and `quiet`, each `RequestHandler(handler, SCENE_UNWRITTEN)`. Each writes a `Loner4eNext`; the check is `check_next(proposal, world, read=goal + details, needs=_loner_needs(proposal, world))`; install with card `f"New scene: {title}"`. `dramatic` returns the cue `ARRIVING` with the player's last words (`draft.exchanges()[-1].words`, as `depart` does today). `quiet` refills the player's luck, notes `ARRIVING_QUIET`, and returns cue `None`.
    - Intents in `pack.py`: `DRAMATIC = "The scene closed ({reason}). The player's last words: \"{words}\". DRAMATIC: open on what is pressing. Something external has moved; the protagonist responds. Place it where the player was heading when the fiction allows. Write `goal` and two to four `details`."` and `QUIET = "QUIET: the protagonist has initiative and the world is receptive. Their aim: \"{aim}\". Write the place and the people for it. `goal` is that aim in one line. Settle nothing: the oracle answers whether it works."` The opening intent (family `OPENING` + Loner guidance) asks for `goal` and `details` and says: "A blank goal or motive on the sheet is fine: let the first scenes offer them."
    - `scene_text`: title, `[kind]`, location, situation, `goal`, `details`, the phase (`open` / `closing: next {kind}` / `breather`), and `CLOSING_TEST`.
    - `narrator_view`: `situation = f"{situation}\n\nWhat {name} is here for: {goal}. The place: {', '.join(details)}. Add no one and nothing beyond this, the cards and the notes: the oracle decides what else is here."`.
    - The `@tool roll` stays as it is this phase.
16. `app/session.py` `_land`: with no narrator cue and some facts, record the facts as an exchange with no lines (`engine.record(draft, (), resolution.facts, words=words, cause=cause)`); with no facts, accept as today. The quiet card then reaches the transcript without a narration.
17. New `loner4e/panels.py`: `scene_panel(world) -> Panel` (kind, goal, details) and `sheet_panel(world) -> Panel` (today's character rows). `scene_panels` uses them.
18. `scenarios/whispering-vault/world.json`: the opening gains `goal` and `details`; `hidden` is emptied and the `vault-map` cast entry and `icons/vault_map.jpg` are deleted (whether a map lies under the flagstone is the oracle's; a found map is a scene `detail`). The unmet `tomas`, `elena` and `cloister-rat` stay as the web of connections the worldsmith may bring in. `arc` stays empty or holds only pressure.
19. `loner4e/rules.md`: delete everything about `next_scene` and `reveal`; add "## Scene": "The goal is in SCENE. If the player's first words set another aim, rewrite it with `drive(actor_id: scene, goal)` before the first question; after that a new pursuit closes the scene as `abandoned`. Call `close_scene` when the goal is resolved, blocked or abandoned; `turning_point` in a quiet scene; `unclear` when you cannot tell. Call it before `direct`: after `direct` no tool runs. Nothing else about scenes: the engine and the worldsmith open the next one." Add one line on `change_tags` with `actor_id: scene`. The goal rewrite is rules text, no code gate.
20. `loner4e/pack.py` `WORLDSMITH_GUIDANCE` is Loner's own worldsmith text. It adds `goal` and `details` ("a place's tags go in `details`, never in a character's tags"; never file a cast entry under `scene`) and the emergent paragraph: "Loner has no pre-written story: the oracle discovers the world. Leave open what the oracle can answer. Write places, people, their tags and what they want, never a secret answer. Leave `hidden` empty. Write in `arc` loose pressure only: what the opposition wants and the open threads, never a plot or a planned twist. A cast entry the player has not met is someone who may turn up, not a secret. Surprise comes from the oracle, the twists and the transitions, not from you." The opening intent says the same for a scenario written from a prompt.
21. `qa/s_loner.py`: the way-on and `next_scene` flow becomes `close_scene` and the breather; `qa/s_24xx.py`: Move on is always shown.

**Tests.**
- Move the way-on, departure, complication and location tests from `tests/engines/test_scenes.py` and `test_scene_bar.py` to `tests/twentyfourxx/`; delete the way-offered-once tests.
- New (`tests/loner4e/test_scene_loop.py`), one each: a Loner scene with `hidden` is refused; `transition_for`; `close_scene` refused when not open and `turning_point` refused outside quiet (one parametrized test); `close_scene` then `direct` in one turn both land; `end_turn` sets the `dramatic` request and the handler installs the goal; `end_turn` sets nothing while a decision waits; the breather's write installs a quiet scene with full luck and its card is recorded; a failed write keeps `frame.next` and the next played turn sets the request again with no new die; the leak scan refuses an unmet name in `goal`, for the opening and for a next scene.
- Regenerate goldens.

**Done when.** Loner publishes no `reveal` and its scenes hold nothing hidden. A Loner game opens on a goal, closes on `close_scene`, rolls the transition and opens the next scene or the breather. 24XX plays as before with Move on always shown. The family holds no place-based rule. Four checks green. `src` ≤ 15870.

---

## Phase 4 — The oracle and conflicts

**Goal.** `ask` replaces `roll`: protagonist-only questions, cited tags netted by code, Settled, the closing test, `inspire`, `dead_end`, code-owned conflicts, `withdraw`, groups, the twist close and the counter shown. `master.md` stops giving dice rules that contradict Loner.

**Depends on:** phase 3.

**Steps.**

1. `engines/scenes/world.py`: `class Settled(Frozen): question: str; answer: str; outcome_id: str = ""; kind: Literal["action", "fixed"]; banked: bool = False`. `Scene.settled: list[Settled] = []`. `SceneWorld.settle(question, answer, *, outcome_id="", kind) -> Settled` appends to the current scene. `settled_lines() -> str` numbers the last twelve. `SceneEngine.master_sections` adds `SETTLED THIS SCENE` when non-empty. `fixed` entries are code's own questions (run its course, dead end, the ally question); `banked` marks a Yes-and banked as leverage (phase 7).
2. `loner4e/tables.py`: `INSPIRATION_VERBS`, `INSPIRATION_ADJECTIVES`, `INSPIRATION_NOUNS` as `tuple[tuple[str, ...], ...]`, six rows of six (Appendix A).
3. `loner4e/rules.py`:
   ```python
   LUCK_MAX = 6
   GROUP_LUCK_MAX = 10
   DEAD_END_QUESTION = "Does something or someone point toward a new way forward?"
   type Position = Literal["advantage", "neutral", "disadvantage"]   # moved from args.py
   class RollOutcome(Frozen): id; harm; is_yes (property); as_no_but() -> RollOutcome
   def position_for(helps: int, hinders: int) -> Position        # sign(helps - hinders), one die at most
   def faces_for(position: Position) -> tuple[tuple[int, ...], tuple[int, ...]]   # today's Roll.faces
   ```
   `outcome_for` unchanged (tie is yes-but and skips step 2). `TagKind` gains `"relationship"`.
4. `loner4e/world.py`:
   - `Loner4eEntity`: add `group: bool = False`; a validator: `luck.maximum == LUCK_MAX` unless `group`, then `LUCK_MAX <= maximum <= GROUP_LUCK_MAX`. Delete `defeated`, `run_out_of_luck`, `recover`, and the `defeated` row, `required` clause and `spend_luck` check. `relationship` joins the rows. `change_tags` refuses `relationship` on the player.
   - `Loner4eWorld`: `opponent_ids: list[Slug] = []`. Methods: `find_tag(text) -> bool` (case-insensitive exact match on the player's tags, every tag of a known entity here, `frame.details`); `start_conflict(opponent)` (refill the player and the opponent); `join_conflict(opponent)` (refill the opponent); `strike(opponent, outcome) -> tuple[list[Fact], Slug | None]` (Yes hurts the opponent, No hurts the player, by `harm`; returns who hit 0); `end_conflict(why) -> list[Fact]` (refill the player and every opponent, clear `opponent_ids`). An opponent at 0 while others remain leaves the conflict, refills at once and gets the `DEFEATED` note. `close` ends an open conflict first. Overrides of `leave`, `kill`, `leave_party` drop the entity from `opponent_ids` and end the conflict when none is left.
5. `loner4e/args.py`: delete `Roll`, `RestoreLuck`, `DEFEAT_NOTE`, `Position`. Add
   ```python
   class Ask(Frozen):
       question: Told = Field(min_length=1)  # "One closed question; yes is what the protagonist hopes. Never name someone the player has not met."
       helps: tuple[str, ...] = ()     # "Exact tags that bear on this moment and help: on the player, anyone here, or the scene. A frailty can help. An opponent's frailty can help."
       hinders: tuple[str, ...] = ()   # "Exact tags that bear on this moment and hinder."
       untrained: bool = False         # "The task needs expertise the protagonist lacks."
       against_id: Slug | None = None  # "Exact id of an opponent here for a Harm & Luck exchange. Null for one question or one key action."
   class Withdraw(Frozen): cost: Told   # min_length=1: "What breaking away costs the protagonist; apply it with a tool."
   ```
   Notes: `TWIST_NOTE` (the pair, then "Read the room, then the table: if SETTLED and the sheet show pressure, land it hard; if the scene has been clean, it is a shift." then one line for the action: Ends the scene → "The scene is closing: develop the twist and direct."; Changes the goal → "Call `drive` with `actor_id: scene` and the new goal."; Alters the location → "Call `change_tags` with `actor_id: scene` and kind `detail`."). `DEFEATED = "{name} is out of luck and lost the conflict. Tell how it ends: captured, hurt, driven off, cornered or conceding. Defeat is not death."`
6. `loner4e/engine.py`:
   - Delete `roll`, `restore_luck`, `_oracle_line`.
   - `@tool ask`, docstring: "One closed question for the oracle, yes being what the protagonist hopes; cite the tags that bear on it, and the engine nets them, rolls and reads the answer; `against_id` makes it a Harm & Luck exchange." In order: refuse unless `frame.open`; `against_id` through `require_living_here` (refuses the unmet), and refuse the player; refuse a cited tag that `find_tag` misses, and a tag cited twice across `helps` and `hinders`. Position = `position_for(len(helps), len(hinders) + untrained)`. With `against_id` start or join first. Roll Chance and Risk (`highlight_kept`). While no conflict is open, tick the twist on doubles (the SRD: the counter does not apply during Harm & Luck conflicts). Settle kind `action`. Then `self._exchange(draft, outcome, against_id)` (a private helper phase 7 reuses): strike; at the protagonist's or the last opponent's 0 end the conflict and note `DEFEATED`; else the trace says "{name} is still in it: direct; the player's next words press on, change tack or break away". No decision opens: the master interprets every exchange. Facts: chance, risk, the told card `"{question}\n{answer}\ntags: {helps} / {hinders}"` with the dice and the exchange lines absorbed (today's `_absorbed`), the twist facts. The closing test is not repeated here: SCENE shows it every turn.
   - Twist at 3: roll the pair (`twist_pairing`), note `TWIST_NOTE`; when the action is `ENDS_THE_SCENE`, append `world.close("twist", rng)`.
   - `@tool withdraw(args: Withdraw)`, docstring: "The protagonist breaks off the conflict; always allowed, never free: name the cost, then apply it with a tool." Refuse without a conflict; `end_conflict`; the told card names the cost.
   - `@tool inspire(NoArgs)`, docstring: "Roll a verb, a noun and an adjective to read as a lens on what is already here." Three 2d6 rolls on the grids; one trace-only fact "verb noun (adjective)", never told: the master reads it and directs.
   - `@tool dead_end(NoArgs)`, docstring: "The path has closed; the engine asks whether something or someone points a new way." Refuse unless `frame.open`. Roll `DEAD_END_QUESTION` neutral; settle kind `fixed`; the trace gives the SRD's three readings (Yes: a new element; No-but: why it closed; No/No-and: pull back to the goal); a No or No-and adds "close as blocked".
   - `close_scene(unclear)` now settles `RUN_ITS_COURSE` kind `fixed`.
   - `master_sections` add `DEAD ENDS IN THE LAST SCENE` when the previous scene settled `DEAD_END_QUESTION` entries (their lines from `scenes[-2].settled`), so a second dead end on the same thread is visible across the close it usually causes.
   - `master_sections` add `CONFLICT` (each opponent with luck) when a conflict is open; `scene_text` shows the twist counter `n/3`.
   - `panels.py` `sheet_panel`: meters Luck and Twist.
7. `loner4e/pack.py` guidance: luck is 6 for everyone; a `group` is one character with one pool of 6 to 10; a `relationship` tag goes on the NPC; a place's tags are the scene's `details`. Delete "Give 2 or 3 luck to minor opposition".
8. `loner4e/rules.md` rewritten around `ask`, in this order and in short paragraphs: **You interpret; you do not author outcomes.** **When to ask** (obvious or established: apply it; uncertain or risky: `ask`, never settle it in `direct`; an expert does not roll for a standard door; ask even when confident if a twist would be welcome; before acting in a new scene, at most one framing question about what is already true, with no tags). **How to frame** (one closed question; yes is what the protagonist hopes; never compound: split a compound action into single questions in story order; ask only what the player's action raises, never a question the player's next move should answer, and stop at the next choice that is the protagonist's; never name in `question` someone the player has not met; an opponent's action is "Do I avoid it?"). **Tags** (cite only tags that bear on this moment; one or two apply, the rest are inert; a frailty may help; `untrained`; the engine nets them; a circumstance the result creates is a scene `detail`). **Reading** (the six results; the three lenses in six lines; a plain Yes or No adds nothing; a No redirects; a closed path is `dead_end`; a second dead end on the same thread: do not ask again, `close_scene(blocked)`; unclear: don't overquestion it, three follow-ups at most, "if not X, then…", `inspire`, default yes-but). **What is established** (what was told, the tags on a sheet or the scene, and SETTLED THIS SCENE stand: never ask them again; everything else is open: when it matters and is uncertain, ask the oracle instead of deciding it. THE ARC is pressure, not answers: it says what the opposition wants, never what is true). **Conflict** (three ways; `against_id` opens Harm & Luck; one exchange per turn: ask, interpret, `direct`; the player's next words press on, change tack or break away; the Twist Counter rests while a conflict is open; each opponent has its own pool, a group is one character; `withdraw(cost)` always allowed, never free; at 0 the engine ends it; defeat is not death). **Twists** (the pair is a beat; the intensity line; the three actions). **The end of the adventure** (today's text). The Scene paragraph from phase 3 stays.
9. `app/prompts/master.md`: keep only the rules true for every engine: only tools change the world; read every result; a refusal is a correction; `direct` ends the turn, and so does a tool that hands to the worldsmith or the player; the engine rolls, pays and selects; stop when the next step needs the player; add "A tool result may carry a rule line: follow it before you continue." Delete the "Use the dice" paragraphs.
10. The deleted failure lines ("A failure costs something and changes the situation. A failure never shuts the only way on.") go into `engines/rooms/rules.md` (Tunnel Goons and Pokemon share it) and into `twentyfourxx/rules.md` "When to roll" where missing.
11. `qa/s_loner.py`: the roll flow becomes `ask`.

**Tests.**
- Rewrite `tests/loner4e/test_world.py` and `test_tools.py` around the new shapes; delete tests of `roll`, `defeated`, `restore_luck`.
- One each: `position_for` netting and cap; one parametrized table of `ask` refusals; a conflict start refills both sides and doubles tick no twist while it is open; a conflict end refills everyone (one path); the group luck bound; the twist "Ends the scene" sets `frame.next`; `dead_end` No adds "close as blocked".
- `tests/support/golden_turn.py`: the Loner script is `ask` with tags, `change_tags`, `close_scene`, `direct`. Regenerate goldens.

**Done when.** No `roll` tool, no `position`/`edge`/`target_id` argument, no `defeated`, no `restore_luck` remains in `loner4e`. `master.md` names no dice rule. A Loner game asks, fights, twists and closes. Four checks green. `src` ≤ 15985.

---

## Phase 5 — Meanwhile

**Goal.** A rolled 6 is the world's turn: code rolls the ally question and the follow-up; the worldsmith updates the opposition off screen and writes the next scene or opens the breather.

**Depends on:** phase 4.

**Steps.**

1. `loner4e/rules.py`: `MEANWHILE_QUESTION = "Does an ally or wildcard act independently?"`.
2. `loner4e/world.py`:
   ```python
   class CastUpdate(Frozen):
       entity_id: Slug; kind: TagKind; gained: tuple[ShortName, ...] = (); lost: tuple[str, ...] = ()
   class Loner4eMeanwhile(Frozen):
       updates: tuple[CastUpdate, ...]
       scene: Loner4eNext | None   # required exactly when the follow-up is dramatic
   ```
   Every field carries its description. `close` on a 6: roll `MEANWHILE_QUESTION` neutral (settle kind `fixed`), roll the follow-up with `transition_for`, a second 6 read as dramatic; `next = ("meanwhile", follow_up)`. Card: `"Scene closes: {reason}. Next: meanwhile, then {follow_up}"`. Delete the phase-3 "6 reads as dramatic" rule.
3. `loner4e/engine.py`:
   - `end_turn` step (3): a closing frame whose `next[0] == "meanwhile"` sets `WorldsmithRequest(kind="meanwhile", detail=follow_up)`.
   - Handler `meanwhile`: intent `MEANWHILE` in `pack.py`: "MEANWHILE: the world's turn. Cut to whoever holds power; write their new tags in `updates`. The oracle said {Yes/No} to \"Does an ally or wildcard act independently?\"; on Yes update the tags of the NPC most affected and let the next scene show what they did. Then {write the next scene as DRAMATIC in `scene` / write no scene: leave `scene` null; the protagonist gets a quiet window}." The ally answer is the scene's last `fixed` Settled entry.
   - The check applies every update to a deep copy of the world with the entity method (`world.require(entity_id).change_tags(...)`, not the tool), so a `lost` tag not carried or a `gained` tag already carried is refused inside the worldsmith's retry. It also refuses: an unknown id, the player, a party member, a gained tag naming what the player has not met (`world.check_unnamed`), a `scene` present when the follow-up is quiet or missing when dramatic, and on the scene everything the dramatic check refuses.
   - Apply each update with the entity method. Updates on entities the player has met are told as one cutaway card, "Meanwhile: {name} is now {gained}; no longer {lost}" per line (the SRD's "cut to whoever holds power"; the protagonist does not see it, the player does). Updates on unmet entities stay traces (`told=False`, `card=""`). Dramatic: install the scene. Quiet: set `frame.next = ("quiet",)` (the breather) and `frame.offscreen` to the update lines. `Frame.offscreen: str = ""` (replaced with the frame on install); the QUIET intent adds, when set: "Off screen: {offscreen}. Let this scene show it where it touches the aim." The narrator cue on quiet is `MEANWHILE_CUE = "Cut away from the protagonist: tell only what the Meanwhile card says moved, as the world's turn; the protagonist does not see it. Name nothing else."` (in `args.py`); on dramatic it is `MEANWHILE_CUE` then `ARRIVING`, one narration.
   - `request_handlers` adds `meanwhile`.
4. `loner4e/pack.py` `WORLDSMITH_GUIDANCE`: "The opposition's tags say what they are doing now, such as `Searching for the Protagonist`."
5. `loner4e/rules.md`: one line: "A meanwhile happens off screen; the updated tags show in HERE WITH THE PLAYER when those people are here again."

**Tests.** One each: a 6 rolls the ally question and the follow-up inside `close_scene`, and a second 6 reads as dramatic; the handler tells met entities' updates on one card, keeps unmet ones as traces, and installs or opens the breather with `offscreen` set; the check refuses a `lost` tag the entity does not carry. Regenerate goldens.

**Done when.** A meanwhile close plays through both follow-ups; the player reads the cutaway for people they have met, and no unmet name reaches the narrator. Four checks green. `src` ≤ 16060.

---

## Phase 6 — The player asks the oracle

**Goal.** The player types a question and presses **Ask the oracle**; code rolls it word for word through the master's `ask(question=null)`.

**Depends on:** phase 4.

**Steps.**

1. `loner4e/world.py` `Loner4eWorld.player_question: str = ""`.
2. `loner4e/args.py`: `ASK_ORACLE = PendingOption(id="ask", name="Ask the oracle", brief="Type one yes/no question", action_name="ask_oracle")`. `Ask.question` widens to `Told | None` with no default; its description adds "Null asks the question in THE PLAYER ASKS, word for word."
3. `loner4e/engine.py`:
   - `@action ask_oracle(draft, args: Words, _rng)`: refuse unless `frame.open`; store `player_question`; return `[]`. The session then opens a turn with the words.
   - `composer()`: `(ASK_ORACLE, False)` while `frame.open` (the family already hides it while a decision waits).
   - `ask`: the docstring adds "null rolls the question THE PLAYER ASKS". `question: null` takes `player_question` and clears it; refuse null when none waits; refuse a non-null question while one waits ("THE PLAYER ASKS waits: pass `question: null`").
   - `dead_end` and `close_scene(unclear)` refuse while a player question waits.
   - `end_turn` clears `player_question` before its early return (an unasked question is dropped).
   - `master_sections`: `THE PLAYER ASKS` with the stored words.
4. `loner4e/rules.md` (How to frame): "When THE PLAYER ASKS shows a question, your first `ask` passes `question: null`. Do not roll it, and say why with `direct`, when it is not a closed question, when its Yes is the bad side for the protagonist (ask them to turn it round), or when what it asks is already established." The engine drops an unrolled question at `end_turn`.
5. `qa/s_loner.py`: one Ask-the-oracle step.

**Tests.** One each: the null path rolls the stored words and clears them; a non-null question is refused while one waits; `end_turn` drops an unasked question. Regenerate goldens.

**Done when.** The page shows Ask the oracle and the card shows the player's own words. Four checks green. `src` ≤ 16090.

---

## Phase 7 — Modules: Status Track, Challenge Tracks, Leverage

**Goal.** The three optional 4e modules. They are on in every game: the SRD pack turns them on, and every game plays the SRD pack.

**Depends on:** phases 4 and 5.

**Steps — flags and shared.**

1. `loner4e/pack.py` `Loner4ePack`: `status_track: bool = False`, `challenge_tracks: bool = False`, `leverage: bool = False`. `packs/srd.json` sets all three true. The AP packs and written packs leave them false; `Loner4eHead` is unchanged (a pack writer does not choose rules modules). A module is on when any played pack sets its flag: `any(pack.<flag> for pack in self.packs.played(draft.pack_id))`, one engine helper `_module_on(state, flag) -> bool` used by every module tool and section.
2. Each module tool's docstring starts with "(Status Track module)", "(Challenge Tracks module)" or "(Leverage module)" and refuses "this game does not use the {module}" when off.

**Steps — Status Track.**

4. `world.py`: `class StatusTrack(Mutable): boxes: list[str] = []` (`STATUS_BOXES = 3` in `rules.py`); `active` property = `boxes[-1]` or `""`. `Loner4eWorld.status: StatusTrack`. `find_tag` also matches the active status tag.
5. `args.py`: `MarkStatus(tag: ShortName)` ("After a protagonist defeat that leaves a lasting mark, the tag for the next box"); `RecoverStatus(why: Told)`. No call means no mark.
6. `engine.py`: `@tool mark_status` — docstring "(Status Track module) After a protagonist defeat that leaves a lasting mark, fill the next box with this tag; the newest box is the active tag." Refuse when full; a filled third box adds "the protagonist is overcome; the story decides what that means". `@tool recover_status` — "(Status Track module) Clear the newest status box; `why` is the card the player reads." Refuse when empty. A protagonist defeat adds the note "If the defeat leaves a lasting mark, call `mark_status`."
7. `panels.py` sheet: a Status row with the active tag and a meter `n/3`. `master_sections`: `STATUS`.

**Steps — Challenge Tracks.**

8. `rules.py`: `TRACK_SIZES = (4, 6)`; `TRACK_PROGRESS = {"yes-and": 2, "yes": 1, "yes-but": 1, "no-but": 0, "no": -1, "no-and": -1}`; `def track_step(outcome_id: str, *, reverse: bool, banked: bool) -> int` (a banked Yes-and counts +1; the sign flips on a reverse track).
9. `world.py`: `class Track(Mutable): id: Slug; name: str; size: int; filled: int = 0; reverse: bool = False`; `Loner4eWorld.tracks: dict[Slug, Track] = {}`; `Framing.track_id: Slug | None = None` ("The open track this scene is framed on, from the player's aim or the pressure; null when none applies"); `Frame.track_id: Slug | None = None`. `close` moves the focused track once from the scene's last `action` Settled entry (its `outcome_id` and `banked`); fixed entries never move it; no action entry, no move. Filling a track adds "the track is full: the arc can close" (reverse: "the pressure has become a fact"). A failed write never moves it twice: the move happens in `close`, which runs once.
10. `args.py`: `OpenTrack(name: ShortName, size: Literal[4, 6], reverse: bool = False)`.
11. `engine.py`: `@tool open_track` — "(Challenge Tracks module) Open a track for a pursuit that spans scenes; reverse for a mounting threat." Id is `slug(name, existing)`. A track opened mid-scene is framed on from the next scene. Loner's own request checks (the `check` passed to `write_next`) list as a need a `track_id` that names no open track; `new_game` refuses a non-null `track_id` on the opening (no track is open yet).
12. `worldsmith_sections` and `master_sections`: `TRACKS` (name, id, `filled/size`, reverse). `panels.py`: `tracks_panel(world)`, one meter per track; `scene_panel` shows the focused track. `pack.py` guidance: "`track_id` names the open track the scene is framed on, when one applies."

**Steps — Leverage.**

13. `world.py`: `class Leverage(Mutable): phrase: str; armed: bool = False` (the phrase is the banked question). `Loner4eWorld.leverage: Leverage | None = None`. The twist clears it.
14. `args.py`: `SettleLeverage(outcome_id: Slug, against_id: Slug | None, use: bool)` (action only); `DropLeverage(why: Told)`.
15. `engine.py`:
    - `ask`, module on: an `armed` leverage counts only when the master cites its phrase in `helps` (`find_tag` matches `leverage.phrase` while armed: the SRD's "related to the same pursuit"); citing it consumes it. Uncited, it stays armed. On a Yes-and, or on a No/No-and while holding, emit the dice and trace only, settle the rolled result, and open `PendingDecision(kind="leverage", options=..., allows_text=False)` whose options carry `outcome_id`, `against_id` and `use`. Yes-and prompt: `"Yes, and: '{question}'. Bank it as leverage, or take the boon now?"` (options "Bank it" / "Take it now"; while holding: "Replace the held leverage" / "Take it now"). No prompt: `"No: '{question}'. Spend the leverage? It becomes No, but."`, plus " Spending also keeps the track box." when the scene has a `track_id` (options "Spend it" / "Keep it"). The exchange waits.
    - `@action settle_leverage`: on a Yes-and, `use` banks or replaces and marks the scene's last Settled entry `banked=True`; on a No, `use` spends: the result becomes `as_no_but()` and the last Settled entry is replaced with that reading. Then it writes the final told card and, with `against_id` still in the conflict, calls `_exchange`. No decision follows, so the option's turn is played: the master interprets the final result. A banked Yes-and deals the harm of a plain Yes (2): the bonus is saved, not narrated.
    - `@action arm_leverage(NoArgs)`: refuse unless holding; set `armed`. A sheet-panel option on the Leverage row.
    - `@tool drop_leverage` — "(Leverage module) The held leverage no longer connects to the fiction; `why` is the card."
    - `master_sections`: `LEVERAGE HELD`. `panels.py` sheet: a Leverage row with the phrase and the `arm_leverage` option.
16. `loner4e/rules.md`: "## Modules" paragraphs: Status Track (after a protagonist defeat that leaves a lasting mark, `mark_status(tag)`; the SRD's example columns — Hurt / Injured / Overcome; Rattled / On the Back Foot / Humiliated; Unsettled / Shaken / Broken; the active tag can hinder; `recover_status(why)` needs a fictional reason). Challenge Tracks (`open_track` for a pursuit that spans scenes; TRACKS shows where they stand; check it before you ask). Leverage (the player banks and spends; LEVERAGE HELD shows it; `drop_leverage(why)` when the fiction no longer connects to it). 

**Tests.** One each: status fill and recover (the active tag moves back); the overcome line on the third box; `track_step` forward, reverse and banked; a fixed question never moves a track; leverage bank, spend (No becomes No-but in Settled), arm consumed by the next ask, cleared on a twist; the leverage pause tells nothing and the option tells the final card. Regenerate goldens.

**Done when.** Every game, AP packs included, plays all three modules. Four checks green. `src` ≤ 16200.

---

## Phase 8 — End of the adventure

**Goal.** The master proposes the end; the player confirms and says what was learned; the master writes the growth once; the worldsmith writes the Living World; the game ends; the grown sheet is written back.

**Depends on:** phase 4.

**Steps.**

1. `loner4e/world.py`: `Loner4eEntity.living_world: list[str] = []` (the Living World lines of the character's past adventures; not a sheet row). `Loner4eWorld.end_why: str = ""` (the end the player is asked to confirm; `play_on` clears it) and `ended: bool = False`. `class LivingWorld(Frozen): people: tuple[Told, ...]; places: tuple[Told, ...]; events: tuple[Told, ...]` with descriptions from the intent. `end_why` replaces the design's `growth_due`, because a text answer to a decision runs no engine code: the end stays pending from `end_adventure` until `play_on` clears it, and the request detail needs the why.
2. `loner4e/args.py`: `EndAdventure(why: Told)`; `ENDING_PROMPT = "End the adventure here? Say what {name} learned, or play on."`; `PLAY_ON = PendingOption(id="play-on", name="Play on", action_name="play_on")`; the note `GROWTH = "If the player confirmed the end and said what {name} learned, write that growth once with `change_tags` or `drive`, then direct. If the player declined in their own words, call `play_on`."`; `EPILOGUE = "The adventure is over. Tell WHAT HAPPENED as a short epilogue."`
3. `loner4e/engine.py`:
   - `@tool end_adventure` — "Propose the end of the adventure; the player confirms and says what they learned." Set `end_why`, note `GROWTH`, open `PendingDecision(kind="ending", prompt=ENDING_PROMPT, options=(PLAY_ON,), allows_text=True)`.
   - `play_on(NoArgs)` marked `@tool` and `@action`, docstring "The player declined the end in their own words." It clears `end_why`.
   - `end_turn` step (2): with `end_why` set, `WorldsmithRequest(kind="living-world", detail=end_why)`, and return. With `end_why` set, a closing `frame.next` is kept; after **Play on** the next played turn hands the scene over. So the order is: text answer, growth turn, request, `ended`.
   - Handler `living-world`: intent `LIVING_WORLD` in `pack.py`: "The adventure ended: {why}. For each NPC or faction that mattered: how the relationship stands, what they want now, gone or still in play. For each location: what changed there. For each event or thread: settled or still hanging. One line each; the player reads them." The check refuses a line naming what the player never met (`world.check_unnamed`). Tell the three lists as one told card, append their lines to `world.player.living_world`, set `ended`, cue `EPILOGUE`.
   - `ending(state)`: `"The adventure is over."` when `ended`, else `super()`.
   - `grown_character(state) -> AnyCharacter | None`: when `ended`, `Character[Loner4eEntity](id=state.character_id, engine_id=self.id, sheet=<the player with luck refilled>)`.
4. `engines/engine.py`: `def grown_character(self, state: Game[W], /) -> AnyCharacter | None: return None`.
4a. `loner4e/engine.py` `worldsmith_sections`: `WHAT THE PROTAGONIST CARRIES FORWARD` with `world.player.living_world` when non-empty, so the character's next Loner game writes its scenes from it. The pre-authored opening is not rewritten.
5. `core/io.py`: a private helper `_player_character_path(library, character) -> Path` holds the shipped-character refusal and the path, shared by `write_character` and the new `Library.rewrite_character(character)`, which overwrites the player's own `<characters>/<id>/<engine_id>.json` ("{id} ships with the game; its sheet is not rewritten" for a shipped one). `write_character` keeps its exists and sibling-name checks.
6. `app/session.py`: `GameService.library: Library` (passed by `app/runtime.py`). After `_write_request` lands, when `self.engine.grown_character(self.state)` is not `None`, call `library.rewrite_character` and set `self.character` to the grown character, so a restart replays the grown sheet; a `Refusal` there is logged as a warning, like a world that did not grow.
7. `loner4e/rules.md` "## The end of the adventure": the SRD's signals (goal achieved or failed, abandoned with no new direction, a revelation, a satisfying resolution, momentum gone); call `end_adventure(why)`; write the growth once when the player has confirmed and said what they learned (a new skill, gear or frailty; a new nemesis; a modified trait); if they declined in words, `play_on`.
8. `qa/s_loner.py`: the ending step.

**Tests.** One each: `close_scene` and `end_adventure` in one turn leave only the ending decision and no request; a text answer, the growth turn, then the `living-world` request, then `ended` with the card; `rewrite_character` overwrites a player's sheet and refuses a shipped one; the session writes back and refreshes `character` after the end; a new game's worldsmith prompt carries the Living World lines. Regenerate goldens.

**Done when.** A Loner game with a player-made character ends with the Living World card, and the sheet on disk shows the growth (the shipped Kael is never rewritten). Four checks green. `src` ≤ 16270.

---

## Phase 9 — 24XX fidelity

**Goal.** The player commits or revises before each risky roll, seeing the dice and the stakes; the player may break gear to turn a hit into a hindrance; job results, advancement, the ship emergency, the bad-luck test and death follow the SRD.

**Depends on:** phase 4 (Settled).

**Steps.**

1. `twentyfourxx/args.py` `Roll`: `committed: bool = Field(default=False, description="True only when the player's own words for this action name this danger and accept it, such as 'I jump even if I fall'. A bare 'I shoot him' accepts nothing. That the story told the danger before is never enough. A text answer that accepts the risk prompt as shown commits.")`.
2. `twentyfourxx/engine.py` `roll`: marked `@tool` and `@action`. With `committed` false it validates the pool (`_pool`) and the defences (`check_defenses`), then opens `PendingDecision(kind="risk", prompt=self._stake_prompt(actor, pool, args), options=(PendingOption(id="commit", name="Commit", action_name="roll", args={**args.model_dump(mode="json"), "committed": True}),), allows_text=True)` and returns `[]`: no fact, so no narrator runs. With `committed` true it rolls at once, as today. A text answer is a revision and leaves nothing behind. `_stake_prompt` builds one line from the pool and the stakes: `"{what}: {label} d{die}{+ d6 helped: why}{, helped by X dX}{; hindered: why} — risking {risk}{ (deadly)}{; X risks …}.{ Hindrances: …}{ Carries N bulky items.}{ Cannot succeed without help.} Commit, or revise in your own words."` ("Cannot succeed" when every face is below 5; the hindrances are the actor's sheet list, so the player sees what the master did not set). Docstring: "Call this only to avoid a risk. The engine checks the dice and asks the player to commit, unless `committed` is set; then it rolls and reads the result."
2a. Defence as a reaction. `roll` splits into the dice and a private `_land(draft, args: Roll, rolled: DiceEvent, defence_id: Slug | None) -> list[Fact]` that writes the roll card, lands every stake (`take_hit`) and runs `_succession`. The pause opens only where a hit lands on the actor: a disaster, or a setback on a `deadly` roll; the actor named no `defend_with_id`; and `TwentyFourXXWorld.defences_for(actor) -> list[tuple[Slug, Gear]]` (unbroken carried items, and unbroken ship functions while the ship is here) is non-empty. Then `roll` returns only the untold dice fact (the card is withheld while the pause is open) and opens `PendingDecision(kind="defence", prompt=f"{what}: {band}. {risk} hits {name}. Break an item to turn it into a brief hindrance, or take it.", options=<one per defence> + "Take it", allows_text=False)`. Each option runs `@action defend_hit(args: DefendHit)`, `DefendHit(roll: Roll, rolled: DiceEvent, item_id: Slug | None)`, which calls `_land`. A broken non-harmless item leaves the hindrance `f"Brief: {risk}"` (cut to `NAME_MAX`), which `_break` accepts; a harmless item leaves none; the trace adds "the hit became a brief hindrance: do not apply `risk`; remove the hindrance when the moment ends". The option's turn is played, so the master interprets the whole result. A helper's defence stays the pre-roll `defend_with_id`.
3. `job find` result lines (1-2 per the SRD's "spend to re-roll, or risk debt"): 5-6 "a choice between two jobs: offer two with `direct`; the player picks in their words; `job take` records the pick"; 3-4 "a job, but something seems off: when you `take` it, put 'something seems off' in `terms`"; 1-2 "nothing: offer to pay ₡1 (`spend`) and `find` again, or to take a job owing somebody; when you `take` that one, put 'owes somebody' in `terms`". The find result is settled (kind `fixed`).
3a. Advancement. `Raise` entries in `job finish` name hired members only; `job finish` pays everyone, closes the job, sets `TwentyFourXXWorld.raise_owed: bool = True` and opens `PendingDecision(kind="raise", prompt="The job is done. Which skill do you raise? Pick one, or name a new one.", options=<one per sheet skill below d12>, allows_text=True)`. Each option and a text answer land through `raise_skill`, marked `@tool` and `@action`, `RaiseSkill(skill: Told)` ("The skill the player named for their raise after a job; a new one starts at d8"), docstring "Raise the skill the player chose after a job." It refuses unless `raise_owed`, then clears it.
3b. Death with no hired crew. `ending` no longer ends the game on a death; `_succession` with no hired member alive opens `PendingDecision(kind="newcomer", prompt=f"{name} is dead. Who joins the crew? Describe them in your own words.", options=(), allows_text=True)`. The master answers the text with `@tool bring_in(args: BringIn)`, `BringIn(who: Told)` ("The new operator in the player's words"), docstring "A new operator joins the crew after the lead died; the worldsmith writes them." It sets `WorldsmithRequest(kind="newcomer", detail=who)`. The handler reuses the hiring path: the worldsmith answers `NewcomerProposal(Frozen)` (`id`, `name`, `brief`, `sheet: SheetProposal`); code files the person, places them here, joins them to the party with the sheet and makes them the lead (`take_lead`'s code). Refuses unless the lead is dead and no hired member lives. `docs/24XX.md` drops deviation 2.
4. `args.py`: `ShipEmergency(danger: Told, risk: ShortName, deadly: bool = False, stations: tuple[Station, ...] = Field(min_length=1))`, `Station(function_id: Slug, skill: str = "")` ("A ship function this emergency calls on, and the skill working it rolls; empty rolls the plain d6"), every field with a description. `engine.py` `@tool ship_emergency` — "An emergency on the ship: name the functions it calls on and the skill each uses; the player picks one to work; the pick is the commit." Refuses an unknown function id. Opens `PendingDecision(kind="emergency", prompt=f"Emergency: {danger}. Which ship function do you work?", options=<one per station>, allows_text=False)`; each option is `roll` with `what=f"{function}: {danger}"`, `risk`, `deadly`, that station's `skill`, `committed=True` and no `defend_with_id`.
5. `ask_world` becomes `@tool test_luck(args: BadLuck)`, `BadLuck.question: str` ("The bad luck you test: ammo, guards, weather"). Docstring: "Test for bad luck when no one acts: ammo, guards, weather; one d6." The answer is settled (kind `fixed`), not told.
6. `twentyfourxx/rules.md`: "## Before a roll": impossible → `direct`; a cost or extra steps → "Name the cost with `direct` and ask; apply it only when the player's next words accept it."; risky → `roll`, always, never settled in `direct`, and the engine asks the player to commit; "Set `committed` only when the player's own words for this action name this danger and accept it, such as 'I jump even if I fall'. A bare action such as 'I shoot him' accepts nothing. That the story told the danger before is never enough. A text answer to the risk prompt that accepts it as shown ('yes, do it') commits: the prompt named the danger; call `roll` again with the same stake and `committed`." Delete "Name only a danger that the story already told the player about": the pause now tells it; keep "name the danger plainly in `risk`". Hindrances: "Read HINDRANCES before every roll; the player sees them on the commit prompt." Defence: the player may break gear after the roll; `defend_with_id` stays for gear the player named before it. Advancement: the player picks their own raise. Death: `bring_in`. Add "Present dilemmas you do not know how to solve." and "Describe people by behaviour, risk and obstacle, not dice." Rename `ask_world` to `test_luck`; describe `ship_emergency`.
7. `docs/24XX.md`: the tools list (`roll` commit step and defence pause, `test_luck`, `ship_emergency`, `raise_skill`, `bring_in`); deviations: a helper without a sheet shares no risk (kept: an unsheeted member has no sheet to carry a hit); delete "the game ends when no hired member is left"; the commit pause's one escape (`committed` from the player's own words).
8. `tests/support/golden_turn.py`: the 24XX script's `roll` passes `committed=true`, so the golden records a roll, not the pause. `qa/s_24xx.py`: a Commit step.

**Tests.** One each: `roll` as a tool opens the decision and tells nothing; the Commit option rolls once; `committed` rolls at once; a deadly setback with carried gear opens the defence pause with the card withheld, and breaking an item spares the hit and tells the card; a non-deadly setback opens no pause; `raise_skill` refuses when no raise is owed; a death with no hired crew opens the newcomer decision and the handler makes the newcomer the lead; `test_luck` is settled; each emergency option rolls with the function in `what`. Regenerate goldens.

**Done when.** A 24XX risky action pauses on Commit with its dice shown; a landing hit can break gear, and the master always rules on the result; the player picks their raise; a lone death brings in a new operator. Four checks green. `src` ≤ 16470.

---

## Phase 10 — Loner rules text and docs

**Goal.** Loner's rules text reads as one piece; the docs record every deviation and reading; the goldens are current.

**Depends on:** phases 1-9.

**Steps.**

1. `loner4e/rules.md`: a final pass for order and one voice (the order of phase 4 step 8, then Scene, Modules, End). Every tool named exists; no removed tool is named; cut repetition.
2. `docs/LONER-4E.md`: the tools list; the deviations and readings below; "What the AI game master adds" (known/unmet; alive/kill; the scene frame and `close_scene`; Settled; composer options; the Living World carried with the character); "Where the rules live" (`tables.py` is the transcription of record).
3. Refresh every golden.

**Tests.** Goldens only.

**Done when.** The docs list every deviation below. Four checks green. `src` ≤ 16450.

---

## Deviations and readings for `docs/LONER-4E.md`

Deviations (a divergence from the SRD, with its reason):

1. **A twist fires inside the question that rolled it.** The app cannot interrupt a resolved call; the narration shows it arriving that turn.
2. **One Twist Counter beside the world.** One protagonist, one counter.
3. **`packs/srd.json`'s starter tables are ours.** The twist, inspiration and transition tables are the SRD's, in `tables.py` and `rules.py`.
4. **The party.** NPCs may join only to follow the protagonist. They never roll; their help is a tag cited in `helps`.
5. **Trait labels carry no meaning of their own.**
6. **Group luck above 6.** Only a group may carry 6 to 10; every other character has 6.
7. **The master is an interpreter.** The player may ask directly; the master asks on the player's behalf when an action needs a question. Code rolls. This adapts 4e's "With a Game Master" line, where the players consult the oracle and the GM interprets.
8. **The world is emergent, with a premise.** A scenario is a premise, an opening scene and a web of people who may turn up (the SRD's own "Before the Adventure"). Nothing is hidden and no twist is planned; the arc is loose pressure. What is established stands; the oracle decides the rest.
9. **Scenarios are written ahead of play.** 5W+H, the Adventure Maker and the transition meaning lines are not transcribed.
10. **Leverage decisions belong to the player**; the phrase is the banked question.
11. **The modules are always on.** They are rules of the SRD pack, which every game plays; a pack may add one, none removes one. The SRD makes each optional for the solo player.
12. **Meanwhile is a cutaway, not a scene.** The worldsmith applies both steps; the player reads what moved for the people they have met on one card and does not play it.
13. **The question text is public** and names no one the player has not met. No private note is stored.
14. **Code rules the conflict boundary**: it starts at the first exchange against an opponent and ends at 0, `withdraw`, the last opponent leaving or dying, or the scene closing.
15. **Goal and motive stay creation steps**, optional ("leave empty to let play decide"); the opening offers a goal.
16. **The Living World is carried as lines.** It is told as the closing card and stored with the grown character; the character's next Loner game gives it to the worldsmith. NPC state in the ended game is not rewritten.
17. **The breather.** A quiet scene's aim is the player's words on the Take the breather button; the worldsmith frames it as the goal.
18. **The twist table lives in code.** Code keys on "Ends the scene", "Changes the goal" and "Alters the location"; a pack cannot replace the columns.

Readings (where the SRD is open):

1. Tag netting counts: `sign(helps − hinders − untrained)`, one die at most (the alley example); an armed leverage is a help when its phrase is cited.
2. The master decides relevance; code checks existence and uniqueness on known things only. The card shows the cited tags.
3. Action questions are protagonist-oriented; code-rolled world questions are neutral.
4. Both ask; the player's question is rolled word for word.
5. The worldsmith writes the goal; `drive(actor_id="scene")` rewrites it when the player's first words set another aim, or after "Changes the goal". A different pursuit later closes as `abandoned`.
6. The master closes; SCENE repeats the SRD's test every turn (not every ask result, which would push early closes). No question quota: "six to eight questions" is a first session, not a scene.
7. Meanwhile updates on met people are told on the cutaway card; on unmet ones they stay traces; an unmet entity's tag cannot be cited.
8. The last action ask of the scene moves the track; fixed questions never do.
9. "Ends the scene" closes through the twist's own ask; "Alters the location" is a scene `detail`.
10. With the Status Track on, a protagonist defeat gets the note "call `mark_status`" when the defeat leaves a lasting mark. The note is the only enforcement.
11. The Status Track is the protagonist's only.
12. Several opponents each keep their own pool (option 2); a group is one character (option 1). An opponent at 0 leaves the conflict while others fight on.
13. One framing question is rules text: code cannot tell a fact question from an action question.
14. Relationship tags live on the NPC.
15. After a Meanwhile, code rolls the transition again; a second 6 reads as dramatic.
16. A player question that is not closed: the master says so with `direct`; `end_turn` drops it.
17. Leverage and a track: one chance, at ask time; spending turns the No into No-but, which is no track change. A banked Yes-and marks one box.
18. The scene's track is set at framing by the worldsmith; the master never sets it; a track opened mid-scene is framed on from the next scene.
19. A reverse track flips the step's sign: a No fills a threat box, a Yes erases one.
20. Spent luck outside a conflict (AP01 spells) refills when a quiet scene opens. No rest tool.
21. No open-threads list: the debrief lists them from history; the worldsmith keeps them in `arc`.
22. No pause between exchanges: the SRD asks nothing of the player there. The master interprets each exchange, one per turn, and the player's next words press on, change tack or break away.
23. End order: the decision, the growth, the Living World request, `ended`, the sheet write-back.
24. Dead-end memory is the master's: SETTLED and DEAD ENDS IN THE LAST SCENE show the earlier dead end; a string match the model could reword was not worth its state.
25. Twist intensity is the master's judgment, stated in one line of the twist note.
26. The Twist Counter rests while a Harm & Luck conflict is open, for every ask (the SRD: it "does not apply during Harm & Luck conflicts").
27. A banked Yes-and inside Harm & Luck deals the harm of a plain Yes: the bonus is saved, not spent.
28. When to ask is rules text, not a code gate: code cannot tell an obvious try from an uncertain one.
29. A player question whose Yes is the bad side, or whose answer is established, is not rolled; the master says why and the question is dropped.
30. A track moves on the scene's last action ask, not a "most bearing" pick: code cannot judge bearing.
31. The 24XX newcomer is written by the worldsmith from the player's words, not built through the creation page.

---

## Appendix A — SRD tables (Loner 4e: Core Rules © 2026 Roberto Bisceglie, CC BY-SA 4.0)

Twist (d6 per column):

| d6 | Subject | Action |
|---|---|---|
| 1 | A third party | Appears |
| 2 | The Protagonist | Alters the location |
| 3 | An encounter | Helps the Protagonist |
| 4 | A physical event | Hinders the Protagonist |
| 5 | An emotional event | Changes the goal |
| 6 | An object | Ends the scene |

Inspiration: roll 2d6 per grid, the first die the row, the second the column.

Verbs:
1. inject, pass, own, divide, bury, borrow
2. continue, learn, ask, multiply, receive, imagine
3. develop, behave, replace, damage, collect, turn
4. share, hand, play, explain, improve, cough
5. face, expand, found, gather, prefer, belong
6. trip, want, miss, dry, employ, destroy

Adjectives:
1. frequent, faulty, obscene, scarce, rigid, long-term
2. ethereal, sophisticated, rightful, knowledgeable, astonishing, ordinary
3. descriptive, insidious, poor, proud, reflective, amusing
4. silky, worthless, fixed, loose, willing, cold
5. quiet, stormy, spooky, delirious, innate, late
6. magnificent, arrogant, unhealthy, enormous, truculent, charming

Nouns:
1. cause, stage, change, verse, thrill, spot
2. front, event, home, bag, measure, birth
3. prose, motion, trade, memory, chance, drop
4. instrument, friend, talk, liquid, fact, price
5. word, morning, edge, room, system, camp
6. key, income, use, humor, statement, argument

Scene transition (d6): 1-3 Dramatic, 4-5 Quiet, 6 Meanwhile.

Challenge Track progress: Yes-and +2; Yes and Yes-but +1; No-but 0; No and No-and −1. Four boxes, six for long arcs.

Status Track examples (printed in `rules.md` only): Physical Hurt / Injured / Overcome; Social Rattled / On the Back Foot / Humiliated; Psychological Unsettled / Shaken / Broken.

Fixed questions: dead end "Does something or someone point toward a new way forward?"; meanwhile "Does an ally or wildcard act independently?"; closing "Has this scene run its course?".

Resolution: Chance > Risk yes; Risk > Chance no; equal is Yes-but (+1 Twist on doubles outside Harm & Luck) and skips step 2; both ≥ 4 add "and"; both ≤ 3 add "but". Luck loss: Yes-and 3, Yes 2, Yes-but 1 to the opponent; No-but 1, No 2, No-and 3 to the protagonist.
