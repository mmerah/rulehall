import json
from pathlib import Path

import pytest
from support.engine_dir import install_engine_dir
from support.table import (
    ENGINE_IDS,
    ENGINES_BUILT,
    game,
)

from rulehall.core.game import Character
from rulehall.core.stores import ENCODING
from rulehall.core.validation import EngineId, Refusal
from rulehall.engines.sheet import PLAYER_ID, Person
from rulehall.engines.tunnelgoons.engine import TunnelGoonsEngine


def _engine_at(tmp_path: Path) -> type[TunnelGoonsEngine]:
    """A shipped engine read out of a directory a test writes, so construction is the subject."""

    class Installed(TunnelGoonsEngine):
        directory = tmp_path

    return Installed


def test_a_pack_with_doubled_keys_is_refused(tmp_path: Path) -> None:
    install_engine_dir(tmp_path)
    (tmp_path / "packs" / "srd.json").write_text(
        '{"name": "The SRD", "name": "Twice"}', encoding=ENCODING
    )
    with pytest.raises(Refusal, match="duplicate keys"):
        _engine_at(tmp_path)(tmp_path / "written")


@pytest.mark.parametrize("engine_id", ENGINE_IDS)
def test_player_of_refuses_a_sheet_the_engine_does_not_write(engine_id: EngineId) -> None:
    engine = ENGINES_BUILT[engine_id]
    stranger = Character[Person](
        id="wren",
        engine_id=engine.id,
        person=Person(id=PLAYER_ID, name="Wren", brief="", known=True),
    )

    with pytest.raises(Refusal, match="is not a"):
        engine.player_of(stranger)


@pytest.mark.parametrize("engine_id", ENGINE_IDS)
def test_restored_round_trips(engine_id: EngineId) -> None:
    engine, state = game(engine_id)
    assert engine.restore(state.model_dump_json()) == state


def test_restore_refuses_a_save_smuggling_a_pending_request() -> None:
    engine, state = game(ENGINE_IDS[0])
    raw = json.loads(state.model_dump_json())
    raw["request"] = {"kind": "departure", "detail": "smuggled in by hand"}

    with pytest.raises(Refusal, match="request"):
        engine.restore(json.dumps(raw))
