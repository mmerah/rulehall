import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Annotated, NewType, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SLUG_MAX = 64
# Python 3.14 decodes any depth, but the code that walks a value recurses.
JSON_DEPTH_MAX = 100
Slug = Annotated[str, Field(pattern=rf"^{SLUG_PATTERN}$", max_length=SLUG_MAX)]

EngineId = NewType("EngineId", str)


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Mutable(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always", strict=True)


class Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class EngineHeader(Loose):
    engine_id: EngineId


class Refusal(ValueError):
    pass


def refuse(reason: str) -> None:
    if reason:
        raise Refusal(reason)


def content_id(value: str) -> Slug:
    if re.fullmatch(SLUG_PATTERN, value) is None or len(value) > SLUG_MAX:
        raise Refusal(f"invalid content id {value!r}")
    return value


def fold_accents(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(char for char in stripped if not unicodedata.combining(char))


def slug(text: str, taken: Iterable[str]) -> Slug:
    words = re.sub(r"[^a-z0-9]+", "-", fold_accents(text.lower())).strip("-")
    if not words:
        raise Refusal(f"{text!r} makes no id; give it a latin letter or a digit to be named by")
    return _unused(_capped(words, SLUG_MAX), taken)


def slugs(names: Iterable[str], taken: Iterable[str] = ()) -> list[Slug]:
    used = set(taken)
    made: list[Slug] = []
    for name in names:
        made.append(slug(name, used))
        used.add(made[-1])
    return made


def check_unique(what: str, ids: Iterable[str]) -> None:
    if found := sorted(name for name, count in Counter(ids).items() if count > 1):
        raise Refusal(f"duplicate {what}: {found}")


def as_tuple(value: object) -> object:
    if isinstance(value, str):
        return (value,)
    # Past a before-validator the input is Python, where strict mode takes a tuple, not a list.
    return tuple(cast("list[object]", value)) if isinstance(value, list) else value


def parse[T: BaseModel](model: type[T], value: object) -> T:
    try:
        return model.model_validate(value)
    except ValidationError as broken:
        raise _refused(broken) from broken


def parse_json[T: BaseModel](model: type[T], raw: str | bytes) -> T:
    """Strict mode reaches a tuple field only from JSON, so text is validated as text."""
    try:
        return model.model_validate_json(raw)
    except ValidationError as broken:
        raise _refused(broken) from broken


def decode(raw: str) -> JsonValue:
    """`json` keeps the last of two equal keys, so a doubled id would vanish without a word."""
    try:
        value: JsonValue = json.loads(raw, object_pairs_hook=_unique_keys)
    except (json.JSONDecodeError, RecursionError) as broken:
        raise Refusal(f"not JSON: {broken}") from broken
    if _nesting_depth(value) > JSON_DEPTH_MAX:
        raise Refusal(f"not JSON: nested deeper than {JSON_DEPTH_MAX} levels")
    return value


def parse_strict_json[T: BaseModel](model: type[T], raw: str) -> T:
    decode(raw)
    return parse_json(model, raw)


def for_engine_of[T](raw: str, by_engine: Mapping[EngineId, T]) -> T:
    engine_id = parse_strict_json(EngineHeader, raw).engine_id
    found = by_engine.get(engine_id)
    if found is None:
        raise Refusal(f"the {engine_id!r} engine is not installed")
    return found


def _refused(broken: ValidationError) -> Refusal:
    first = broken.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return Refusal(f"{where}: {first['msg']}" if where else first["msg"])


def _unique_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    check_unique("keys in a JSON object", (key for key, _ in pairs))
    return dict(pairs)


def _unused(base: str, taken: Iterable[str]) -> str:
    used, candidate, number = set(taken), base, 2
    while candidate in used:
        suffix = f"-{number}"
        candidate, number = f"{_capped(base, SLUG_MAX - len(suffix))}{suffix}", number + 1
    return candidate


def _capped(words: str, limit: int) -> str:
    return words[:limit].rstrip("-")


def _nesting_depth(value: JsonValue) -> int:
    deepest = 0
    pending = [(value, 0)]
    while pending:
        node, depth = pending.pop()
        deepest = max(deepest, depth)
        if isinstance(node, dict):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
    return deepest
