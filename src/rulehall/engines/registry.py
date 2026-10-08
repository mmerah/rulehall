from pathlib import Path

from rulehall.core.validation import EngineId
from rulehall.engines.engine import AnyEngine
from rulehall.engines.loner4e.engine import Loner4eEngine
from rulehall.engines.pokemon.journey.engine import PokemonEngine
from rulehall.engines.tunnelgoons.engine import TunnelGoonsEngine
from rulehall.engines.twentyfourxx.engine import TwentyFourXXEngine


def build_engines(packs_dir: Path) -> dict[EngineId, AnyEngine]:
    engines = tuple(
        engine(packs_dir / engine.id)
        for engine in (Loner4eEngine, TunnelGoonsEngine, TwentyFourXXEngine, PokemonEngine)
    )
    ids = [engine.id for engine in engines]
    if len(set(ids)) != len(ids):
        raise ValueError(f"engine ids are not unique: {ids}")
    return {engine.id: engine for engine in engines}
