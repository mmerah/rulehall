import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from inspect import cleandoc, signature
from random import Random
from types import FunctionType, UnionType
from typing import Annotated, Union, cast, get_args, get_origin

from pydantic import BaseModel, JsonValue

from rulehall.core.facts import Fact
from rulehall.core.model import AnyGame
from rulehall.core.validation import Frozen, parse_json

type Call = Callable[[AnyGame, JsonValue, Random], tuple[Fact, ...]]
type Marks = dict[Callable[..., object], type[BaseModel]]
type CheckUnnamed = Callable[[AnyGame, tuple[str, ...]], None]

NOISE_KEYS = ("title", "pattern", "maxLength", "minLength")
_TOLD = object()
# A plain assignment, not a `type` alias: pydantic must read the metadata inside it.
Told = Annotated[str, _TOLD]
_TOOLS: Marks = {}
_ACTIONS: Marks = {}


# No docstring: pydantic would publish it as the schema's `description`.
class NoArgs(Frozen):
    pass


@dataclass(frozen=True, slots=True)
class MasterTool:
    name: str
    description: str
    args: type[BaseModel]
    call: Call


def tool[F: Callable[..., Sequence[Fact]]](method: F) -> F:
    """The method docstring is the text the master reads."""
    if not (method.__doc__ or "").strip():
        raise ValueError(f"{method.__qualname__} carries no description")
    args = _args_of(method)
    if bare := [key for key, info in args.model_fields.items() if not info.description]:
        raise ValueError(
            f"{method.__qualname__} parameters the model reads carry no description: {bare}"
        )
    _TOOLS[method] = args
    return method


def action[F: Callable[..., Sequence[Fact]]](method: F) -> F:
    _ACTIONS[method] = _args_of(method)
    return method


def tools_of(engine: object, check_unnamed: CheckUnnamed) -> dict[str, MasterTool]:
    return {
        name: _published(engine, name, function, check_unnamed)
        for name, function in _marked(engine, _TOOLS, "tool").items()
    }


def actions_of(engine: object) -> dict[str, Call]:
    return {
        name: _call_of(engine, name, _ACTIONS[function], _trusted)
        for name, function in _marked(engine, _ACTIONS, "action").items()
    }


def schema_of(args: type[BaseModel]) -> dict[str, JsonValue]:
    """One schema function, so what MCP publishes is what every prompt describes."""
    schema = args.model_json_schema()
    defs = schema.pop("$defs", {})
    _inline_refs(schema, defs)
    _normalize(schema)
    return schema


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(schema_of(model), indent=2, ensure_ascii=False)


def _marked(engine: object, marks: Marks, mark: str) -> dict[str, FunctionType]:
    """Definition order, base class first; a name defined again keeps the slot it first took."""
    marked: dict[str, FunctionType] = {}
    for cls in reversed(type(engine).__mro__):
        members: Mapping[str, object] = vars(cls)
        for name, value in members.items():
            if not isinstance(value, FunctionType):
                continue
            if value in marks:
                marked[name] = value
            elif name in marked:
                raise ValueError(
                    f"{value.__qualname__} overrides a @{mark} method but carries no @{mark} mark"
                )
    return marked


def _published(
    engine: object, name: str, function: FunctionType, check_unnamed: CheckUnnamed
) -> MasterTool:
    """The marked function carries the text and the model."""
    args = _TOOLS[function]
    # One line: the master reads a description, not the source's wrapping.
    description = " ".join(cleandoc(function.__doc__ or "").split())
    return MasterTool(name, description, args, _call_of(engine, name, args, check_unnamed))


def _call_of(engine: object, name: str, args: type[BaseModel], check_unnamed: CheckUnnamed) -> Call:
    """The bound method resolves an override."""
    bound: Callable[[AnyGame, BaseModel, Random], Sequence[Fact]] = getattr(engine, name)

    def call(draft: AnyGame, raw: JsonValue, rng: Random) -> tuple[Fact, ...]:
        parsed = parse_json(args, json.dumps(raw))
        if texts := tuple(_told_texts(parsed, type(parsed))):
            check_unnamed(draft, texts)
        return tuple(bound(draft, parsed, rng))

    return call


def _trusted(_draft: AnyGame, _texts: tuple[str, ...]) -> None:
    """Code builds the page's options, so their texts need no check."""


def _told_texts(value: object, annotation: object, *, told: bool = False) -> Iterator[str]:
    origin = get_origin(annotation)
    members = get_args(annotation)
    if told and isinstance(value, str):
        yield value
    elif isinstance(value, BaseModel):
        for key, info in type(value).model_fields.items():
            yield from _told_texts(
                getattr(value, key), info.annotation, told=_TOLD in info.metadata
            )
    elif origin is Annotated:
        yield from _told_texts(value, members[0], told=_TOLD in members[1:])
    elif origin in (Union, UnionType):
        for member in members:
            yield from _told_texts(value, member)
    elif origin in (tuple, list) and isinstance(value, tuple | list):
        # Every args sequence is `tuple[X, ...]` or `list[X]`.
        for item in cast("Sequence[object]", value):
            yield from _told_texts(item, members[0])


def _args_of(function: Callable[..., object]) -> type[BaseModel]:
    parameters = list(signature(function).parameters.values())
    args = parameters[2] if len(parameters) > 2 else None
    if args is not None and args.name.removeprefix("_") == "args":
        annotation: object = args.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
    raise ValueError(f"{function.__qualname__} does not take (self, draft, args, rng)")


def _inline_refs(node: JsonValue, defs: Mapping[str, JsonValue]) -> None:
    """A `$ref` becomes its definition: the model reads one tree and no class name leaks in."""
    if isinstance(node, list):
        for item in node:
            _inline_refs(item, defs)
        return
    if not isinstance(node, dict):
        return
    ref = node.pop("$ref", None)
    if isinstance(ref, str):
        target = defs[ref.removeprefix("#/$defs/")]
        if isinstance(target, dict):
            for key, value in target.items():
                node.setdefault(key, deepcopy(value))
    for value in node.values():
        _inline_refs(value, defs)


def _normalize(node: JsonValue) -> None:
    if isinstance(node, list):
        for item in node:
            _normalize(item)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        # A `properties` map is keyed by names, which may spell a noise key.
        if key == "properties" and isinstance(value, dict):
            for child in value.values():
                _normalize(child)
        else:
            _normalize(value)
    for key in NOISE_KEYS:
        node.pop(key, None)
    _collapse_nullable(node)


def _collapse_nullable(node: dict[str, JsonValue]) -> None:
    members = node.get("anyOf")
    if not isinstance(members, list) or len(members) != 2:
        return
    branches = [member for member in members if member != {"type": "null"}]
    if len(branches) != 1:
        return
    branch = branches[0]
    if not isinstance(branch, dict) or not isinstance(branch.get("type"), str):
        return
    rest = {key: value for key, value in node.items() if key != "anyOf"}
    node.clear()
    node.update(branch)
    node["type"] = [branch["type"], "null"]
    node.update(rest)
