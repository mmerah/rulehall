import ast
import re
from pathlib import Path

import pytest
from support.table import ENGINE_IDS

SOURCE = Path(__file__).parents[2] / "src" / "rulehall"
# The registries are the only modules that name a family;
# the composition root names only the registries.
REGISTRY = "engines/registry.py"
SCREENS_REGISTRY = "screens/registry.py"
COMPOSITION_ROOT = "main.py"
# Flow: core <- engines <- app <- ui <- screens <- main.
LAYERS = ("core", "engines", "app", "ui", "screens", "main")
# A layer that may not see a layer below it.
BLIND = {"ui": {"rulehall.engines"}}
# A framework belongs to the layers that own it and to nothing below them.
CONFINED = {
    "nicegui": ("ui", "screens"),
    "rulehall.config": ("app", "ui", "screens"),
}
GENERIC_SUFFIXES = {".py", ".js", ".css", ".md"}
# What one engine family owns; a shared module names none of it.
CONCEPTS = (
    "showdown",
    "mega",
    "species",
    "natures?",
    "presets?",
    "stat points",
    "pips?",
    "slots?",
    "teams?",
    "catalogs?",
    "trainers?",
    "movesets?",
    "evol[a-z]*",
)
# A legitimate hit, cut out before the scan: the file's own phrases first, then the shared ones.
ALLOWED = {
    "*": ("slots=true", "rulehall.app.catalog import", "runtime.catalog()"),
    "app/runtime.py": ("def catalog(self) -> launchercatalog",),
    "core/tools.py": ("keeps the slot it first took",),
    "ui/create.py": ('add_slot("append")',),
    "ui/hall.py": ("self.catalog",),
    "ui/home.py": (
        "catalog = runtime.catalog()",
        "catalog: launchercatalog",
        "catalog.saves",
        "catalog.scenarios_for",
        "catalog.unresumable",
        "(catalog,",
    ),
    "ui/transcript.py": ("head_slot", "card_slot", "line_slot", 'add_slot("avatar")'),
}


def _forbidden(package: str) -> set[str]:
    """What a package may not name: the layers after it, the layers it is blind to, frameworks."""
    later = {f"rulehall.{name}" for name in LAYERS[LAYERS.index(package) + 1 :]}
    confined = {name for name, owners in CONFINED.items() if package not in owners}
    return later | confined | BLIND.get(package, set())


FORBIDDEN = {package: _forbidden(package) for package in LAYERS}


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


def _names(name: str, root: str) -> bool:
    return name == root or name.startswith(f"{root}.")


def _registered_families(registry: str, layer: str) -> frozenset[str]:
    """The family packages a registry installs; the others are bases they share."""
    return frozenset(
        parts[2]
        for name in _file_imports(SOURCE / registry)
        if len(parts := name.split(".")) > 3
        and parts[:2] == ["rulehall", layer]
        and (SOURCE / layer / parts[2]).is_dir()
    )


FAMILIES = _registered_families(REGISTRY, "engines")
SCREEN_FAMILIES = _registered_families(SCREENS_REGISTRY, "screens")
ENGINE_WORDS = re.compile(
    "|".join(sorted({*FAMILIES, *(word for each in ENGINE_IDS for word in each.split("-"))}))
)
CONCEPT_WORDS = re.compile(rf"(?<![a-z])(?:{'|'.join(CONCEPTS)})(?![a-z])")


def _family(path: Path) -> str | None:
    """The engine family a file belongs to: `engines/<family>/` or `screens/<family>/`."""
    parts = path.relative_to(SOURCE).parts
    if len(parts) > 2 and parts[0] in {"engines", "screens"} and parts[1] in FAMILIES:
        return parts[1]
    return None


def _shared_files() -> tuple[Path, ...]:
    """core/, app/, ui/, main.py and every engines/ file outside a family, but the registry."""
    return (
        *(
            path
            for root in ("core", "app", "ui", "engines")
            for path in (SOURCE / root).rglob("*")
            if path.suffix in GENERIC_SUFFIXES
            and _family(path) is None
            and path.relative_to(SOURCE).as_posix() != REGISTRY
        ),
        SOURCE / COMPOSITION_ROOT,
    )


def _scanned_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").lower()
    for phrase in (*ALLOWED.get(path.relative_to(SOURCE).as_posix(), ()), *ALLOWED["*"]):
        text = text.replace(phrase, "")
    return text


@pytest.mark.parametrize(("package", "forbidden"), FORBIDDEN.items())
def test_packages_import_only_in_the_allowed_direction(
    package: str,
    forbidden: set[str],
) -> None:
    violations = {
        name for name in _imports(package) if any(_names(name, root) for root in forbidden)
    }
    assert not violations


def test_the_turn_reads_no_settings() -> None:
    assert not {name for name in _imports("app/turn") if name.startswith("rulehall.config")}


def test_each_screen_family_is_an_installed_engine_family() -> None:
    screens = SOURCE / "screens"
    packages = {
        path.relative_to(screens).parts[0]
        for path in _python_files(screens)
        if len(path.relative_to(screens).parts) > 1
    }
    assert packages == SCREEN_FAMILIES
    assert SCREEN_FAMILIES <= FAMILIES


def test_no_module_names_a_concrete_engine() -> None:
    naming = {
        path.relative_to(SOURCE).as_posix()
        for path in _python_files(SOURCE)
        for name in _file_imports(path)
        if any(_names(name, f"rulehall.engines.{family}") for family in FAMILIES)
        if not ((family := _family(path)) and _names(name, f"rulehall.engines.{family}"))
    }
    assert naming == {REGISTRY}


def test_only_the_screens_registry_names_a_screen_family() -> None:
    naming = {
        path.relative_to(SOURCE).as_posix()
        for path in _python_files(SOURCE)
        for name in _file_imports(path)
        if any(_names(name, f"rulehall.screens.{family}") for family in SCREEN_FAMILIES)
        if not ((family := _family(path)) and _names(name, f"rulehall.screens.{family}"))
    }
    assert naming == {SCREENS_REGISTRY}


def test_the_composition_root_names_only_the_screens_registry() -> None:
    naming = {
        (path.relative_to(SOURCE).as_posix(), name)
        for path in _python_files(SOURCE)
        if not path.is_relative_to(SOURCE / "screens")
        for name in _file_imports(path)
        if _names(name, "rulehall.screens")
    }
    assert {path for path, _ in naming} == {COMPOSITION_ROOT}
    assert all(_names(name, "rulehall.screens.registry") for _, name in naming)


def test_a_screen_family_imports_only_its_own_screens() -> None:
    naming = {
        path.relative_to(SOURCE).as_posix()
        for path in _python_files(SOURCE / "screens")
        if _family(path)
        for name in _file_imports(path)
        if _names(name, "rulehall.screens")
        and not _names(name, f"rulehall.screens.{_family(path)}")
    }
    assert naming == set()


def test_shared_modules_name_no_engine() -> None:
    naming = {
        path.relative_to(SOURCE).as_posix()
        for path in _shared_files()
        if ENGINE_WORDS.search(path.read_text(encoding="utf-8").lower())
    }
    assert naming == set()


def test_shared_modules_name_no_engine_concept() -> None:
    naming = {
        f"{path.relative_to(SOURCE).as_posix()}: {found.group()}"
        for path in _shared_files()
        if (found := CONCEPT_WORDS.search(_scanned_text(path)))
    }
    assert naming == set()


def test_only_the_pokemon_family_names_showdown() -> None:
    naming = {
        path.relative_to(SOURCE).as_posix()
        for path in _python_files(SOURCE)
        if _family(path) != "pokemon" and "showdown" in path.read_text(encoding="utf-8").lower()
    }
    assert naming == set()
