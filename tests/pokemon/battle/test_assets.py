from pathlib import Path

import pytest

from rulehall.core.validation import Refusal
from rulehall.engines.pokemon.battle import battling
from rulehall.engines.pokemon.battle.battling import ASSETS_HINT, ASSETS_VERSION, ShowdownBattles


def test_a_marker_with_an_old_assets_version_refuses_a_battle_with_the_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    simulator = tmp_path / "pokemon-showdown"
    simulator.touch()
    monkeypatch.setattr(battling, "SIMULATOR", simulator)
    marker = tmp_path / "complete"
    monkeypatch.setattr(battling, "ASSETS_COMPLETE", marker)

    with pytest.raises(Refusal, match="not fetched") as missing:
        ShowdownBattles().simulator_argv()
    marker.write_text("1\n")
    with pytest.raises(Refusal) as old:
        ShowdownBattles().simulator_argv()
    marker.write_text(ASSETS_VERSION.read_text())

    assert str(missing.value) == str(old.value) == ASSETS_HINT
    assert ShowdownBattles().simulator_argv()[0] == "node"
