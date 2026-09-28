from collections.abc import Callable
from pathlib import Path

from nicegui import Client, ui
from support.game import KEY
from support.table import ENGINES_BUILT, offline_settings

from rulehall.app.catalog import LauncherCatalog, scenario_models
from rulehall.core.stores import Library, SaveStore
from rulehall.ui.home import LaunchForm
from rulehall.ui.widgets import DICE_CLIP, SOUNDS_DIR


async def test_an_unresumable_save_renders_no_start_button(
    tmp_path: Path, page: Callable[[], Client]
) -> None:
    settings = offline_settings(tmp_path)
    _ = (tmp_path / f"{KEY.save_id}.json").write_bytes(b"\xff\xfe not text")
    library = Library(settings.scenarios_dir, settings.characters_dir)
    catalog = LauncherCatalog.read(
        library, SaveStore(settings.saves_dir), ENGINES_BUILT, scenario_models(ENGINES_BUILT)
    )
    assert catalog.unresumable == (KEY.save_id,)

    client = page()
    form = LaunchForm(catalog)
    form.scenario_id = KEY.scenario_id
    form.character_id = KEY.character_id

    await form.draw.refresh()

    elements = client.elements.values()
    assert not any(isinstance(element, ui.button) for element in elements)
    assert any(
        isinstance(element, ui.label) and "cannot be resumed" in element.text
        for element in elements
    )


def test_each_clip_the_page_plays_has_a_wav_in_the_sounds_directory() -> None:
    present = {clip.stem for clip in SOUNDS_DIR.glob("*.wav")}

    assert DICE_CLIP in present
