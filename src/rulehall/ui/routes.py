from rulehall.app.catalog import SavedGameKey
from rulehall.core.validation import EngineId

HOME = "/"
CHARACTER = "/character"
SCENARIO = "/scenario"
PACK = "/pack"
PACKS = "/packs"
SETTINGS = "/settings"
GAME = "/game/{scenario}/{character}"
SOUNDS = "/sounds/"
ASSETS = "/assets"


def game_path(key: SavedGameKey) -> str:
    return GAME.format(scenario=key.scenario_id, character=key.character_id)


def assets_route(engine_id: EngineId) -> str:
    return f"{ASSETS}/{engine_id}"
