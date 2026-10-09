from pathlib import Path

from rulehall.screens.pokemon.registry import SCREEN_FACTORIES as POKEMON_SCREEN_FACTORIES
from rulehall.screens.pokemon.registry import STYLES as POKEMON_STYLES
from rulehall.ui.surfaces import ScreenFactories

STYLES: tuple[Path, ...] = (*POKEMON_STYLES,)


def build_screen_factories() -> ScreenFactories:
    families = (POKEMON_SCREEN_FACTORIES,)
    ids = [surface_id for family in families for surface_id in family]
    if len(set(ids)) != len(ids):
        raise ValueError(f"surface ids are not unique: {ids}")
    return {surface_id: factory for family in families for surface_id, factory in family.items()}
