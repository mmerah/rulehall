import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from functools import cache
from inspect import cleandoc, signature
from types import FunctionType, UnionType
from typing import Annotated, Literal, Protocol, Union, cast, get_args, get_origin

from pydantic import BaseModel, JsonValue

from rulehall.core.facts import Fact
from rulehall.core.validation import Frozen

type Marks = dict[Callable[..., object], type[BaseModel]]

NOISE_KEYS = ("title", "pattern", "maxLength", "minLength")
_PLAYER_FACING = object()
# A plain assignment, not a `type` alias: pydantic must read the metadata inside it.
PlayerFacing = Annotated[str, _PLAYER_FACING]
_TOOLS: Marks = {}
_ACTIONS: Marks = {}
_EDITS: Marks = {}


# No docstring: pydantic would publish it as the schema's `description`.
class NoArgs(Frozen):
    pass


@dataclass(frozen=True, slots=True)
class MasterTool:
    name: str
    description: str
    args: type[BaseModel]

    @property
    def schema(self) -> dict[str, JsonValue]:
        return deepcopy(tool_schema(self.args))


class ToolSurface(Protocol):
    @property
    def must_stop(self) -> bool: ...
    @property
    def nudge(self) -> str: ...

    def published_tools(self) -> tuple[MasterTool, ...]: ...
    def call_tool(self, name: str, arguments: str | dict[str, JsonValue]) -> str: ...


def tool[F: Callable[..., Sequence[Fact]]](method: F) -> F:
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


def edit[F: Callable[..., None]](method: F) -> F:
    _EDITS[method] = _args_of(method)
    return method


def marked_methods(
    engine: object, mark: Literal["tool", "action", "edit"]
) -> dict[str, MasterTool]:
    marks = {"tool": _TOOLS, "action": _ACTIONS, "edit": _EDITS}[mark]
    return {
        name: MasterTool(
            name,
            " ".join(cleandoc(function.__doc__ or "").split()) if mark == "tool" else "",
            marks[function],
        )
        for name, function in _marked(engine, marks, mark).items()
    }


def player_facing_texts(parsed: BaseModel) -> Iterator[str]:
    return _player_facing_texts(parsed, type(parsed))


@cache
def tool_schema(model: type[BaseModel]) -> dict[str, JsonValue]:
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})
    _inline_refs(schema, defs)
    _normalize(schema)
    return schema


def render_schema(model: type[BaseModel]) -> str:
    return json.dumps(tool_schema(model), indent=2, ensure_ascii=False)


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


def _player_facing_texts(
    value: object, annotation: object, *, player_facing: bool = False
) -> Iterator[str]:
    origin = get_origin(annotation)
    members = get_args(annotation)
    if player_facing and isinstance(value, str):
        yield value
    elif isinstance(value, BaseModel):
        for key, info in type(value).model_fields.items():
            yield from _player_facing_texts(
                getattr(value, key), info.annotation, player_facing=_PLAYER_FACING in info.metadata
            )
    elif origin is Annotated:
        yield from _player_facing_texts(
            value, members[0], player_facing=_PLAYER_FACING in members[1:]
        )
    elif origin in (Union, UnionType):
        for member in members:
            yield from _player_facing_texts(value, member)
    elif origin in (tuple, list) and isinstance(value, tuple | list):
        for item in cast("Sequence[object]", value):
            yield from _player_facing_texts(item, members[0])


def _args_of(function: Callable[..., object]) -> type[BaseModel]:
    parameters = list(signature(function).parameters.values())
    args = parameters[2] if len(parameters) > 2 else None
    if args is not None and args.name.removeprefix("_") == "args":
        annotation: object = args.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation
    raise ValueError(f"{function.__qualname__} does not take (self, draft, args, rng)")


def _inline_refs(node: JsonValue, defs: Mapping[str, JsonValue]) -> None:
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
