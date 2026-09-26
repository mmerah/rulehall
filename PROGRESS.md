# Progress

## Standing decisions

User decisions. A phase never re-opens one.

1. The engine is `loner4e`. The move is straight: no `loner3e` beside it. Old saves, old sheets and packs written under `packs/loner3e/` may stop loading.
2. One protagonist. The party only follows; members never roll. Their help is a tag cited in `helps`.
3. Luck is 6 for everyone. Only a group may be larger (6 to 10).
4. Code nets the tags. The master cites them; code checks each exists and counts.
5. The player sees the question text on the card. It names nothing hidden.
6. The player sees the Twist Counter.
7. EMERGENT LONER (replaces "hidden canon wins over the oracle"). Loner follows the SRD's first principle: no pre-written story; the oracle discovers the world. What is established (told, a sheet or scene tag, or in Settled) stands; everything else is open to the oracle. Loner scenes hold nothing hidden and no secret twist; the arc is loose pressure (what the opposition wants, open threads). Loner's worldsmith text is its own guidance, without "Surprise the player" or authored secrets. The canon-vs-oracle machinery goes: no `answer_from_canon`, no `reveal` in Loner. The shared hidden support stays for 24XX (a deciding GM) and rooms.
8. The player may ask the oracle directly ("Ask the oracle"); the question is rolled word for word.
9. The Status Track, Challenge Tracks and Leverage are on in every game. A module is on when any played pack (the SRD pack or the game's own pack) sets its flag; `srd.json` sets all three, and every game plays the SRD pack.
10. The worldsmith runs the Living World step. LIVING WORLD CARRIES FORWARD: its lines are stored on the grown Loner sheet and given to the worldsmith in that character's next Loner game.
11. Goal and motive stay creation steps but may be blank.
12. 24XX pauses on the player's commit. One narrow escape: the master may set `committed` only when the player's own words for this action name this danger and accept it.
13. The Loner master interprets; code owns the loop. The 24XX master stays a deciding GM.
14. Unit tests are minimal: one per new core behaviour; no tests for prose, wiring or every branch.
15. No comments and no docstrings, except a one-line critical "why" or text a model reads (tool docstrings, `Field` descriptions). PLAN.md's "How to work" agrees with the `/phase` skill's Rules paragraph: SOLID, Clean Architecture, DRY, KISS, consistency with the codebase, unit tests only for the minimal core behaviour.
16. No deferral. Everything in scope is settled by the end of the plan.
17. The size budget is soft. Never cut scope for it.
18. NO no-roll gate: `direct` gets no `settled_by`; the rules text says when to ask.
19. 24XX follows the SRD on defence (break gear as a reaction after a disaster or setback), advancement (the player picks their own raise) and death (with no hired crew, a new operator joins; "favor inclusion over realism").

Key design readings (from the reviewed design):

- The master owns one lifecycle call per scene: `close_scene`. Every die rolls inside a tool; `end_turn` only hands over.
- A tool that sets `request` or `pending` ends the master's turn, so the close is recorded in `Frame.next` and `end_turn` sets the request.
- Player input is composer text, a composer option (an action that gets the words), or a pending decision. The way-on hook is gone.
- The meanwhile clock belongs to the rooms family only. Loner's meanwhile is a roll.
- Settled lives in the scenes family (Loner and 24XX use it). The closing result is the last `action` entry.
- Module tools refuse when their flag is off, as `spend_luck` does. No per-state tool list.
- The Living World is told as the closing card and carried as lines on the grown sheet; the ended game's NPC state is not rewritten.
- 24XX `roll` is both tool and action; the Commit option is `roll` with `committed=True`. The emergency pick is the commit.

Decisions this plan made where the design left a shape open:

- `tables.py` is the only twist table; pack twist columns are deleted, because code keys on the action wording.
- The inspiration grids arrive in phase 4 with `inspire`, not in phase 2. No `STATUS_EXAMPLES` constant: the examples live in `rules.md` only.
- `CreationStep.optional` makes a step blank-able; `check_picks` names no step id.
- `Frame.next: tuple[()] | tuple[SceneKind] | tuple[Literal["meanwhile"], SceneKind]`; `Frame.coming` narrows it with `match` and gives the kind of the next scene, so no install takes a kind. `Frame.closed_by` keeps the reason for the dramatic request.
- The quiet install has no narrator cue: the aim's turn narrates the arrival. `_land` records a cue-less resolution's facts with no lines, so the quiet card reaches the transcript; the quiet handler notes `ARRIVING_QUIET` for the master.
- `end_why: str` replaces `growth_due: bool`: a text answer runs no engine code, so the end stays pending from `end_adventure` until `play_on` clears it. `play_on` is both `@tool` and `@action`, so a player who declines in words is answered by the master.
- `Library.rewrite_character` writes the grown sheet (the existing `write_character` refuses overwrites); it shares the shipped check and the path with `write_character` through one private helper. `GameService.character` is set to the grown sheet, so a restart replays it. A shipped character is never rewritten; the refusal is logged.
- The banking lives on the Settled entry (`Settled.banked`), so a banked Yes-and counts once even after the leverage is gone. `Leverage` is `phrase` and `armed` only.
- Scene tags use `actor_id: "scene"` (`SCENE_ID`) on a plain `Slug` field. `SCENE_ID` is reserved: the world validator and the worldsmith checks refuse a cast id `scene`. `detail` is not a `TagKind`; only `ChangeTags.kind` adds it.
- `details` takes one to four tags; the prompt asks for two to four.
- The composer banner keeps one fixed icon; `DecisionOption.sprite` names an image, not an icon.
- `end_turn` has one order: a waiting decision or request stops it; then the ending; then the scene handover.
- `inspire` is trace only, never told.
- `mark_status` takes a tag; no call means no mark.
- A banked Yes-and inside Harm & Luck deals the harm of a plain Yes.
- An opponent at 0 while others fight gets the `DEFEATED` note.
- Phase 9 depends on phase 4; phases run strictly in order.
- `master.md`'s dice paragraphs go in phase 4, not phase 10, so no phase contradicts Loner.
- Emergent Loner, leanest shape: the shared `worldsmith.md` becomes neutral and its `hidden` and "Surprise" paragraphs move to 24XX guidance; Loner's scene checks refuse any `hidden`; `reveal` moves to a `Revealing` mixin used by rooms and 24XX. The shipped whispering-vault loses its hidden map.
- The Living World lines live in `Loner4eEntity.living_world` and reach the worldsmith through a `WHAT THE PROTAGONIST CARRIES FORWARD` section; the pre-authored opening is not rewritten.
- The closing test shows in SCENE only, not after every ask.
- Dead-end memory across scenes: a `DEAD ENDS IN THE LAST SCENE` section from the previous scene's Settled.
- The player's goal change before the first question is `drive(scene, goal)`, a rules-text permission with no code gate.
- A quiet scene after a Meanwhile carries `Frame.offscreen` into its intent.
- 24XX: the commit prompt is built from the pool, the stakes, deadliness and the actor's hindrances; `committed`'s description and rules text reject a bare action ("I shoot him"); the defence pause covers the actor only; `raise_owed` guards `raise_skill`; `bring_in` and a `newcomer` request reuse the hiring path.
- Rejected: `settled_by` on `direct` (user decision 18); `answer_from_canon` (no canon to answer from); an `unhindered_because` field (the commit prompt shows the hindrances instead); a verbatim-quote check on `committed` (the Commit option shares the method, and the turn's words are not on the draft); unsheeted helpers sharing risk (no sheet to carry the hit; kept as a documented deviation); module toggles or opt-in leverage pauses (modules are on by user decision; the pauses are the player's SRD choices); leverage and status reminder notes (LEVERAGE HELD and STATUS show every turn).
- After-result pauses never cut the master out: a pause that belongs to a result (leverage, 24XX defence) withholds the card, and its option writes the final card on a played turn, so the master interprets the result that stands. The Loner per-exchange conflict pause is dropped (reading 22 was not a user decision; the SRD asks nothing of the player between exchanges): the master interprets each exchange and directs, and the player's next words choose.
- The 24XX defence pause opens only where a hit lands on the actor (a disaster, or a deadly setback), through `_land` and `defend_hit`; a broken non-harmless item leaves `Brief: {risk}` so `_break` accepts it.
- The Meanwhile cutaway tells met people's updates on one card; unmet ones stay traces.
- `close_scene` is called before `direct` (after `direct` no tool runs); rules text and docstring say so.
- Loner questioning follows the SRD's own lines: never compound, don't overquestion (three follow-ups), stop at the protagonist's next choice. No invented after-a-No rule.
- Armed leverage counts only when its phrase is cited in `helps`.
- 24XX ship emergency: the master names the stations (function and skill); a text "yes, do it" at the commit prompt commits; job find 1-2 offers the ₡1 re-roll or debt; the commit prompt names more than one bulky item.
- The Loner narrator view says to add nothing beyond SCENE, the cards and the notes. The Twist Counter rests while any conflict is open. `MODULES IN PLAY` is cut. Deviation 7 says "adapts". `direct`'s "use reveal first" moves to the rooms and 24XX rules text.

Known and accepted:

- A leverage or risk pause withholds the ask's card, but when an earlier tool in the same turn told a fact, the narrator runs and sees the pause prompt. The result is settled either way; the harm is small.

## Log

- 2026-09-26: Plan reviewed; findings folded.
- 2026-09-26: Blind check folded; emergent Loner.
- 2026-09-26: Second blind check folded.

