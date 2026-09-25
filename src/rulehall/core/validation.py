import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Annotated, NewType

from pydantic import BaseModel, ConfigDict, Field, ValidationError

SLUG_PATTERN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
SLUG_MAX = 64
# assignment, not `type`: an alias publishes a dict key as `propertyNames`, without the pattern
Slug = Annotated[str, Field(pattern=rf"^{SLUG_PATTERN}$", max_length=SLUG_MAX)]

EngineId = NewType("EngineId", str)


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
