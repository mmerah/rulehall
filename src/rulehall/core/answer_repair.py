"""Three answer repairs: a null word to null, a lone string to a list, unknown fields dropped."""

import json
import logging
import re
from collections.abc import Mapping
from functools import cache

from pydantic import BaseModel, JsonValue

from rulehall.core.validation import parse_json

NULL_WORDS = ("null", "None", "")
LOGGER = logging.getLogger(__name__)

type Schema = Mapping[str, JsonValue]


def parse_with_repairs[T: BaseModel](model: type[T], value: JsonValue) -> T:
    return parse_json(model, json.dumps(_mended(value, _schema(model), model)))


@cache
def _schema(model: type[BaseModel]) -> Schema:
    return model.model_json_schema()


def _shapes(schema: Schema, model: type[BaseModel]) -> list[Schema]:
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
    if key in (fields := _as_schema(schema.get("properties"))):
        return _as_schema(fields[key])
    patterns = _as_schema(schema.get("patternProperties"))
    matched = (shape for pattern, shape in patterns.items() if re.search(pattern, key))
    other = next(matched, schema.get("additionalProperties"))
    return None if other is False else _as_schema(other)
