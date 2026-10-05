from urllib.parse import urlencode

from rulehall.app.catalog import SavedGameKey
from rulehall.core.validation import EngineId, Slug

HOME = "/"
SETTINGS = "/settings"
HALL = "/rules/{engine_id}"
NEW_CHARACTER = HALL + "/character"
NEW_SCENARIO = HALL + "/scenario"
NEW_PACK = HALL + "/pack"
PACKS = HALL + "/packs"
GAME = "/game/{scenario}/{character}"
SOUNDS = "/sounds/"
ICONS = "/icons/"
ASSETS = "/assets"
CHOSEN_CHARACTER = "character"


def game_path(key: SavedGameKey) -> str:
    return GAME.format(scenario=key.scenario_id, character=key.character_id)


def engine_path(route: str, engine_id: EngineId) -> str:
    return route.format(engine_id=engine_id)


def hall_path(engine_id: EngineId, character_id: Slug | None = None) -> str:
    path = engine_path(HALL, engine_id)
    return path if character_id is None else f"{path}?{urlencode({CHOSEN_CHARACTER: character_id})}"


def assets_route(engine_id: EngineId) -> str:
    return f"{ASSETS}/{engine_id}"
