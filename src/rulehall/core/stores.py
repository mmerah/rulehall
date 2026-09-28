import logging
import os
import re
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from tempfile import mkstemp

from pydantic import BaseModel

from rulehall.core.game import AnyCharacter, AnyGame, AnyScenario, CharacterHeader
from rulehall.core.validation import (
    EngineId,
    Refusal,
    Slug,
    content_id,
    for_engine_of,
    parse_json,
    parse_strict_json,
)

LOGGER = logging.getLogger(__name__)

ENCODING = "utf-8"
WORLD_FILE = "world.json"
# Two content ids joined by `--`: a save id is not a `Slug`.
SAVE_ID_PATTERN = r"[a-z0-9][a-z0-9-]*"
SHIPPED_CONTENT = Path(__file__).parents[3]


@dataclass(frozen=True, slots=True)
class SaveStore:
    directory: Path

    def save_ids(self) -> tuple[str, ...]:
        return tuple(
            path.stem
            for path in sorted(self.directory.glob("*.json"))
            if re.fullmatch(SAVE_ID_PATTERN, path.stem) is not None
        )

    def read(self, save_id: str) -> str | None:
        path = self._save_path(save_id)
        return _read_text(path) if path.exists() else None

    def write(self, save_id: str, state: AnyGame, /) -> None:
        write_model(self._save_path(save_id), state)

    def media_dir(self, save_id: str) -> Path:
        return _safe_path(self.directory, save_id, ".media")

    def discard(self, save_id: str) -> None:
        try:
            self._save_path(save_id).unlink(missing_ok=True)
        except OSError as broken:
            raise Refusal(f"{save_id} cannot be discarded: {broken}") from broken

    def _save_path(self, save_id: str) -> Path:
        return _safe_path(self.directory, save_id, ".json")


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
                LOGGER.warning("skipping scenario %r: %s", path.name, unreadable)
                continue
            yield content_id(path.name), scenario

    def read_characters(
        self, engines: Collection[EngineId]
    ) -> Iterator[tuple[Slug, EngineId, CharacterHeader]]:
        for path in _entries(self.shipped_characters, self.characters, "character"):
            for engine_id in engines:
                file = path / f"{engine_id}.json"
                if not file.is_file():
                    continue
                try:
                    character_id = content_id(path.name)
                    header = read_model(file, CharacterHeader)
                    _check_filed(header.id, header.engine_id, character_id, engine_id)
                except Refusal as unreadable:
                    LOGGER.warning("skipping character %r: %s", path.name, unreadable)
                    continue
                yield character_id, engine_id, header

    def read_scenario(
        self, scenario_id: Slug, models: Mapping[EngineId, type[AnyScenario]]
    ) -> AnyScenario:
        path = self.scenario_folder(scenario_id) / WORLD_FILE
        raw = _read_text(path)
        return parse_json(for_engine_of(raw, models), raw)

    def read_character(
        self, character_id: Slug, engine_id: EngineId, model: type[AnyCharacter]
    ) -> AnyCharacter:
        character = read_model(self.character_folder(character_id) / f"{engine_id}.json", model)
        _check_filed(character.id, character.engine_id, content_id(character_id), engine_id)
        return character

    def write_character(self, character: AnyCharacter) -> None:
        path = self._player_character_path(character)
        if path.exists():
            raise Refusal(f"character {character.id!r} already exists")
        sibling = next(path.parent.glob("*.json"), None)
        if sibling is not None:
            filed, named = read_model(sibling, CharacterHeader).person.name, character.person.name
            if filed != named:
                raise Refusal(f"character {character.id!r} is {filed!r}, not {named!r}")
        write_model(path, character)

    def rewrite_character(self, character: AnyCharacter) -> None:
        write_model(self._player_character_path(character), character)

    def write_scenario(self, scenario_id: Slug, scenario: AnyScenario) -> None:
        if content_id(scenario_id) in self.scenario_ids():
            raise Refusal(f"scenario {scenario_id!r} already exists")
        write_model(self.scenarios / content_id(scenario_id) / WORLD_FILE, scenario)

    def _player_character_path(self, character: AnyCharacter) -> Path:
        if (self.shipped_characters / content_id(character.id)).exists():
            raise Refusal(f"character {character.id!r} ships with the game")
        return self.characters / content_id(character.id) / f"{character.engine_id}.json"


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
        write_model(self.path(engine_id, pack_id), pack)


@cache
def read_cached_text(path: Path) -> str:
    return path.read_text(encoding=ENCODING)


def publish(path: Path, write: Callable[[Path], object]) -> None:
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


def write_model(path: Path, model: BaseModel) -> None:
    write_text(path, model.model_dump_json(indent=2))


def read_model[T: BaseModel](path: Path, model: type[T]) -> T:
    return parse_strict_json(model, _read_text(path))


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


def _safe_path(directory: Path, stem: str, suffix: str) -> Path:
    if re.fullmatch(SAVE_ID_PATTERN, stem) is None:
        raise ValueError(f"invalid save id {stem!r}")
    return directory / f"{stem}{suffix}"
