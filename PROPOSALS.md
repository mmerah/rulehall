# Simplification proposals

> **Review closed (2026-10-11).** Accepted: P1–P10 and R1. Not taken: R2–R5. The chosen option is marked on each decision.
>
> **Implementation order** (mechanical moves first, so later diffs stay small; each step keeps `pytest`, `ruff` and `basedpyright` green):
> 1. **P4.** Vocabulary and the move to `engines/bases/{maps,scenes}/`.
> 2. **P10.** Core contract renames.
> 3. **P2 (C).** Flatten engine composition: `join_party` on `Engine`, `PokemonEngine` base, battle support as a component. Regenerate the `master_tools.json` goldens on purpose.
> 4. **P3.** Lifecycle hooks.
> 5. **P1 + the ToolProvider rename from P6.** One tool-call route.
> 6. **P5.** GameSession cleanup and the rewind-after-restart fix (add a regression test).
> 7. **P8 (A).** Make the siblings alike.
> 8. **P9.** Pokémon untangling, including `legendary_person_id` and `UnsavedTeam`.
> 9. **P6 (rest).** BattleSnapshot, ScreenSlot, the TeamBuilding protocol, the flat registry and the banner.
> 10. **P7 (A).** Split the team builder.
> 11. **R1.** One owner for player packs.

Five reviewers looked at the code, each through a different lens: core/app, the non-Pokémon engines, the Pokémon engines, UI/tests/naming, plus one cross-cutting pass. This file merges their findings into the top 10 proposals, ranked by impact. Items that came close are listed under **Runners-up** at the end.

Each proposal has a **Status** line. Where the right choice is not obvious, it ends with a **Decision** that offers 2–3 options. "Golden drift" means a golden test file has to be regenerated on purpose: the model reads the same content, but it may be in a different order.

Baseline: `uv run pytest` gives 785 passed. Nothing here changes game rules.

---

## P1. One path for every tool call a model makes

**Status:** ACCEPTED

**In plain English.** Two kinds of AI role use tools: the game master and the worldsmith. Their tool calls reach the engine by two different routes.
- The worldsmith's call carries a token that names the open submission.
- The master's call carries nothing. The server guesses that it belongs to "whatever game is currently running, then that game's turn".

So to follow one tool call you have to read six files: `mcp`, `game_session` (Gate), `roles`, `submission`, `cli_roles` and `turn`.

**Evidence.**
- `app/mcp.py:88` and `:106`: `gate.turn if token is None else gate.submissions.find(token)`.
- `Gate.turn` and `Gate.require_turn` reach into `admitted.turn` (`game_session.py:555-562`).
- `RoleRunner` has three methods, but `play_master_turn` and `submit_answer` both just call `_play_tools(...)`. The provider `match` block is written out twice (`roles.py:57-65`, `:90-101`).
- `ask()` changes its behaviour based on the role's name: `if role == "worldsmith"` (`roles.py:112`).
- `mcp_token: str | None` branches exist in `cli_roles.py:150` and `:217-221`, only because the master has no token.
- `Submissions` already stores any `ToolSurface`, not only submissions.

**Change.**
- Rename `Submissions` → `OpenToolProviders` (a registry from token to tool provider), and `SUBMISSION_HEADER` → `TOOLS_HEADER`.
- `GameSession._play_master` registers its `Turn` there exactly as the worldsmith registers its `Submission`. Every CLI run gets a token, so `mcp_token` becomes `str`.
- Delete `Gate.turn`, `Gate.require_turn` and `NO_TURN`.
- `RoleRunner` shrinks to `answer(role, prompt, heard)` and `play_tools(role, prompt, provider)`. One private `_run(...)` holds the single `match config.provider`. The one-time CLI nudge for a missing submit stays, inside a small `submit()` helper.
- Split `ask` into `ask_by_submission` (worldsmith) and `ask_with_retry` (the other roles). `role_answer(runner, role)` picks between them.

**Size.** About 6 source files (mcp, roles, submission, cli_roles, game_session, runtime) and 4 test files (`support/table.py`, test_mcp, test_roles, test_api_roles). About 150 lines, net −40.

**Feature impact.**
- Prompts, saves and goldens: none.
- A master tool call without a token is now refused. This also closes a small hole: today any local client can drive the open turn.
- The refusal text for "no tools open" changes wording.

**Risk.** Low to medium. test_mcp covers routing.

---

## P2. Flatten how engines are put together (mixins, generics, the battle check)

**Status:** ACCEPTED — Decision C (core + `PokemonEngine` base + battle support as a component)

**In plain English.** The first line a newcomer reads in an engine is its class header, and it is the hardest line to read.
- TunnelGoons inherits from `Hiring[Goon, TunnelGoonsWorld, TunnelGoonsPack, RegionProposal[Goon], AbilitiesProposal], RoomEngine[Goon, TunnelGoonsWorld, TunnelGoonsPack, RegionProposal[Goon]]`.
- 24XX has three bases with 10 type arguments.
- The behaviour of a tool depends on the order of these bases.

**Evidence.**
- There are two mixin styles. `Revealing` and `Joining` are plain classes (`engine.py:86-100`). `Hiring` and `ShowdownBattling` subclass `Engine` and repeat its 4–5 type parameters.
- Every engine takes exactly one of `Joining` or `Hiring`. A comment enforces this (`engine.py:94`).
- `door_id` and `mode_name` are properties that return a constant. Journey sets `id = DOOR_ID`; Champions overrides the property. That is two ways to do one thing.
- "Is this engine in a battle?" is asked in 7 places. The answer goes through a free function, which runs `isinstance` against a `@runtime_checkable` Protocol and returns a `TypeGuard` (`engines/battles.py`). There is exactly one implementation. `BattleRun[G]` is generic, but `G` is always `AnyGame`.
- Journey and Champions repeat the same triple base plus `title`, `art_style`, `portraits` and `door_id`.

**Change (core of the proposal).**
- Move the plain `join_party` onto `Engine` and delete `Joining`. `Hiring.join_party` already overrides it with a subclass argument (`HireOrJoin`), so the existing override check still passes.
- Keep `Revealing`. Loner4e has no hidden things and must not get a `reveal` tool.
- Turn `door_id` and `mode_name` into plain class attributes.
- Add `Engine.in_battle(state) -> bool` (default `False`; `ShowdownBattling` overrides it). Call sites become `engine.in_battle(state)`. Keep the `Battling` protocol for the single `open_battle` call. Make `BattleRun` non-generic.

**Feature impact.** In the `master_tools.json` goldens for loner4e, journey and champions, `join_party` moves earlier in the tool list. This is golden drift: the model sees the same tools in a different order. No behaviour change.

**Risk.** Low.

**Decision P2: how far to go?** → **Chosen: C.** Battle support becomes a component (`Engine.battles: BattleSupport | None`), which replaces the `Engine.in_battle` override from the core change. The app checks `engine.battles`, or calls a thin `Engine.in_battle` that delegates to it.
- **A. Core only (recommended):** the bullets above. About 60 lines.
- **B. A, plus a `PokemonEngine` base.** It absorbs `ShowdownBattling`, `Joining` and `RoomEngine`, and holds the shared Pokémon class attributes. Journey and Champions headers become one base. About 120 lines.
- **C. B, plus battle support as a component.** `Engine.battles: BattleSupport | None` replaces the `ShowdownBattling` base class entirely: composition instead of inheritance. This is the biggest simplification of the headers, but `surfaces`/`assets` then need a small hook. About 200 lines, medium risk.

---

## P3. Name the engine's "after a change" hooks by when they run

**Status:** ACCEPTED — Decision A (24XX keeps its pending timing in `before_log_entry`)

**In plain English.** An engine has three hooks that run after the state changes, at three different moments. Their names don't say when they run. Two engines also override `accept`, the method that checks the state, and use it to change the state. On top of that there are three different checking names: `accept`, `validate` and `validated`. A newcomer cannot tell where something like "derive the pending decision" belongs.

**Evidence.**
- `Engine.accept` (`engine.py:416`) runs after every tool call and every save.
- Champions (`engine.py:265`) and Journey (`engine.py:281`) override `accept` to set `draft.pending`.
- 24XX sets `draft.pending` in `before_record` instead (`twentyfourxx/engine.py:187`).
- Rooms and loner4e use `end_turn(acted=)`, which runs only when the master played.
- `before_record` and `end_turn` are no-op bases with `# noqa: B027`.
- `Engine.validate` is never overridden.

**Change.**
- `accept` stops being overridable. It does `self.after_each_change(draft); self.check_state(draft); return draft.validated()`.
- Rename the hooks:

  | Before | After | Runs |
  |---|---|---|
  | (new) | `after_each_change` | after every change; the Pokémon pending logic moves here |
  | `before_record` | `before_log_entry` | before a turn is logged |
  | `end_turn` | `after_master_turn` | only after a master turn |
  | `validate` | `check_state` | inside `accept` |

- Add one docstring on `Engine` that lists the order.

**Size.** engine.py, 2 Pokémon engines, rooms, loner4e, 24XX, `Turn.finish`. About 40 lines.

**Feature impact.** None, as long as each hook keeps its current timing.

**Risk.** Low.

**Decision P3: should 24XX's pending decision also move to `after_each_change`?** → **Chosen: A.**
- **A. No, keep it in `before_log_entry` (recommended).** No behaviour change.
- **B. Yes.** One rule for every engine, but 24XX's decision would then appear right after a tool call instead of at log time. That is a small behaviour change, kept only if the tests show it doesn't matter.

---

## P4. One vocabulary for "rule set / mode / shared base"

**Status:** ACCEPTED — Decision B (move the bases to `engines/bases/{maps,scenes}/`)

**In plain English.** Several words mean the same thing, and one word means two things.
- The README says "rule sets" and "modes". The code says "door" (`door_id`, `door_engines`, `pokemon/door.py`), a home-page picture that leaked onto the engine base class.
- "Family" means two things. `Engine.family_dir` points at the shared `rooms/` or `scenes/` base, while the boundary test calls each engine package (loner4e, pokemon…) a "family".
- The `rooms` base has no rooms. Its prose and most of its types talk about maps, places and regions (Place ×50, MapProposal ×27), but the base is `RoomWorld`/`RoomEngine`.
- `SceneHeader`/`scene_header` is used by map engines too, while "scenes" is the name of the other base.

**Change** (pure renames, no logic):

| Before | After |
|---|---|
| `engines/rooms/` | `engines/maps/` |
| `RoomEngine`, `RoomWorld` | `MapEngine`, `MapWorld` |
| `RoomMap` | `MapContents` |
| `Engine.family_dir` | `Engine.base_dir` |
| `door_id`, `door_engines` | `rule_set_id`, `modes_of(rule_set_id)` |
| `pokemon/door.py`, `DOOR_ID` | `pokemon/rule_set.py`, `RULE_SET_ID` (the word "door" stays inside `ui/home.py`) |
| `SceneHeader`, `scene_header` | `ViewHeader`, `view_header` |
| `FAMILIES` (boundary test) | `ENGINE_PACKAGES` |

- Add a short glossary to CLAUDE.md: engine, rule set, mode, base, panel, screen, decision, option, request, resolution, fact, trace, card, told.

**Size.** About 30 files, mechanical.

**Feature impact.** None. Class names never reach prompts (the schema `title` is stripped) or saves. `EngineId` values and routes stay the same.

**Risk.** Low.

**Decision P4: where do the two shared bases live?** → **Chosen: B.** Paths become `engines/bases/maps/` and `engines/bases/scenes/`. Update the boundary test and every import of `rulehall.engines.rooms` / `rulehall.engines.scenes`.
- **A. Rename in place (recommended):** `engines/maps/`, `engines/scenes/`.
- **B. Also move them under `engines/bases/{maps,scenes}/`.** Shared bases would then stop sitting next to the real engines, which is why the rule "sibling engines hold the same files" looks false today. It adds more import churn.

---

## P5. GameSession: one undo record (fixes a bug), Gate in its own file, plain verbs

**Status:** ACCEPTED — Decision A (all 5 steps, including the `choose` routing table)

**In plain English.** `GameSession` (580 lines) keeps two separate "undo" concepts, and they stay valid in two different ways.
- One is checked by identity.
- The other is cleared by hand in scattered places, and one place is missed. **Bug, confirmed in the code:** `restart()` never clears `rewind_point`. After a restart, the Rewind button can bring back the game the player was just told was erased.

Its core methods also use metaphor verbs that hide what they do: `present`, `_land` and `_settle`.

**Change.**
1. **One undo record.** Replace `Rewind` and `EditUndo` with `last_change: Change | None`, where `Change(before, after, words: str | None)` and `words=None` means an edit. Rewind and undo are allowed only when `last_change.after is self.state`. All the hand-written `rewind_point = None` lines go away, and the restart bug goes with them.
2. **Gate in its own file.** Move `Gate` and `Busy` to `app/gate.py`.
3. **Clearer routing in `choose`.** Add a pure `_route(answer) -> Silent | IntoTurn | PlainTurn`, and make `choose` a `match` over it. The five nested-`if` paths become a table you can unit-test.
4. **Drop pass-throughs.** `find_clip`, `clip_refused`, `speak_later` and `transcribe` only forward to `self.speaker`. The UI uses `session.speaker` directly (2 UI files).
5. **Plain verbs:**

   | Before | After |
   |---|---|
   | `present` | `illustrate_later` |
   | `_land` | `_narrate_and_record` |
   | `_settle` | `_save_battle_progress` |
   | `_narrated` | `_narrate` |
   | `_write_request` | `_grow_world` |
   | `memo`, `_memo` | `view_cache`, `_cached_views` |
   | `stores.publish` | `write_atomically` |
   | `Illustrator._draw` | `_generate_scene` |

**Size.** game_session.py, new gate.py, mcp/runtime imports, 2–3 UI files. About 150 lines, net −30.

**Feature impact.** Fixes the rewind-after-restart bug. Nothing else changes. Note texts must stay byte-identical, because the goldens pin them.

**Risk.** Low for steps 1, 2, 4 and 5. Medium for step 3: the silent/pending/unnarrated conditions are subtle, and `test_game_session` and `test_decisions` must stay green.

**Decision P5: include step 3 (the `choose` routing table)?** → **Chosen: A.**
- **A. Yes (recommended).** It is the hardest method to read in the app layer.
- **B. No, do steps 1, 2, 4 and 5 only.** Lowest risk.

---

## P6. One clear path from engine to screen

**Status:** ACCEPTED

**In plain English.** Engine-specific screens get their data in two different ways.
- The team builder reads `Surface.view`.
- The battle ignores it (`view=None`) and reads four loose `battle_*` fields on `SessionSnapshot`.

The word "surface" also means two things: a UI screen slot (`core.views.Surface`) and the tool protocol (`ToolSurface`).

One real layering break: the team builder screen imports `ChampionsWorld` and pulls it out of `session.state.world` (`screens/pokemon/team_builder.py:1212`). CLAUDE.md says the layers above the engines must not know the shape of a world, and this is the only place that does.

There is also a two-level screen registry built for "many families" when only one exists, and a 15-line banner copied into both screens.

**Change.**
- Group the four `battle_*` fields into `battle: BattleSnapshot | None` (fields `run`, `log`, `facts`, `view`).
- Rename `ToolSurface` → `ToolProvider`. This matches P1's `OpenToolProviders` registry; do both together.
- Rename the UI side: `Surface` → `ScreenSlot`, `surface_id` → `screen_id`, `ui/surfaces.py` → `ui/screen_host.py`.
- Fix the layering break. Add a small `TeamBuilding` protocol (`team_catalog`, `team_import_preview`, `team_export_text`), which `ChampionsEngine` implements by calling its existing functions, and which the screen uses through the session. This follows the existing `Battling` pattern. The catalog cache keys on the state rather than on world identity.
- Merge `screens/pokemon/registry.py` into `screens/registry.py` as one plain dict, and drop `build_screen_factories`.
- Extract the shared `screen_banner(...)` helper.

**Size.** About 250 lines, mostly type-checked renames (about 110 references for `Surface`).

**Feature impact.** None. No save, prompt or golden changes.

**Risk.** Low. The team-builder catalog cache invalidation needs care.

---

## P7. Split the 1,310-line `TeamBuilderScreen`

**Status:** ACCEPTED — Decision A (three component classes, after P6)

**In plain English.** One class does everything:
- layout
- the slot rail
- the slot editor
- four dialogs
- keyboard shortcuts
- the undo toast
- tab storage
- running edits

It has about 45 widget attributes and about 70 methods. To read one feature you have to read the whole file. The codebase already shows the fix: `CatalogPicker` and `PointsEditor` are pulled out of it.

**Change.** `TeamBuilderScreen` stays as the shell. It keeps build, sync, the edit, play and undo actions, storage, the keyboard handlers and the selected slot. Three parts move out:
- `team_dialogs.py`: `TeamDialogs` (import with preview/replace, export, keys and replace-move dialogs, plus `is_open()`).
- `slot_editor.py`: `SlotEditor` (draw_editor/pick/moves/pinned and move drag-and-drop; it owns the `PointsEditor`).
- `team_rail.py`: `TeamRail` (cards, card menu, status, item, slot drag-and-drop).

Each part takes callbacks (`edit`, `confirm`, `find_asset`) instead of the whole screen. Do this **after P6**, so the parts never touch `ChampionsWorld`.

**Size.** About 1,300 lines moved, about 100 lines of new glue, 3 new files.

**Feature impact.** None. CSS classes and DOM stay the same.

**Risk.** Medium. NiceGUI `@ui.refreshable_method` must stay on the object that owns the drawn state. Test imports (`moved`, `picked_ids`) need updating.

**Decision P7: how deep?** → **Chosen: A.**
- **A. Three component classes, as above (recommended).**
- **B. Dialogs only, as one class.** The dialogs are the most separable part, so this gets most of the clarity for a third of the work.

---

## P8. Make the sibling engines actually alike

**Status:** ACCEPTED — Decision A (rename only). After P4, paths read `engines/bases/maps/` where this says `rooms/`.

**In plain English.** CLAUDE.md says sibling engines hold the same files with the same roles. Mostly true, but the same job is done in different ways from engine to engine.

**Evidence.**
- **Five extension mechanisms for "setup, then add my extras".**

  | Where | Mechanism |
  |---|---|
  | rooms | a `starting_items` hook, used only by tunnelgoons |
  | rooms opening | `**extra_fields`, used only by Pokémon |
  | loner4e | `apply_scene_extras`, applied twice |
  | 24XX and Journey | `apply_opening_extras` |
  | Champions | `install_event` |
- **Rules logic sits on engine classes.**
  - 24XX `build_sheet` and its helpers: about 75 lines of creation rules. `_chosen` raises but is not called `require_…`.
  - 24XX `_item_lines` renders the world.
  - loner4e `_grow` only changes `world.grown`.
- **Request kinds are named inconsistently.** These slugs are stored in saves, but they are spread across `panels.py`, `engine.py` and `hiring.py`, some with a `_REQUEST` suffix and some without. Rooms keeps 7 prompt strings in `args.py`.
- **Scenes hooks don't fit their users.**
  - Both `lead_panels` implementations re-add the party panel.
  - `sheet_help` round trip: it is defined in `panels.py`, put on the engine class, then passed back into the same module.
  - Two `narrator_view` overrides exist only to append text.
- **Boilerplate repeats.** `grown_character` is the same in two engines, and numbered-pick ids (`item-1`, `skill-2`…) are rebuilt by hand in 3 places.

**Change.**
- Give one name to each extension point: `apply_opening_extras(proposal)` and `apply_next_extras(proposal) -> list[Fact]` on every world. Delete `starting_items`.
- Move rules onto their owners:
  - `SheetProposal.build_sheet(...)` for 24XX.
  - `TwentyFourXXWorld.gear_lines` for 24XX.
  - `Loner4eWorld.grow` for loner4e.
  - `_chosen` → `require_offered_option`.
- Request kinds: `*_REQUEST` constants in each engine's `world.py`, with the same string values. The rooms prompt strings move to `rooms/engine.py`.
- `SceneEngine.scene_panels` adds the party panel itself, and `sheet_panel` reads its own `SHEET_HELP`.
- Add `Engine.character_of(..., character_id=)` and `core/creation.numbered_picks`.

**Size.** About 250 lines across the 5 engines.

**Feature impact.** None, as long as panel order and narrator text stay byte-identical. The golden turn tests will catch any drift.

**Risk.** Low to medium.

**Decision P8: how should the extension points be wired?** → **Chosen: A.**
- **A. Rename only (recommended first step).** Each engine still calls its extras itself, but under the same names. Low risk.
- **B. Template methods.** The bases call no-op `apply_opening_extras`/`apply_next_extras`, which deletes 5 engine overrides. Medium risk: loner4e must apply its extras *before* the scene, and 24XX emits its facts *before* the scene's facts.

---

## P9. Untangle the Pokémon modules

**Status:** ACCEPTED — P9: A (rename to `legendary_person_id`); P9b: A (`UnsavedTeam`/`UnsavedSet`)

**In plain English.** The Pokémon code is the newest and largest part of the codebase (13.5k lines). The battle package (header, history, choices, preview…) is clean. The rest has overloaded functions, mixed modules, and one name used for two things.

**Evidence and change.**
1. **Journey battle setup.**
   - `setup_battle` takes 7 arguments and infers wild, legendary, trainer, double or tag from which arguments are `None`. The three ways to start a battle are spread over the engine and the world.
   - **Change:** give the world three explicit entry points, `start_wild_battle`, `start_legendary_battle` and `start_trainer_battle`. They share one private setup. Split the 54-line `settle_battle`.
   - **Naming bug:** `Battle.legendary_id` holds an *npc id*, while every other `legendary_id` holds a *species id*.
2. **`battle/opponent.py` (850 lines) holds two things.**
   - It mixes the model prompt with the scripted AI that plays without a model.
   - **Change:** move `greedy_choice`, `advised_switch`, the switch helpers and the thresholds into `battle/tactics.py`. The prompt stays byte-identical.
3. **Journey-only code sits in shared modules.**
   - `dex.py` holds the 70-entry `ITEMS` shop table.
   - `sprites.py` holds `look_step` and the move text helpers.
   - `journey/sheet.py` (892 lines) holds a 330-line `Mon`.
   - **Change:** new `journey/items.py` and `journey/mon.py`, and move `look_step` to `trainers.py`.
4. **Champions unsaved team.**
   - The lock checks use three different names between the world and the view (`team_lock`→`save_lock`, `pending_team_lock`→`locked_reason`, `copy_lock`→`copyable`). **Change:** one vocabulary, `edit_lock`, `save_lock` and `copy_lock`, in both places.
   - `field_id` can only ever be `"sp"`. **Change:** drop it and its guard.
   - `allowed_species_ids` is threaded through every method (54 uses). **Change:** store it once on the team.
   - The same legality check is written twice. **Change:** reuse one copy.
5. **One name, one meaning.**

   | Before | After |
   |---|---|
   | `companion` / `ally` / `partner` (the tag partner) | `ally` |
   | `Outcome` in `journey/scheme.py` (defined twice) | `OperationOutcome` |
   | `species_pool` | `species_ids` |
   | simulator: `asks` | `requests_by_side` |
   | simulator: `said` | `chat_lines` |
   | simulator: `Dump` | `Snapshot` |
   | simulator: `Hand` | `TeamPositions` |

**Size.** About 900 lines moved and touched, mostly mechanical.

**Feature impact.** None on prompts or tools: the tool argument `tag` and the saved `BattleSetup.ally` stay.

**Risk.** Low for items 2, 3 and 5. Medium for items 1 and 4 (good test coverage exists).

**Decision P9: rename `Battle.legendary_id` → `legendary_person_id`?** → **Chosen: A.**
- **A. Yes (recommended).** It removes a real trap. Any save made in the middle of a legendary battle becomes invalid; per CLAUDE.md, saves have no version.
- **B. No.** Keep the field and add a comment on it.

**Decision P9b: the name for `PendingTeam`/`PendingSet`?** → **Chosen: A (`UnsavedTeam`/`UnsavedSet`).** "Pending" already means `Game.pending` (a decision).
- **A. `UnsavedTeam`/`UnsavedSet` (recommended).**
- **B. `DraftTeam`/`DraftSet`.** But "draft" already means a game draft everywhere.
- **C. Keep `Pending…`.**

---

## P10. Core contract names a newcomer can guess

**Status:** ACCEPTED

**In plain English.** A few central core names describe the wrong thing, or collide with another meaning. Each one costs a newcomer a lookup.

**Change** (renames and moves only):

| Before | After | Why |
|---|---|---|
| `MasterTool` (21 refs) | `ToolSpec` | also describes the worldsmith's `submit` tool, actions and edits |
| `DecisionOption` | `Option` | the base option class; `ActionOption` stays its subclass |
| `Engine.moves` / `PlayerView.moves` | `standing_options` | collides with real Pokémon moves |
| `Engine.published` | `offered_tools` | it returns the tools offered now |
| `Loner4eEntity` | `Loner4ePerson` | it fills `person_model`, like its siblings |
| `World.hear` | `meet_people_named` | a no-op everywhere except 24XX, where it does exactly that |
| scenes `find_entity` (fuzzy match) | `find_by_id_or_name` | the rooms base has a `find_entity` that is exact |
| two different `GAME_OVER` constants | `GAME_OVER_FOR_PLAYER` / `GAME_OVER_FOR_MASTER` | one is for the player, one for the model |
| `facts_carried_from_last_turn` and `Game.unnarrated` | `unnarrated` | the same list under two names |
| `find_option`, `other_than` (in `creation.py`), `unique_options` (in `packs.py`) | move to `core/decisions.py` | next to `Option` |
| `NarratorView` (in the UI-models module) plus `Line`/`Narration` (in `log.py`) | new `core/narration.py` | "what can the narrator see?" lands in one file |
| `EngineHeader`, `for_engine_of` (in `validation.py`) | move to `core/game.py` | next to `CharacterHeader` |
| `map_layout.Line` | `Segment` | collides with `core.log.Line` |

**Size.** About 300 sites, all type-checked, across about 40 files.

**Feature impact.** None. Saved field names (`Decision.options`, `action_name`) do not change. The narration schema golden should not change; run the golden test to confirm.

**Risk.** Low.

---

## Runners-up (not in the top 10, could be promoted)

- **R1. Player packs get one owner.** **(PROMOTED — ACCEPTED)** Today three places in two layers handle player packs: `read_packs`, `core/stores.PackStore` and `Engine.install_pack`, which rewrites a frozen `PackSet` with `replace`. **Change:** make `PackSet` a mutable state class with `new_id`, `path` and `write`, and delete `PackStore` and `install_pack`. About 50 lines.
- *(not taken)* **R2. Test helpers with the same names in every engine.** The started-game helper is called `initialized`, `small_world` or `started`, depending on the engine. `support/game.py` is actually the Loner helper module. `change()` calls a tool (142 call sites). **Change:**
  - `support/loner4e.py`
  - `new_game()` everywhere
  - `change` → `call_tool`
  - `refused` → `tool_refusal`
  - `run_action` → `play_action`
  - goldens move to `tests/goldens/`
- *(not taken)* **R3. Boundary test that scans prose.** `test_shared_modules_name_no_engine_concept` regex-searches whole files for words like "slot" and "team", and survives on an allow-list of phrases. An ordinary comment can fail CI. **Change:** scan identifiers only, via `ast`.
- *(not taken)* **R4. QA harness readability.** About 550 one-letter `s.` uses, `qa/s_*.py` file names, 14 `sys.path` hacks, and helpers named `text`, `still` and `clean`. **Change:** `QaRun` and `qa`, `qa/scenarios/`, run as modules, verb names.
- *(not taken)* **R5. `ui/widgets.py` is a grab bag.** It mixes static files, error handling, toasts, chrome and sound. **Change:** split it into `page.py`, `notify.py` and `media.py`. Also, `transcript.show_*` actually draws, so rename those methods to `draw_*`.

## Considered and rejected

- **Removing the `Engine[P, W, K, R]` generics:** they carry real typing. Packs are typed, and `check_next`/`install_next` stay valid overrides.
- **A deeper split of `Engine` into smaller classes:** the template-method shape *is* the plug-in contract. Splitting it adds indirection.
- **Replacing the `@tool`/`@action`/`@edit` registries:** they are compact, and their override check is useful.
- **Merging the per-genre pack Body classes:** their field descriptions are deliberate per-genre prompt text.
- **Removing the 75 unused `_rng` parameters:** the uniform `(draft, args, rng)` signature is simpler than having the dispatcher inspect signatures.
- **Splitting `core/validation.py`:** 177 importers, too much churn for little gain.
