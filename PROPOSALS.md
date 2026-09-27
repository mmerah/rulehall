# Code quality proposals for MVP0

Scope: `src/rulehall` (Python only). Baseline: `ruff` and `basedpyright` are clean. No rule in CLAUDE.md is broken badly. The problems are duplicates, one oversized module, a few leaks of the house rules, and naming slips.

**Naming rule for every accepted proposal:** use descriptive, human-readable names, even when they are longer. Avoid vague words such as `meta`, `data`, `info`.

**Result:** all 12 proposals accepted (some with changes). About **−170 LOC**, one process leak fixed, one layout rule for every engine, `pokemon/world.py` from 1544 to ~800 lines. All drastic cuts rejected.

| # | Proposal | LOC | Behaviour change | Status |
|---|---|---|---|---|
| 1 | One base method to ask the worldsmith during play | −30 | none | ACCEPTED |
| 2 | Move proposal checks into the proposal models; drop the `check_opening` hook | −24 | refusal text only | ACCEPTED |
| 3 | Remove `SceneEngine` defaults that every engine overrides | −10 | none | ACCEPTED |
| 4 | One `CastPack` base for factions/people/monsters | −12 | none | ACCEPTED |
| 5 | One file layout for every engine; smaller `pokemon/world.py` | ~0 (moves) | saves invalid (D3) | ACCEPTED (D1 sheet.py, D2 always, D3 sub-models) |
| 6 | Close the battle simulator on every failure; reuse `StateCache` | −3 | bug fix | ACCEPTED |
| 7 | HTTP errors become a `Refusal` in one place | −6 | none | ACCEPTED (A) |
| 8 | `io.py` holds files only; `validation.py` holds all parsing | −6 | none | ACCEPTED |
| 9 | Remove duplicate build steps in `app/` | −19 | none | ACCEPTED |
| 10 | Small duplicates and dead code in the engines | −45 | none | ACCEPTED (all) |
| 11 | UI: one choice-group helper, shared form code | −14 | small visual | ACCEPTED (A) |
| 12 | Naming: ids end in `_id`, one name per concept | 0 | saves invalid | ACCEPTED (A, descriptive names) |

---

## 1. One base method to ask the worldsmith during play

**Status: ACCEPTED.**

**In short.** Four places build a worldsmith prompt and then call the worldsmith. They do it the same way. Put it in the base `Engine` once.

**Now.** `Engine.render_request` (`engines/engine.py:194`) is always followed by `await worldsmith(prompt, model, check)`. This pair is written 4 times:
- `engines/rooms/engine.py:209` (`write_next`)
- `engines/scenes/engine.py:167` (`ask_worldsmith`)
- `engines/hiring.py:83` (`write_hire`)
- `engines/twentyfourxx/engine.py:658` (`write_newcomer`)

`SceneEngine.write_scene` (`scenes/engine.py:138`) wraps "ask, then `install_scene`" and has one caller (`loner4e/engine.py:307`). 24XX does the same two steps by hand.

**Change.** Replace `render_request` with `ask_worldsmith` (name chosen for clarity; the scene method of that name becomes `ask_worldsmith_for_next_scene`):
```python
async def ask_worldsmith[A: BaseModel](
    self,
    draft: Game[W],
    worldsmith: RoleAnswer,
    intent: str,
    answer_model: type[A],
    check: Check[A],
    *,
    guidance: str | None = None,
) -> A:
    prompt = render_worldsmith(
        ...,
        guidance=self.guidance_for(draft.pack_id, opening=False) if guidance is None else guidance,
        answer_model=answer_model,
    )
    return await worldsmith(prompt, answer_model, check)
```
- `RoomEngine.write_next` becomes one line.
- `SceneEngine.ask_worldsmith` is renamed `ask_worldsmith_for_next_scene`. It keeps only its arc text and calls `self.ask_worldsmith`.
- `write_hire` and `write_newcomer` pass `guidance=self.hire_guidance(draft)`.
- Delete `write_scene`. Loner4e calls `ask_worldsmith_for_next_scene`, then `install_scene`.
- Naming rule for this change: full, human-readable names, even if longer.

**Impact.** Prompts stay byte-identical, so goldens do not move. `tests/engines/test_rooms.py:204` calls `render_request` and needs a one-line update. No feature change.

---

## 2. Move proposal checks into the proposal models; drop the `check_opening` hook

**Status: ACCEPTED.**

**In short.** Two engines patch proposals by hand at many call sites. A pydantic validator can do it once, at parse time. Then the `check_opening` hook has no users and goes away.

**Now.**
- Loner4e: `_loner_needs` (`loner4e/engine.py:664`) checks the reserved `scene` cast id. It is called at lines 144, 245, 305. The `check_opening` override (line 141) needs a `cast(...)` only for this.
- 24XX: `filed_by_name` (`twentyfourxx/world.py:572`) re-keys the cast by name. It is called at `world.py:267`, `engine.py:587`, `engine.py:590`, `engine.py:593`. On the opening path it runs twice.
- `SceneEngine.check_opening` (`scenes/engine.py:50`) exists only for these two overrides.

**Change.**
- `Loner4eOpening` and `Loner4eNext`: add `@model_validator(mode="after")` that raises `ValueError` when `SCENE_ID in self.cast`. Delete `_loner_needs`, the override and its `cast`, and the `needs=` arguments.
- `TwentyFourXXScene` and a real `TwentyFourXXNext` subclass: `filed_by_name` becomes a `@model_validator(mode="before")`. Delete the 4 call sites and the override.
- Delete the `check_opening` hook. `new_game` calls the free `check_opening(proposal)`.

**Impact.** A bad proposal now fails at parse time. It still gets the normal one retry. The refusal text changes a little (it is no longer merged with the other "needs"). The validator must be idempotent (re-slugging slugs gives the same keys); check the hand-built proposals in `tests/twentyfourxx`.

---

## 3. Remove `SceneEngine` defaults that every engine overrides

**Status: ACCEPTED.**

**In short.** The scene base gives defaults that both scene engines replace. One engine reuses a default with a fragile tuple unpack.

**Now.**
- `SceneEngine.composer` (`scenes/engine.py:53`) is overridden by loner4e (152) and 24XX (221).
- `SceneEngine.scene_panels` (`scenes/engine.py:119`) is replaced by 24XX (398). Loner4e (180) does `_sheet, *party, _here, trail = super().scene_panels(state)`. This breaks silently if the base order changes.

**Change.** Make both `@abstractmethod`. Loner4e lists its panels in plain order: `(sheet_panel(...), scene_panel(...), *party_panel(...), here_panel(...), trail_panel(...))`.

**Impact.** None on features. `tests/loner4e/test_engine.py:15` still works.

---

## 4. One `CastPack` base for factions/people/monsters

**Status: ACCEPTED.**

**In short.** Three packs declare the same three fields and render them the same way.

**Now.** `tunnelgoons/pack.py:44`, `loner4e/pack.py:164`, `twentyfourxx/pack.py:135` each declare `factions`, `npcs`, `monsters: tuple[XBlock, ...] = ()` and render `bullets("FACTIONS"/"PEOPLE"/"MONSTERS", ...)`.

**Change.** In `engines/packs.py`:
```python
class Block(Protocol):
    def line(self) -> str: ...


class CastPack[B: Block](Pack):
    factions: tuple[B, ...] = ()
    npcs: tuple[B, ...] = ()
    monsters: tuple[B, ...] = ()

    def sections(self, *, opening: bool) -> Sections:
        return (
            *super().sections(opening=opening),
            *self.table_sections(),
            *bullets("FACTIONS", ...),
            *bullets("PEOPLE", ...),
            *bullets("MONSTERS", ...),
        )

    def table_sections(self) -> Sections:
        return ()
```
Each pack becomes `CastPack[XBlock]` and overrides `table_sections` (items, trait tags, specialties). The per-engine block classes stay.

**Impact.** Same section order, so prompts and pack JSON do not change. Pokemon is not affected.

---

## 5. One file layout for every engine (and a smaller `pokemon/world.py`)

**Status: ACCEPTED — D1 `sheet.py`, D2 always, D3 sub-models.**

**In short.** The engines put the same kinds of code in different files. `pokemon/world.py` (1544 lines) is the worst case. Fix the layout rule once, then apply it to all engines. Save-shape changes are allowed.

**Now (the inconsistencies).**
- Choice builders (`PendingOption`, `PendingDecision`) live in four different places:
  - `args.py`: loner4e (9 options), 24XX (1)
  - `engine.py`: loner4e (6), 24XX (9)
  - `world.py`: tunnelgoons (`level_up_decision`), pokemon (3 decision builders with hard-coded action names)
  - `panels.py`: pokemon, 24XX, loner4e, rooms
- `args.py` holds argument models in rooms, scenes, tunnelgoons and pokemon. In loner4e (lines 22–144) and 24XX (12–93) it also holds master notes, cards and facts.
- The rooms family has `rooms/panels.py`. The scenes family keeps `trail_panel` in `scenes/engine.py:187`, and 24XX imports it from there.
- Character and sheet models sit in `world.py` in every engine: `Goon`/`GoonSheet`, `Loner4eEntity`/`StatusTrack`, `Kit`/`Gear`/`CrewSheet`/`Crewmate`, `Mon`/`TrainerSheet`/`Trainer` (~560 lines in pokemon).
- `PokemonWorld` (~720 lines) owns 8 scheme fields and 4 rival fields with their methods mixed into the class.

**Change: the layout rule (replaces the engine-package bullet in CLAUDE.md).**

| File | Holds | Family base (rooms, scenes) | Leaf engine |
|---|---|---|---|
| `rules.py` | pure rules | only when needed | only when needed |
| `sheet.py` | the engine's person model, its sheet and their parts | no | always (D2) |
| `world.py` | the world class, its sub-state models, worldsmith proposal models | yes | yes |
| `args.py` | argument models and their field descriptions only | yes | yes |
| `panels.py` | every `Panel`, `PendingOption` and `PendingDecision` builder | yes | always (D2) |
| `worldsmith.py` / `pack.py` | as today | `worldsmith.py` | `pack.py` |
| `engine.py` | the engine, plus the master notes, cards and facts it sends | yes | yes |
| subpackage | one concern of several files (e.g. `pokemon/battle/`) | — | only when needed |

Import flow: `rules <- sheet <- world <- args <- panels <- engine`.

**Change: the moves this rule causes.**
- **All leaf engines:** character and sheet models move from `world.py` to `sheet.py`.
- **loner4e, 24XX:** the options in `args.py` go to `panels.py`; the notes, cards and facts go to `engine.py`. Inline `PendingDecision(...)` blocks in `engine.py` become named builders in `panels.py` (e.g. `status_decision(world)`); the engine does `draft.pending = status_decision(world)`.
- **tunnelgoons:** gets `sheet.py` and `panels.py` (`level_up_decision` moves there).
- **scenes:** gets `scenes/panels.py` with `trail_panel`, like `rooms/panels.py`.
- **pokemon:**
  - `Mon`, `MoveSlot`, `Learning`, `Evolving`, `TrainerSheet`, `Trainer` and their helpers go to `sheet.py`.
  - `next_decision` and the three decision builders go to `panels.py` as `pending_decision(world)`.
  - The scheme and rival state become two sub-models in `world.py` (D3): `SchemeTrack(Mutable)` (the 8 scheme fields plus `_move_scheme`, `_end_operation`, `_hold_way`, `_stake`, `_check_scheme`, `scheme_lines`, ...) and `RivalTrack(Mutable)` (the 4 rival fields plus `place_rival`, `_rival_leaves`, `_rival_roster`). `PokemonWorld` keeps `scheme: SchemeTrack` and `rival: RivalTrack`.
  - Result: `world.py` is ~800 lines and `PokemonWorld` is ~400 lines.

**Decisions.**
- **D1 — name of the people file.** A: `sheet.py` (recommended: matches `Sheeted`, `GoonSheet`, `CrewSheet`, `TrainerSheet`). B: `cast.py` (matches the scene `cast`). C: `people.py`.
- **D2 — must every leaf engine have `sheet.py` and `panels.py`?** A: yes, always (recommended: every leaf engine then has the same 7 files; tunnelgoons gains two small files). B: only when needed (current CLAUDE.md wording).
- **D3 — pokemon scheme and rival.** A: sub-models in `world.py` (recommended: a class owns its state; the save shape changes). B: keep them as flat fields on `PokemonWorld`.

**Impact.**
- Saves: invalid after D3-A (allowed: saves have no version). The file moves alone do not change saves.
- Prompts: byte-identical. Only the modules change, not the text.
- Tests: many imports change (`from ...world import Mon` and similar, about 15 files across engines). About 10 `world.next_decision()` calls in `tests/pokemon/` change. `tests/pokemon/test_scheme.py` changes with D3-A.
- CLAUDE.md: the engine-package and import-flow bullets are rewritten to the table above.
- Supersedes: the "move prose out of `args.py`" item in "Considered and dropped".

---

## 6. Close the battle simulator on every failure; reuse `StateCache`

**Status: ACCEPTED.**

**In short.** A bug during a battle leaks the Showdown process. Also, a hand-made cache copies `StateCache`.

**Now.**
- `app/session.py:155` and `:168`: `except (Refusal, CancelledError): close; raise`. Any other exception skips the close. The node process stays alive.
- `debriefed: tuple[AnyGame, Debrief] | None` (`session.py:74`, used 190–196) re-implements `StateCache`.

**Change.**
- Use `except BaseException: await transport.close(); raise` (and `_close_battle()` in the second site). It re-raises, so it does not hide a bug.
- Give `StateCache` `get(state) -> T | None` and `put(state, value)`. Use `debriefs: StateCache[Debrief]`.

**Impact.** Fixes a process leak. No other change.

---

## 7. HTTP errors become a `Refusal` in one place

**Status: ACCEPTED — option A (keep the role in the text).**

**In short.** Callers of the provider helpers catch `httpx` errors themselves. One of them also catches non-`Refusal` errors, against CLAUDE.md.

**Now.**
- `app/providers.py:27–47` (`post_bearer`, `stream_bearer`) let `HTTPError` escape.
- `app/api_roles.py:89` catches it and builds a `Refusal` with `_detail` (204–210).
- `app/illustration.py:127` catches `(HTTPError, OSError, Refusal)`.

**Change.** Move `_detail` to `providers.py`. Both helpers turn `HTTPError` into `Refusal` (in `stream_bearer`, wrap the whole `async with ... yield`). `run_over_api` loses its try/except. `illustrate` catches only `Refusal`. The `httpx` imports leave both callers.

**Decision — error text.**
- **A (recommended).** `providers` takes a `label` argument, so the text stays "the master's provider failed: …". Tests unchanged.
- **B.** Generic "the provider failed: …". Tests matching the role name change.

**Impact.** Unexpected `OSError` in illustration now reaches the task callback, which logs it. The player sees no change.

---

## 8. `io.py` holds files only; `validation.py` holds all parsing

**Status: ACCEPTED.**

**In short.** There are several ways to write a model and to parse JSON. Parsing code sits in the file module.

**Now.**
- `write_text(path, x.model_dump_json(indent=2))` appears 5 times in `core/io.py` (53, 153, 156, 161–164, 187).
- `parse_text` (`io.py:224`) has one caller.
- `app/spawn.py` parses JSON lines with `suppress(ValidationError)` + `model_validate_json` (138, 385) and with `suppress(Refusal)` + `parse_json` (146).
- `LINES`, `partial_lines`, `decode`, `routed` live in `io.py` but parse model text. `SOURCE_SUFFIXES` (`io.py:30`) belongs to `core/source.py`.

**Change.**
- Add `write_model(path, model)`. Inline `parse_text` into `read_model`.
- `spawn.py` uses `parse_json` + `suppress(Refusal)` everywhere.
- Move `LINES`, `partial_lines`, `decode`, `routed` to `core/validation.py`. Move `SOURCE_SUFFIXES` to `core/source.py`.
- `routed(raw, by_engine)` calls `decode` itself (both callers do `routed(decode(raw), …)`).

**Impact.** None on features. Test imports change (`test_store.py`, `test_spawn.py`).

---

## 9. Remove duplicate build steps in `app/`

**Status: ACCEPTED.**

**In short.** The app builds the same values twice and decodes one save three times.

**Now / change.**
- `app/roles.py`: SCENARIO and BACKDROP sections are copied in `render_master` (172) and `_picture` (233). "Has play started" is computed three ways. → one `_scenario_sections(state)`; use `len(state.exchanges())`. Pick one style for prompt paths (all constants).
- `app/launch.py`: `LaunchTarget(...)` built twice (142, 165); the scenario map built in `launch.py:81` and `runtime.py:128`. → `LaunchTarget.of(state)`; `check_resumes` returns the target; one `Runtime.scenario_models`.
- `app/runtime.py:55` copies `battle_config`, `transcript_config` and illustrator config into each session. → `GameService.settings: Settings`; `Illustrator.open` calls `.configured(settings)`.
- `config.py:158` repeats the role list. → `get_args(Role.__value__)`.

**Impact.** None on features. `tests/ui/test_game.py:161` sets `transcript_config` and needs an update. Role prompts stay byte-identical (goldens show any drift).

---

## 10. Small duplicates and dead code in the engines

**Status: ACCEPTED — all of a–g.**

**In short.** A group of small cuts. Accept all, or name the ones to drop.

- **a. Duplicate graph search.** `pokemon/world.py:1499` `reached()` copies `rooms/world.py:114` `Dungeon.reachable` plus cut edges. → add `cut=` to `reachable`, delete `reached`. −11.
- **b. `refuse()` helper.** `if refused := x_refusal(...): raise Refusal(refused)` appears 7 times in `pokemon/world.py`. → `refuse(reason)` in `core/validation.py`. −7.
- **c. `_check_proposal` args.** `pokemon/engine.py:270` takes `opening`, `operation`, `boss_id` that it can read from the proposal. Same fan-out in `PokemonWorld.absorb` (898). −8.
- **d. `let_go` duplicates `leave_party`.** `twentyfourxx/engine.py:469` = `Engine.leave_party`. → mark the base `@tool @action`, point the panel option at it, rename the world check to `was_let_go`. −4.
- **e. Shared stranger filing.** `loner4e/world.py:604` and `twentyfourxx/world.py:528` build a stranger from an id the same way. → `SceneWorld.file_stranger(entity_id, brief)`; drop 24XX's `Hiring.file_stranger` hook. −6.
- **f. Dead code.** `World.unmet()` (`entities.py:189`, used only by one test). Two name→id resolvers (`scenes/world.py:335`, `scenes/worldsmith.py:114`) → keep one. `Mon.item_refusal` `case "ball"` and the `"tm"` in `use_item` (`pokemon/world.py:449`, `1170`) never run. −10.
- **g. Tangled conditional.** Six `trainer is None` tests in `setup_battle` (`pokemon/world.py:917–941`) → one `if/else` block. −5.

**Decision.** Accept all (recommended), or list the letters to drop.

**Impact.** No feature change. `tests/twentyfourxx/test_tools.py:669` uses `"let_go"`. A save with a pending `let_go` option becomes invalid (saves are unversioned).

---

## 11. UI: one choice-group helper, shared form code

**Status: ACCEPTED — option A (heading only when there are 2+ groups).**

**In short.** The same "grouped choice buttons" code is written three ways. The two create forms share copied code.

**Now.**
- `ui/game.py:355` (`open_row`), `ui/battle.py:102` (`choices`) and `ui/widgets.py:315` (`decision_options`) each group items and draw `choice_button`s.
- `ui/create.py`: `CharacterForm` and `ScenarioForm` copy `use_engine` (102, 278) and the `engine` property (77, 240). `engine` and `pack` have no return type.

**Change.**
- One `choice_groups(items, pick, *, enabled, row_class)` in `widgets.py`, used in all three places.
- `create.py`: annotate `-> AnyEngine` / `-> Pack`; one free `_first_pack_id(engine)`; private methods at the end of the class.

**Decision — group heading style.** Today the game page shows a heading only when there are 2+ groups; the battle shows a small label when a group is set.
- **A (recommended).** Heading when there are 2+ groups, everywhere.
- **B.** Label whenever a group is set, everywhere.

**Impact.** A small visual change on one of the two pages. No tests assert on markup.

---

## 12. Naming: ids end in `_id`, one descriptive name per concept

**Status: ACCEPTED — option A (all), with the descriptive names below.**

**In short.** CLAUDE.md says an id field ends in `_id`. Some do not. Some concepts have two names or a vague name. Use long, descriptive, human-readable names.

| Now | New name | Where |
|---|---|---|
| `LaunchTarget.slug`, `slug` parameters for a save | `save_id` | `app/launch.py`, `core/io.py`, `app/runtime.py`, `app/illustration.py`, `ui/app.py`, `ui/game.py` |
| `FileStore.slugs()` | `FileStore.save_ids()` | `core/io.py` |
| local `name` holding a scenario id / character id | `scenario_id` / `character_id` | `app/runtime.py:87–98`, `core/io.py:121/127`, `app/launch.py:85–97` |
| class `ScenarioMeta` | `ScenarioDescription` | `core/model.py:19` and all users |
| `Game.scenario` | `Game.scenario_description` | `core/model.py:78` (reads: `state.scenario_description.title`) |
| `Scenario.meta` | `Scenario.description` | `core/model.py:48` (reads: `scenario.description.title`) |
| `Species.evos` | `evolution_species_ids` | `pokemon/dex.py:30`, `showdown/export-dex.js`, `dex.json` |
| `Species.evo_move` | `evolution_move_id` | `pokemon/dex.py:35`, same files |
| `BattleResult.on_field` | `on_field_mon_ids` | `pokemon/battle/models.py:89` |
| `TrainerSheet.caught_species` | `caught_species_ids` | `pokemon/world.py:527` (→ `sheet.py` after P5) |
| `PokemonWorld.encounters` | `encountered_place_ids` | `pokemon/world.py:779` |
| `PokemonWorld.centers`, `PokemonMap.centers` | `center_place_ids` | `pokemon/world.py:758, 778`; worldsmith schema and `WORLDSMITH_GUIDANCE` |
| bare strings `"quiet"`, `"recovery"`, `"dramatic"`, `"meanwhile"`, `"living-world"` | `QUIET_SCENE_REQUEST`, `RECOVERY_SCENE_REQUEST`, `DRAMATIC_SCENE_REQUEST`, `MEANWHILE_REQUEST`, `LIVING_WORLD_REQUEST` | `loner4e/engine.py:134–599` |

**Impact.**
- Old saves become invalid (allowed: saves have no version).
- `dex.json` is regenerated with `showdown/export-dex.js`.
- The pokemon worldsmith schema golden (`tests/core/fixtures/schemas/pokemon/worldsmith_answer.json`) and the `WORLDSMITH_GUIDANCE` text change for `center_place_ids`.
- Tests change with each rename. No gameplay change.

---

## Drastic cuts (all REJECTED)

You reviewed these feature cuts and rejected all of them. Do not implement: drop Tunnel Goons; fold `rooms` into Pokemon; drop the Codex driver; drop all CLI drivers; drop illustration; drop the model opponent; drop document upload; drop the pack editor; drop the debrief; drop the sprite setting; merge the narrator into the master.

---

## Considered and dropped

- Pokemon EXP curve helper `exp_at(level)`, route constants in `ui/`, named magic numbers: correct but add LOC.
- 24XX `record` override → `before_record` hook: small gain, touches the turn flow.
- `except Exception` in `core/source.py`, `app/mcp.py`, `ui/game.py`, `ui/battle.py`: all re-raise or wrap hostile input. Keep.
- Empty untracked dirs `src/rulehall/evals/` and `engines/pokemon/arena/`: delete locally, not in git.

---

## Implementation outcome

**Net src Python:** +2433 / −2573 = **−140 LOC** (the P5 layout adds 6 files; their import headers cost about 95 lines).

**Reverted after review (the change made the code longer or harder to read):**
- P7: the provider `label` plumbing. `run_over_api` keeps one `try/except HTTPError`; `illustrate` catches `(HTTPError, Refusal)`.
- P10g: `setup_battle` keeps its per-field ternaries.
- P9: `LaunchTarget.of` was inlined; `StateCache.read` keeps its 3-line body (`get`/`put` added for debriefs).
- P10f: the merged name resolver. `scenes/world.py` `resolved_ids` refuses again; `scenes/worldsmith.py` keeps its lenient `_resolved_ids`.
- P2 (24XX part): `filed_by_name` as a validator (a validator that returns a copy is skipped on `__init__`). The explicit calls and the `SceneEngine.check_opening` hook are back. The Loner4e part of P2 stays.
- P11: each create form keeps a one-line `use_engine`.

**Deviations:**
- P8: `LINES`/`partial_lines` live in `core/play.py`, and `EngineHeader` in `core/validation.py` (import direction).
- P4: `Block` is an abstract `Frozen` model, not a `Protocol` (pydantic needs a schema).
- P5: `PokemonWorld` is ~580 lines, not ~400: most scheme and rival methods need places and people. The sub-models are `EvilTeam` (`evil_team`) and `RivalRecord` (`rival_record`).
- P10b: the dead `"tm"` branch stays (the type checker needs it for exhaustiveness).
- P11: no `-> AnyEngine` / `-> Pack` in `ui/create.py` (the `ui` layer may not import `engines`).
- P12: player files under `user/` that use `meta`, `centers` or `caught_species` also become invalid, like saves.
