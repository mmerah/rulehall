# Repository guidance

## Commands

Run these from the repository root. Do not set `UV_CACHE_DIR`. It breaks the tests.

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run basedpyright
uv run rulehall
```

The tests run offline. They give the same result every time.

## How the game works

- AI roles play the game. Each role starts with no memory every turn.
- A role answers with a typed proposal or plays through tools.
- Only code changes the game state. Only code rolls dice.
- An engine owns its world. The layers above the engines do not know the shape of a world.
- A tool is a marked engine method. Its docstring is the text the model reads.
- A narrator role sees only the facts it may know. Hidden facts never reach it.
- A bad model answer gets one retry with the error. Then it raises.
- Saves have no version. An old save is invalid.
- Only the app and the UI read the settings.

## Code

- A class owns its state and the methods that use it. A function with no owner stays free.
- A property reads one value. A method builds or renders.
- Side effects live at the edges: files, network, UI. Rules code changes only the draft it gets.
- State models are mutable. Value models are frozen.
- Use exact types. Use `Any` only where the type system gives no other way.
- Validate data at each boundary with strict models. Reject bad data at once.
- A message for a person or a model has its own exception type. Any other exception is a bug. Do not catch it.
- One concern, one pattern. Before you add code, find how the codebase already does it and do the same.
- Use the same names for the same things. An id field ends in `_id`.
- Sibling engines hold the same files with the same roles. Look at a sibling before you add one.
- Names are descriptive, even when longer. A lookup that raises is `require_x`; one that returns `None` is `find_x`. A value is a noun; an action is a verb phrase.
- Add a comment only when the code cannot show the reason.
- Do not add an abstraction before two things need it. Do not build for future needs.
- Keep `__init__.py` files empty. Import from full module paths.
- Imports flow one way, from the core out to the UI. No cycles.
- Module layout: imports, constants, classes, public functions, private functions.

## Tests

- Test behavior and boundaries. Do not test prose or wiring.
- Never start a process in a test. Use a scripted stub for roles.
- A golden detects drift. It does not test prose.
