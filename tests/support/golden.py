import json
import os
from difflib import unified_diff
from itertools import islice
from pathlib import Path

from pydantic import BaseModel

from rulehall.core.tools import schema_text

ENCODING = "utf-8"
FIXTURES = Path(__file__).parents[1] / "core" / "fixtures"
REGENERATE = os.environ.get("RULEHALL_GOLDEN_REGEN") == "1"
DIFF_LINES = 40
RULES_MARKER = "<<rules.md>>"
SCHEMA_MARKER = "<<schema>>"
ANSWER_WITH = "# ANSWER WITH\n"


def masked(prompt: str) -> str:
    """The schema is checked elsewhere; a marker keeps this fixture from rewriting."""
    head, sep, _ = prompt.partition(ANSWER_WITH)
    return f"{head}{sep}{SCHEMA_MARKER}\n" if sep else prompt


def masked_master(prompt: str, instructions: str) -> str:
    """`instructions` must be the text the splice used, or the check is skipped in silence."""
    needle = instructions.strip()
    if not needle:
        raise AssertionError("instructions must not be empty")
    if needle not in prompt:
        raise AssertionError("the instructions are not spliced into the prompt verbatim")
    return masked(prompt.replace(needle, RULES_MARKER))


def golden(path: Path, actual: str) -> None:
    """Regenerate fixtures only when explicitly enabled, and never report that run as passing."""
    if REGENERATE:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding=ENCODING)
        return
    if not path.is_file():
        raise AssertionError(f"no fixture at {path}: regenerate with RULEHALL_GOLDEN_REGEN=1")
    expected = path.read_text(encoding=ENCODING)
    if actual != expected:
        raise AssertionError(f"{path} drifted from its fixture:\n{_diff(expected, actual)}")


def golden_json(path: Path, actual: object) -> None:
    golden(path, json.dumps(actual, indent=2, ensure_ascii=False) + "\n")


def golden_schema(path: Path, model: type[BaseModel]) -> None:
    """Pins `schema_text`, the rendering every role's prompt carries."""
    golden(path, schema_text(model) + "\n")


def _diff(expected: str, actual: str) -> str:
    lines = unified_diff(
        expected.splitlines(), actual.splitlines(), "fixture", "actual", lineterm="", n=1
    )
    return "\n".join(islice(lines, DIFF_LINES))
