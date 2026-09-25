# Contributing

Thanks for your interest in Rulehall. Bug reports, ideas and pull requests are all welcome.

Please be kind to each other. See the [code of conduct](CODE_OF_CONDUCT.md).

## Issues

- **Found a bug?** Open an issue with the bug template. The steps to reproduce matter most.
- **Have an idea?** Open an issue with the idea template. For anything bigger than a small fix, please open the issue before you write the code, so we can agree on the shape first.
- **Found a security problem?** Don't open an issue. Read [SECURITY.md](SECURITY.md).

## Getting set up

You need [`uv`](https://docs.astral.sh/uv/). Node 22 is only needed for the Pokemon rule set.

```bash
uv sync
uv run rulehall
```

The README covers the rest: the AI commands, the Pokemon setup and Docker.

## Before you open a pull request

Run the four checks from the repository root. CI runs the same ones.

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
uv run basedpyright
```

The tests run offline and never call a real model, so they're fast and give the same result every time.

A few things make a review quick:

- Keep a pull request to one change.
- Read [CLAUDE.md](CLAUDE.md). Despite the name, it's the project's code guide for humans and AI alike: how the game is split between code and the AI roles, and the rules the code follows.
- Test behavior, not prose. A new rule gets a test; a reworded prompt doesn't.
- Don't bump a save format with a migration. Saves have no version, and an old save is simply skipped.

## Releases

The [releases page](https://github.com/mmerah/rulehall/releases) is the changelog. Pushing a signed tag builds it: CI lists every commit since the last tag, puts dependency bumps in their own section, and publishes the versioned Docker image.

```bash
git tag -s v0.2.0 -m "Rulehall 0.2.0"
git push origin v0.2.0
```

So write commit subjects for people: they end up in the changelog as they are.

## Licence

By contributing, you agree that your work is released under the [MIT licence](LICENSE), the same as the rest of the code.
