import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from functools import cache
from typing import Annotated, NewType, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SLUG_MAX = 64
# assignment, not `type`: an alias publishes a dict key as `propertyNames`, without the pattern
Slug = Annotated[str, Field(pattern=rf"^{SLUG_PATTERN}$", max_length=SLUG_MAX)]

EngineId = NewType("EngineId", str)
NULL_WORDS = ("null", "None", "")
LOGGER = logging.getLogger(__name__)

type Schema = Mapping[str, JsonValue]


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Mutable(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always", strict=True)


class Loose(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class Refusal(ValueError):
    """A message a role or the player is meant to read; any other exception is a bug."""


def content_id(value: str) -> Slug:
    """Narrow a routed id before it names a directory, so `Slug` downstream is a fact."""
    if re.fullmatch(SLUG_PATTERN, value) is None or len(value) > SLUG_MAX:
        raise Refusal(f"invalid content id {value!r}")
    return value


def slug(text: str, taken: Iterable[str]) -> Slug:
    words = re.sub(r"[^a-z0-9]+", "-", _folded(text.lower())).strip("-")
    if not words:
        raise Refusal(f"{text!r} makes no id; give it a latin letter or a digit to be named by")
    return _unused(_capped(words, SLUG_MAX), taken)


def check_unique(what: str, ids: Iterable[str]) -> None:
    if found := sorted(name for name, count in Counter(ids).items() if count > 1):
        raise Refusal(f"duplicate {what}: {found}")


def listed(value: object) -> object:
    """A model often sends one item bare where a list is asked: it is the list of that item."""
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


def parse_mended[T: BaseModel](model: type[T], value: JsonValue) -> T:
    """A model's answer: a harmless slip is mended, and validation refuses only what is left."""
    return parse_json(model, json.dumps(_mended(value, _schema(model), model)))


def _refused(broken: ValidationError) -> Refusal:
    first = broken.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return Refusal(f"{where}: {first['msg']}" if where else first["msg"])


def _folded(text: str) -> str:
    """An accent is dropped, not cut into a dash: `Naïve` is named `naive`, as the packs name it."""
    stripped = unicodedata.normalize("NFKD", text)
    return "".join(char for char in stripped if not unicodedata.combining(char))


def _unused(base: str, taken: Iterable[str]) -> str:
    used, candidate, number = set(taken), base, 2
    while candidate in used:
        suffix = f"-{number}"
        candidate, number = f"{_capped(base, SLUG_MAX - len(suffix))}{suffix}", number + 1
    return candidate


def _capped(words: str, limit: int) -> str:
    return words[:limit].rstrip("-")


@cache
def _schema(model: type[BaseModel]) -> Schema:
    return model.model_json_schema()


def _shapes(schema: Schema, model: type[BaseModel]) -> list[Schema]:
    """The schema itself, its `$ref` and each `anyOf` branch, resolved against the model's."""
    ref = schema.get("$ref")
    if isinstance(ref, str):
        defs = _as_schema(_schema(model).get("$defs", {}))
        return _shapes(_as_schema(defs[ref.rsplit("/", 1)[-1]]), model)
    branches = schema.get("anyOf")
    if not isinstance(branches, list):
        return [schema]
    return [shape for branch in branches for shape in _shapes(_as_schema(branch), model)]


def _as_schema(node: JsonValue | Schema) -> Schema:
    return node if isinstance(node, dict) else {}


def _mended(value: JsonValue, schema: Schema, model: type[BaseModel]) -> JsonValue:
    """A null written as text is null, a bare text where a list is asked is that list, and a
    field no schema names is dropped."""
    shapes = {shape.get("type"): shape for shape in _shapes(schema, model)}
    if isinstance(value, str):
        if "null" in shapes and value.strip() in NULL_WORDS:
            return None
        if "string" not in shapes and "array" in shapes:
            return _mended([value], shapes["array"], model)
        return value
    if isinstance(value, list) and "array" in shapes:
        items = _as_schema(shapes["array"].get("items"))
        return [_mended(item, items, model) for item in value]
    if isinstance(value, dict) and "object" in shapes:
        shape = shapes["object"]
        if extra := [key for key in value if _field(shape, key) is None]:
            LOGGER.info("dropped fields %s from a %s answer", extra, model.__name__)
        return {
            key: _mended(item, field, model)
            for key, item in value.items()
            if (field := _field(shape, key)) is not None
        }
    return value


def _field(schema: Schema, key: str) -> Schema | None:
    """A named field, else the first key pattern it matches, else any other key's shape; None
    when the schema forbids the key."""
    if key in (fields := _as_schema(schema.get("properties"))):
        return _as_schema(fields[key])
    patterns = _as_schema(schema.get("patternProperties"))
    matched = (shape for pattern, shape in patterns.items() if re.search(pattern, key))
    other = next(matched, schema.get("additionalProperties"))
    return None if other is False else _as_schema(other)
