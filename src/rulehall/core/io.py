import json
import logging
import os
import re
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from tempfile import mkstemp

from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_core import from_json

from rulehall.core.model import AnyCharacter, AnyGame, AnyScenario, CharacterHeader, EngineHeader
from rulehall.core.play import Line
from rulehall.core.validation import (
    EngineId,
    Refusal,
    Slug,
    check_unique,
    content_id,
    parse,
    parse_json,
)

LOGGER = logging.getLogger(__name__)

ENCODING = "utf-8"
WORLD_FILE = "world.json"
SOURCE_SUFFIXES = (".md", ".txt", ".pdf")
# Two content ids joined by `--`: a save name is not a `Slug`.
SAVE_SLUG_PATTERN = r"[a-z0-9][a-z0-9-]*"
LINES = TypeAdapter(list[Line])
SHIPPED_CONTENT = Path(__file__).parents[3]


@dataclass(frozen=True, slots=True)
class FileStore:
    directory: Path

    def slugs(self) -> tuple[str, ...]:
        return tuple(
            path.stem
            for path in sorted(self.directory.glob("*.json"))
            if re.fullmatch(SAVE_SLUG_PATTERN, path.stem) is not None
        )

    def read(self, slug: str) -> str | None:
        path = self._save_path(slug)
        return _read_text(path) if path.exists() else None

    def write(self, slug: str, state: AnyGame, /) -> None:
        write_text(self._save_path(slug), state.model_dump_json(indent=2))

    def media_dir(self, slug: str) -> Path:
        return _safe_path(self.directory, slug, ".media")

    def discard(self, slug: str) -> None:
        try:
            self._save_path(slug).unlink(missing_ok=True)
        except OSError as broken:
            raise Refusal(f"{slug} cannot be discarded: {broken}") from broken

    def _save_path(self, slug: str) -> Path:
        return _safe_path(self.directory, slug, ".json")


@dataclass(frozen=True, slots=True)
class Library:
    scenarios: Path
    characters: Path
    shipped: Path = SHIPPED_CONTENT

    @property
    def shipped_scenarios(self) -> Path:
        return self.shipped / "scenarios"

    @property
    def shipped_characters(self) -> Path:
        return self.shipped / "characters"

    def scenario_folder(self, scenario_id: Slug) -> Path:
        return _found(content_id(scenario_id), self.shipped_scenarios, self.scenarios)

    def character_folder(self, character_id: Slug) -> Path:
        return _found(content_id(character_id), self.shipped_characters, self.characters)

    def scenario_ids(self) -> tuple[str, ...]:
        """Every entry, slug or not: a new slug must not collide with a stray folder."""
        return tuple(
            entry.name
            for root in (self.shipped_scenarios, self.scenarios)
            if root.is_dir()
            for entry in root.iterdir()
        )

    def read_scenarios(
        self, models: Mapping[EngineId, type[AnyScenario]]
    ) -> Iterator[tuple[Slug, AnyScenario]]:
        for path in _entries(self.shipped_scenarios, self.scenarios, "scenario"):
            if not (path / WORLD_FILE).is_file():
                continue
            try:
                scenario = self.read_scenario(path.name, models)
            except Refusal as unreadable:
                # Skip incomplete scenarios so the home screen remains usable.
                LOGGER.warning("skipping scenario %r: %s", path.name, unreadable)
                continue
            yield content_id(path.name), scenario

    def read_characters(
        self, engines: Collection[EngineId]
    ) -> Iterator[tuple[Slug, EngineId, CharacterHeader]]:
        """One entry per (character, engine) file, so a shared id never names one engine's rules."""
        for path in _entries(self.shipped_characters, self.characters, "character"):
            for engine_id in engines:
                file = path / f"{engine_id}.json"
                if not file.is_file():
                    continue
                try:
                    name = content_id(path.name)
                    header = read_model(file, CharacterHeader)
                    _check_filed(header.id, header.engine_id, name, engine_id)
                except Refusal as unreadable:
                    LOGGER.warning("skipping character %r: %s", path.name, unreadable)
                    continue
                yield name, engine_id, header

    def read_scenario(
        self, scenario_id: Slug, models: Mapping[EngineId, type[AnyScenario]]
    ) -> AnyScenario:
        path = self.scenario_folder(scenario_id) / WORLD_FILE
        raw = _read_text(path)
        return parse_json(routed(decode(raw), models), raw)

    def read_character(
        self, character_id: Slug, engine_id: EngineId, model: type[AnyCharacter]
    ) -> AnyCharacter:
        character = read_model(self.character_folder(character_id) / f"{engine_id}.json", model)
        _check_filed(character.id, character.engine_id, content_id(character_id), engine_id)
        return character

    def write_character(self, character: AnyCharacter) -> None:
        if (self.shipped_characters / content_id(character.id)).exists():
            raise Refusal(f"character {character.id!r} ships with the game")
        folder = self.characters / content_id(character.id)
        path = folder / f"{character.engine_id}.json"
        if path.exists():
            raise Refusal(f"character {character.id!r} already exists")
        # One folder is one person played by several engines, so any sibling settles who that is.
        sibling = next(folder.glob("*.json"), None)
        if sibling is not None:
            filed, named = read_model(sibling, CharacterHeader).sheet.name, character.sheet.name
            if filed != named:
                raise Refusal(f"character {character.id!r} is {filed!r}, not {named!r}")
        write_text(path, character.model_dump_json(indent=2))

    def write_scenario(self, scenario_id: Slug, scenario: AnyScenario) -> None:
        if content_id(scenario_id) in self.scenario_ids():
            raise Refusal(f"scenario {scenario_id!r} already exists")
        write_text(
            self.scenarios / content_id(scenario_id) / WORLD_FILE,
            scenario.model_dump_json(indent=2),
        )


@dataclass(frozen=True, slots=True)
class PackStore:
    directory: Path

    def ids(self, engine_id: EngineId) -> tuple[str, ...]:
        """Every stem, slug or not: a new id must not overwrite a file the engine skipped."""
        folder = self.directory / engine_id
        if not folder.is_dir():
            return ()
        return tuple(path.stem for path in sorted(folder.glob("*.json")))

    def path(self, engine_id: EngineId, pack_id: Slug) -> Path:
        return self.directory / engine_id / f"{pack_id}.json"

    def write(self, engine_id: EngineId, pack_id: Slug, pack: BaseModel) -> None:
        write_text(self.path(engine_id, pack_id), pack.model_dump_json(indent=2))


@cache
def read_cached_text(path: Path) -> str:
    return path.read_text(encoding=ENCODING)


def publish(path: Path, write: Callable[[Path], object]) -> None:
    """Write beside, then replace: a reader never sees a partial file."""
    staged: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = mkstemp(dir=path.parent, prefix=f".{path.name}.")
        os.close(fd)
        staged = Path(name)
        write(staged)
        staged.replace(path)
    except OSError as broken:
        raise Refusal(f"{path.name} cannot be written: {broken.strerror}") from broken
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def write_text(path: Path, body: str) -> None:
    publish(path, lambda staged: staged.write_text(body, encoding=ENCODING))


def decode(raw: str) -> JsonValue:
    """`json` keeps the last of two equal keys, so a doubled id would vanish without a word."""
    try:
        return json.loads(raw, object_pairs_hook=_unique_keys)
    except (json.JSONDecodeError, RecursionError) as broken:
        raise Refusal(f"not JSON: {broken}") from broken


def parse_text[T: BaseModel](model: type[T], raw: str) -> T:
    """The decode pass rejects a doubled key; a caller that already decoded uses `parse_json`."""
    decode(raw)
    return parse_json(model, raw)


def partial_lines(raw: str) -> tuple[Line, ...]:
    start = raw.find("{")
    if start == -1:
        return ()
    try:
        partial = from_json(raw[start:], allow_partial="trailing-strings")
        return tuple(
            LINES.validate_python(partial.get("lines", []), experimental_allow_partial=True)
        )
    except ValueError:
        return ()


def routed[T](value: JsonValue, by_engine: Mapping[EngineId, T]) -> T:
    engine_id = parse(EngineHeader, value).engine_id
    found = by_engine.get(engine_id)
    if found is None:
        raise Refusal(f"the {engine_id!r} engine is not installed")
    return found


def read_model[T: BaseModel](path: Path, model: type[T]) -> T:
    return parse_text(model, _read_text(path))


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise Refusal(f"{path.parent.name!r} has no {path.name}")
    try:
        return path.read_text(encoding=ENCODING)
    except (OSError, UnicodeDecodeError) as broken:
        raise Refusal(f"{path.name} cannot be read") from broken


def _check_filed(
    character_id: str, plays: EngineId, filed_under: Slug, engine_id: EngineId
) -> None:
    if plays != engine_id:
        raise Refusal(f"the character plays {plays!r}, not {engine_id!r}")
    if character_id != filed_under:
        raise Refusal(f"character {character_id!r} is filed under {filed_under!r}")


def _found(name: str, shipped: Path, player: Path) -> Path:
    return shipped / name if (shipped / name).exists() else player / name


def _entries(shipped: Path, player: Path, kind: str) -> list[Path]:
    found = {path.name: path for path in _folders(shipped)}
    for path in _folders(player):
        if path.name in found:
            LOGGER.warning("skipping %s %r: a shipped %s has that id", kind, path.name, kind)
            continue
        found[path.name] = path
    return [found[name] for name in sorted(found)]


def _folders(root: Path) -> list[Path]:
    return [entry for entry in root.iterdir() if entry.is_dir()] if root.is_dir() else []


def _unique_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    check_unique("keys in a JSON object", (key for key, _ in pairs))
    return dict(pairs)


def _safe_path(directory: Path, stem: str, suffix: str) -> Path:
    if re.fullmatch(SAVE_SLUG_PATTERN, stem) is None:
        raise ValueError(f"invalid storage slug {stem!r}")
    return directory / f"{stem}{suffix}"
