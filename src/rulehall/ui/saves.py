import logging
from datetime import datetime
from functools import partial

from nicegui import ui

from rulehall.app.catalog import SavedGameKey, SaveOption
from rulehall.app.runtime import Runtime
from rulehall.ui.routes import game_path
from rulehall.ui.widgets import Confirm, attempt, icon_button

LOGGER = logging.getLogger(__name__)
PLAY_ICON = "sym_r_play_arrow"
BROKEN_ICON = "sym_r_broken_image"
DELETE_ICON = "sym_r_delete"
DELETE_FAILED = "Something went wrong. The save was not deleted. Look in the server log."
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR
WEEK = 7 * DAY


def save_line(save: SaveOption, now: datetime) -> str:
    return f"{save.character_label} · turn {save.turn} · {ago(save.saved_at, now)}"


def ago(moment: datetime, now: datetime) -> str:
    seconds = (now - moment).total_seconds()
    if seconds < MINUTE:
        return "just now"
    if seconds < HOUR:
        return f"{int(seconds // MINUTE)} min ago"
    if seconds < DAY:
        return f"{int(seconds // HOUR)}h ago"
    if seconds < 2 * DAY:
        return "yesterday"
    if seconds < WEEK:
        return f"{int(seconds // DAY)} days ago"
    local = moment.astimezone()
    return f"{local.day} {local:%b}"


def open_game(key: SavedGameKey) -> None:
    LOGGER.info("opening %r", key.save_id)
    ui.navigate.to(game_path(key))


def delete_button(runtime: Runtime, save_id: str) -> None:
    icon_button(DELETE_ICON, "Delete", partial(_confirm_delete, runtime, save_id))


async def _confirm_delete(runtime: Runtime, save_id: str) -> None:
    dialog = Confirm(keep="Keep", confirm="Delete")
    confirmed = await dialog.ask(f"Delete the save {save_id!r}? It cannot be brought back.")
    dialog.delete()
    if confirmed and await attempt(partial(runtime.delete_save, save_id), failed=DELETE_FAILED):
        ui.navigate.reload()
