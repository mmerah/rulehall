import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[2] / "src" / "rulehall"
ENGINES = (
    "rulehall.engines.loner3e",
    "rulehall.engines.tunnelgoons",
    "rulehall.engines.twentyfourxx",
    "rulehall.engines.pokemon",
)
# The composition root builds the installed concrete engines.
ROOTS = {"engines/registry.py"}
# Flow: core <- engines <- app <- ui.
LAYERS = ("core", "engines", "app")
# `ui` sits above them all and imports downwards; no page names an engine.
TOPS = {"ui": {"rulehall.engines"}}
# A framework belongs to the layers that own it and to nothing below them.
CONFINED = {
    "nicegui": ("ui",),
    "rulehall.config": ("app", "ui"),
}


def _forbidden(package: str) -> set[str]:
    """What a package may not name: the layers downstream of it, its sibling top, its frameworks."""
    later = LAYERS[LAYERS.index(package) + 1 :] if package in LAYERS else ()
    siblings = (top for top in TOPS if top != package)
    downstream = {f"rulehall.{name}" for name in (*later, *siblings)}
    confined = {name for name, owners in CONFINED.items() if package not in owners}
    return downstream | confined | TOPS.get(package, set())


FORBIDDEN = {package: _forbidden(package) for package in (*LAYERS, *TOPS)}


def _python_files(root: Path) -> tuple[Path, ...]:
    """The pokemon engine keeps its Node project, and the Node packages ship python files."""
    return tuple(path for path in root.rglob("*.py") if "node_modules" not in path.parts)


def _source_files(package: str) -> tuple[Path, ...]:
    module = SOURCE / f"{package}.py"
    files = (module,) if module.is_file() else _python_files(SOURCE / package)
    assert files, (
        f"no python files under src/rulehall/{package}: renamed without updating the tables?"
    )
    return files


def _file_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imports.add(base)
            # `from package import module` stores the module in aliases, not `node.module`.
            imports.update(f"{base}.{alias.name}" for alias in node.names)
    return imports


def _imports(package: str) -> set[str]:
    return {name for path in _source_files(package) for name in _file_imports(path)}


@pytest.mark.parametrize(("package", "forbidden"), FORBIDDEN.items())
def test_packages_import_only_in_the_allowed_direction(
    package: str,
    forbidden: set[str],
) -> None:
    violations = {
        name
        for name in _imports(package)
        if any(name == root or name.startswith(f"{root}.") for root in forbidden)
    }
    assert not violations


def test_the_turn_reads_no_settings() -> None:
    assert not {name for name in _imports("app/turn") if name.startswith("rulehall.config")}


def test_no_module_names_a_concrete_engine() -> None:
    naming = {
        str(path.relative_to(SOURCE))
        for path in _python_files(SOURCE)
        for name in _file_imports(path)
        if name.startswith(ENGINES)
        if not (
            path.is_relative_to(SOURCE / "engines")
            and name.startswith(f"rulehall.engines.{path.relative_to(SOURCE / 'engines').parts[0]}")
        )
    }
    assert naming == ROOTS


def test_no_ui_module_names_a_built_engine_id() -> None:
    """The seam hands the UI a `Look`; no page names an engine id."""
    built_ids = {name.rsplit(".", 1)[-1] for name in ENGINES}
    naming = {
        str(path.relative_to(SOURCE))
        for path in _source_files("ui")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if isinstance(node, ast.Constant)
        if isinstance(node.value, str) and node.value in built_ids
    }
    assert naming == set()


def test_only_the_pokemon_engine_names_showdown() -> None:
    naming = {
        str(path.relative_to(SOURCE))
        for path in _python_files(SOURCE)
        if not path.is_relative_to(SOURCE / "engines" / "pokemon")
        and "showdown" in path.read_text(encoding="utf-8").lower()
    }
    assert naming == set()
