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


## Proof gate: every change must prove it is simpler

A change is kept only if it measurably meets its **Proof** line (listed under each proposal). Otherwise it is **reworked once**, and **reverted** if it still fails. Each proposal is one commit, so a revert is clean.

**How it is measured.** `metrics.py` (an AST script, kept in the session scratchpad) is run on `src/rulehall` before and after each commit. It reports code lines (no blanks or comments), classes, functions, protocols, base classes, type parameters, functions over 40 lines, and classes over 300 lines. On top of that come the proposal-specific counts named in each Proof line (greps, file sizes, hops a reader must follow). Every commit must also keep `pytest`, `ruff check`, `ruff format --check` and `basedpyright` green, and an adversarial `reviewer` agent reads each diff against its Proof line.

**Baseline (before any change):**

| Metric | Value |
|---|---|
| Code lines (src) | 25,663 |
| Classes | 424 |
| Functions | 2,097 |
| Protocols | 11 |
| Base classes | 377 |
| Type parameters | 40 |
| Functions > 40 lines | 33 |
| Classes > 300 lines | 13 |
| Largest class | `TeamBuilderScreen`, 1,055 lines |
| Concrete engine headers | 13 bases, 42 type arguments |

**Rules for a rename-only proposal** (P4, P10). A rename cannot reduce lines, so it must prove two things:
- (a) **Zero logic change.** `git diff -M` shows only renames and moves, and the goldens are unchanged unless the proposal says otherwise.
- (b) **Each old ambiguous meaning is gone.** A grep shows that the old word now has exactly one meaning, or no hits at all.

**Running total.** The goal for the whole programme is **fewer code lines, fewer classes and fewer base classes/type parameters than the baseline**. A split (P7) may add a few lines, but only if the size of the largest unit drops by the amount its Proof line names.

---

## P1. One path for every tool call a model makes

**Status:** ACCEPTED

**Proof:** Files a reader must open to follow one master tool call: 6 → ≤ 4. `RoleRunner` methods: 3 → 2. `match config.provider` blocks: 2 → 1. `if role ==` branches in `roles.py`: 1 → 0. `str | None` token branches: 0 left. Net src code lines ≤ −30.

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

**Proof:** Concrete engine headers: 13 bases / 42 type arguments → ≤ 7 bases / ≤ 20 type arguments. `Joining`, the `@runtime_checkable` `Battling` check and the `TypeGuard` are deleted. Base classes and type parameters (metrics) both go down. Net src code lines ≤ 0. Golden change: only the `join_party` position in `master_tools.json`.

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

**Proof:** `def accept` overrides: 3 → 1 (the base only). `# noqa: B027`: 2 → 0. Every hook is named after its timing, and one docstring lists the order. Net src code lines ≤ +10 (the docstring). Goldens unchanged.

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

**Proof:** Rename rules (a) and (b). Afterwards: "door" appears only inside `ui/home.py`; "family" has one meaning; the maps base contains no `Room*` identifiers. Goldens unchanged.

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

**Proof:** The rewind-after-restart regression test fails before and passes after. Undo concepts: 2 → 1. Hand-written `rewind_point = None` clears: 4 → 0. Speaker pass-through methods: 4 → 0. `game_session.py`: 580 → ≤ 520 lines (including the code moved to `gate.py`, the net is still negative). `choose` nesting depth goes down, and `_route` gets a table test.

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

**Proof:** `.state.world` reads above the engines: 1 → 0. `battle_*` snapshot fields: 4 → 1. Screen registry files: 2 → 1. Copied banner blocks: 2 → 1. Net src code lines ≤ 0.

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

**Proof:** Largest class: 1,055 → ≤ 450 lines. No part receives the whole screen, only callbacks. New glue ≤ 100 lines; if the glue grows past 150 lines, rework or revert to Decision B.

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

**Proof:** Distinct extension-point names for "setup + extras": 5 → 2. `twentyfourxx/engine.py` 681 → ≤ 600 lines; `loner4e/engine.py` 684 → ≤ 670. Hand-written numbered-pick loops: 3 → 0. Net src code lines ≤ 0. Goldens unchanged.

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

**Proof:** `setup_battle` (77 lines, 7 arguments) is gone, and no new battle-start function is over 40 lines. `opponent.py` 850 → ≤ 650. `journey/sheet.py` 892 → ≤ 600. `allowed_species_ids` references: 54 → ≤ 15. Two `Outcome` classes → one. Net src code lines ≤ 0. Prompt goldens unchanged.

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

**Proof:** Rename rules (a) and (b). In particular: `moves` no longer names player options; one `GAME_OVER` per meaning; no type named `Line` outside `core`. Goldens unchanged.

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

- **R1. Player packs get one owner.** **(PROMOTED — ACCEPTED)** Today three places in two layers handle player packs: `read_packs`, `core/stores.PackStore` and `Engine.install_pack`, which rewrites a frozen `PackSet` with `replace`. **Change:** make `PackSet` a mutable state class with `new_id`, `path` and `write`, and delete `PackStore` and `install_pack`. About 50 lines. **Proof:** `PackStore`, `Runtime.packs` and `install_pack` are deleted, and the frozen-`replace` write is gone. Pack-folder owners: 3 → 1. Net src code lines ≤ −15.
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

---

# Part 2: Deletion proposals (D1–D10)

Three more reviewers looked only for things to delete: dead code, over-built features, and duplication plus tests.

**The honest finding first.** There is almost no dead code. Four scans (vulture, a token count of every defined name, project-wide references, AST checks for parameters and fields) found about 50 deletable lines in total. Copy detection found 0.11% duplicated code. So the real deletions are **features and mechanisms that are built bigger than the app needs**. Those are product calls, and each one says plainly what disappears for the player.

The proof gate applies here too. **Proof** for a deletion means the named code is gone, the stated line count is reached (within 20%), the remaining tests stay green, and nothing outside the stated feature impact changes.

---

## D1. Speech: keep "tap a line to hear it", drop the rest

**Status:** pending

**What exists today:**
- `voices.json` (1,070 lines): a hand-graded voice catalogue for **7** interchangeable text-to-speech models.
- `voices.py` (80 lines), which loads that catalogue.
- `SpeechConfig` checks (`config.py:75-111`) and a voice list on the settings page.
- A microphone with transcription: `Speaker.transcribe`, `Composer._build_mic` / `_hear`, about 50 lines of recording JS, and its CSS.
- An auto-read queue: `VoicePlayer.hear` / `drain` with timeouts, `Transcript.take_unheard` / `finished_bubbles` / `withdrawn` (tangled up with streamed narration), the "Speaking" pill, and the auto-read button with its `tick()` hookup.

The MiniMax HD entry in `voices.json` is an exact copy of the Turbo entry: 45 shared voice ids, 237 duplicated lines.

**Why it is over-built.**
- Speech is off by default.
- Six of the seven models only change which vendor reads the line.
- The auto-read queue is the most stateful code in the UI.

**Decision D1:**
- **A. Delete speech entirely: about −1,900 lines.**
  - The `Voice` type also goes: the `voice` field on every person, the picker on the new-character form, and the `voice` argument of the `enter` tool.
  - Golden drift in 7 schema files.
  - The shipped characters and scenarios must drop their `voice` key.
  - **Every user-made character becomes unreadable** (`extra="forbid"`).
- **B. One fixed model, tap-to-read only: about −1,500 lines** (about 1,100 of it data). **Recommended.**
  - Removed: the catalogue, the narrator-voice/model/transcription settings, the microphone, auto-read and the Speaking pill.
  - Kept: `Speaker.speak`, a smaller `VoicePlayer`, and the `voice` field.
  - For the player: no choosing a TTS vendor or narrator voice, no dictating input, no auto-read.
- **C. Only remove the duplicate HD entry** (`voices_of` alias, or drop HD): about −230 lines, no feature change.

**Proof:** for B, `voices.json` and `voices.py` are gone, and the microphone/auto-read code has 0 grep hits. src lines −400 or more (excluding data), and test lines go down too.

---

## D2. The model-played Pokémon opponent

**Status:** pending

**What exists today:**
- About 720 of the 850 lines in `battle/opponent.py` exist only to prompt a model: prose, `opponent_system`, `render_opponent`, `check_commands`, `switch_advice` and about 30 render helpers.
- The scripted AI that plays without a model is about 130 lines.
- `preview.py:78-152` is a team-preview prompt.
- The simulator runs think-ahead tasks (the `thinking` dict) and has a model branch in `_decide` (about 60 lines).
- An `"opponent"` role, the `pokemon.opponent` setting, and the `ask_opponent` plumbing.
- About 8 of 18 tests in `test_opponent.py`, plus 3 prompt goldens. The Champions opponent golden alone is 264 lines, which is the prompt sent **on every battle turn**.

There are three opponent policies (random, scripted, model), plus a setting that forces scripted, plus an ally that always uses the model. The scripted fallback is already tested, because a model that hangs falls back to it.

**Feature impact of deleting it.**
- Gym leaders, the rival, key trainers, every Champions opponent and tag allies all play the scripted greedy-plus-switch AI.
- Opponents lose their in-battle chat lines.
- Battles stop making one model call per turn (up to 30 s each).
- **Champions opponents will feel weaker.**
- The README advertises "the fourth role".

**Decision D2:**
- **A. Delete the model opponent: about −900 src and −600 test/golden lines.** P9 item 2 then becomes "`opponent.py` shrinks to tactics".
- **B. Keep the model, drop the extras:** the team-preview prompt (use the scripted preview), the think-ahead tasks and the `pokemon.opponent` setting. About −300 lines. **Recommended if you value opponent strength.**
- **C. Keep it as it is.**

**Proof:** for A, the `"opponent"` role is gone from `config.Role`, `opponent.py` is ≤ 200 lines, and battle tests stay green with the scripted AI. For B, `preview.py` has no prompt, `thinking` has 0 hits, and there is no `pokemon.opponent` setting.

---

## D3. In-app "New pack" writer overlaps "write a scenario from a document"

**Status:** pending

**What exists today:**
- `PackForm` and `packs_page` (`ui/create.py:365-427`).
- `Engine.write_pack`, which asks the worldsmith **twice** (head, then body).
- `Runtime.new_pack`.
- The `PackHead`/`PackBody` bases, plus a Head/Body pair in each of the 5 engines (about 150 lines).
- `HEAD_ASK`, `BODY_ASK`, `PACK_SO_FAR` and `PackStore`.
- `test_pack_authoring.py` (125 lines).

That is about 350 src and 150 test lines in total. The scenario form already takes a premise or a PDF/Markdown file and has the worldsmith write the setting, so there are two model-driven ways to bring your own setting.

**Feature impact:**
- There is no in-app pack writer any more.
- Hand-written pack JSON in the player's `packs/` folder still loads.
- Shipped packs (12 for Loner) are unchanged.

**Decision D3:**
- **A. Delete the pack writer: about −500 lines.** R1 then shrinks to "read player packs".
- **B. Keep it, with one worldsmith ask instead of two.** This deletes the Head/Body split in 5 engines: about −200 lines.
- **C. Keep it.**

**Proof:** for A, `write_pack`, `PackHead`, `PackBody`, `PackForm`, `new_pack` and `PackStore` all have 0 hits, and the shipped packs still load. For B, the per-engine Head/Body classes have 0 hits.

---

## D4. Team builder: drop the extra input layers (do this before P7)

**Status:** pending

**What exists today:**
- `KEY_MAP` (19 bindings) and a keys dialog.
- `pressed()`, `shortcut()`, `swiped()` and `open_keyed_field`.
- `team_builder_input.js` (64 lines: Ctrl shortcuts, focus restore, swipe).
- Drag-and-drop for slots and for moves.
- An "Expert" toggle that **writes to `.env` from inside the screen** and doubles the stat-points UI.

That is about 250–300 lines of Python, JS and CSS.

A slot can be reordered **three ways**: drag-and-drop, Alt+↑/↓, and the card menu's Move up/down. Reordering moves within a set is cosmetic.

**Decision D4:**
- **A. Delete all of it.** The card menu stays, and there is one stat-points editor. About −300 lines. P7 then splits a smaller class.
- **B. Delete drag-and-drop and swipe, keep the keyboard shortcuts:** about −150 lines.
- **C. Keep it.**

**Proof:** for A, `team_builder_input.js`, `KEY_MAP` and the `drag_`/`drop_` methods have 0 hits, and there is no `.env` write from `screens/`. `TeamBuilderScreen` is −250 lines or more before P7 starts.

---

## D5. "Story so far": use the recaps the game already stores

**Status:** pending

**What exists today:**
- `Debrief` and `render_debrief` (about 45 lines).
- `prompts/debrief.md`.
- `GameSession.debrief` with `DebriefMemo`.
- A dialog in `ui/game.py:366-392`.

About 140 lines in total. This button makes a fresh narrator model call, but `Chapter.recap` already holds a player-safe summary of each finished scene, written by the worldsmith and checked for leaks.

**Decision D5:**
- **A. Delete the button:** about −140 lines.
- **B. Show the chapter titles and recaps plus the last few log lines, with no model call:** about −100 lines. The current scene has no recap yet, and Champions writes few recaps. **Recommended.**
- **C. Keep it.**

**Proof:** `Debrief`, `render_debrief` and `debrief.md` have 0 hits, and no model call is reachable from the dialog.

---

## D6. Settings that duplicate another control or barely matter

**Status:** pending

- **`pokemon.music`:** it duplicates the page's Sound toggle, which mutes battle audio too. Delete the setting.
- **`pokemon.sprites` (2d/3d):** keep 2d only. The asset fetch downloads every animated GIF anyway, so dropping 3d could also shrink the about-220 MB first-start download (not yet measured).
- **`pokemon.expert_team_builder`:** goes with D4. If D4 is not taken, store it per browser instead of in `.env`.
- **`roles.*.max_rounds`:** API roles only; make it a constant.

**Size:** about −50 lines.

**Feature impact:** no 3D/animated battle sprites, one fewer mute switch, `max_rounds` no longer configurable.

**Decision D6:**
- **A. All four (recommended).**
- **B. Everything except the sprites.**

**Proof:** the deleted settings have 0 hits in `config.py`, `ui/settings.py` and `.env` examples. Settings model fields go down by 3 or 4.

---

## D7. Trim two defensive checks that guard nothing real

**Status:** pending

- **JSON depth walker** (`_nesting_depth` and `JSON_DEPTH_MAX` in `validation.py`, about 20 lines plus a test). Pydantic's JSON parser already refuses deep nesting. The only recursion risk (`_mended`) is covered by catching `RecursionError` in one line, the same pattern `decode` already uses.
- **`ScenarioDescription.check_drift` and its caller** (about 10 lines plus a test). The save keeps its own copy of the description, so the check only means that **fixing a typo in a shipped scenario makes every save of it unresumable**.

The reviewer checked and recommends **keeping**:
- `answer_repair` (it saves a retry round trip on common model slips, and a test pins it)
- the name-leak checks (the narrator's no-spoiler promise)
- the duplicate-key JSON check (`json` would silently drop a doubled id)

**Size:** about −40 lines.

**Feature impact:** after D7, editing a shipped scenario's text no longer breaks its saves. That is a small improvement.

**Proof:** `_nesting_depth`, `JSON_DEPTH_MAX` and `check_drift` have 0 hits, and the suite is green.

---

## D8. `qa/demo/`: broken since 2026-10-08

**Status:** pending

**Evidence, confirmed:**
- `qa/demo/roles.py` `DemoRoles` has no `submit_answer`.
- Since commit 11dd0ec, every worldsmith call goes through `runner.submit_answer`, and the demo's `create()` step writes a scenario. So every recording take fails.
- Nothing in CI or basedpyright looks at `qa/`.

**What goes:** 8 files, **1,136 lines**. The shipped `docs/demo/demo.{mp4,gif}` stay, and the README keeps showing them. Only new recordings stop being possible.

**Decision D8:**
- **A. Delete the kit, keep the media (recommended).**
- **B. Fix it** (+15 lines: feed the scripted answers through `submission.call_tool`).
- **C. A, plus delete the media** (14.5 MB) and the README GIF.

**Proof:** for A, `qa/demo/*.py` and `*.html` are gone, and the README still renders the existing media.

---

## D9. Docs and the QA harness: remove what restates code or only takes screenshots

**Status:** pending

- **Docs "## The tools" sections**: about 55 lines, but about 21k characters, roughly 45% of the 24XX and Loner docs. They paraphrase the tool docstrings, which the goldens already pin, and they have **already drifted**: 24XX and Tunnel Goons omit `direct`, and Tunnel Goons omits `extend_map`. Replace each section with one line pointing to the engine's `@tool` docstrings.
- **QA screenshot and timing scenarios**: `qa/s_gallery.py` (screenshots only, and not even in `run_all.sh`), `qa/s_endure.py`, and the websocket timing instrumentation in `drive.py`. About −280 lines. You lose the traffic-timing check and the design gallery.
- **Golden fixtures**: store the shared tools (`kill`, `direct`, `reveal`…, repeated 3–5×) once in `shared_tools.json`. About −550 golden lines.

**Decision D9:**
- **A. All three.**
- **B. Docs and QA trim only (recommended).** Golden dedup adds test machinery for diff-noise relief only.
- **C. Docs only.**

**Proof:** the tools sections are gone from `docs/*.md`; `s_gallery.py`, `s_endure.py` and `SocketTraffic` have 0 hits; `run_all.sh` and the README list match.

---

## D10. Safe sweep: small proven dead bits

**Status:** pending

Each item was proven with grep (one hit, or none outside its own definition):
- **Two scenario portraits that can never show.** `scenarios/whispering-vault/icons/tomas.jpg` and `cloister_rat.jpg` (1.25 MB). Icons are looked up by exact id, and the ids are `brother-tomas` and `a-bloated-rat`. These have never matched since 0.5.0. Confirmed.
- **Unused test constants.**
  - `BROKEN_ILLUSION_SETUP`, `HIDDEN_VOLATILES_SETUP` and the `DOUBLES_SETUP` import in `test_opponent.py`.
  - `OBJECT` in `test_views.py`.
  - `FENCED` in `test_api_roles.py`.
  - `SRD` in `twentyfourxx/test_worldsmith.py`.

  About 45 lines in all.
- **`Subject.row(options=())`:** no caller passes it.
- **`GET /qa/faults`:** nothing reads it.
- **The stale `"PLAN.md"` entry** in `pyproject.toml` `extend-exclude`: the file does not exist. Confirmed.
- **The repeated test helper `_won`** (3 copies) and the wild-battle opener (4 copies) each become one shared helper. About −45 lines.
- **The prose-scanning boundary test** (`test_shared_modules_name_no_engine_concept` with its 13-phrase allow-list). CLAUDE.md forbids prose tests. About −50 lines. The import-direction tests still guard the real boundary. *R3 proposed rewriting it; this deletes it instead.*

**Decision D10:**
- **A. Delete the portraits.**
- **B. Rename them to `brother-tomas.jpg` / `a-bloated-rat.jpg`** so they finally show. **Recommended:** it costs the same, and the art was clearly meant to be used.

**Not included (needs you):** `docs/demo/social.png` (378 KB, unreferenced). It may be the GitHub social-preview source.

**Proof:** each named symbol has 0 hits, test lines −140 or more, and the suite is green.
