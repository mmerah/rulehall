import json
from pathlib import Path

import pytest
from support.engine_dir import install_engine_dir
from support.table import (
    ENGINE_IDS,
    ENGINES_BUILT,
    LONER3E,
    change,
    game,
)

from rulehall.core.io import ENCODING
from rulehall.core.model import Character
from rulehall.core.validation import EngineId, Refusal
from rulehall.engines.entities import PLAYER_ID, Person
from rulehall.engines.loner3e.world import Loner3eWorld
from rulehall.engines.tunnelgoons.engine import TunnelGoonsEngine


def _engine_at(tmp_path: Path) -> type[TunnelGoonsEngine]:
    """A shipped engine read out of a directory a test writes, so construction is the subject."""

    class Installed(TunnelGoonsEngine):
        directory = tmp_path

    return Installed


def test_the_clock_arms_on_reaching_the_tempo_and_starts_over() -> None:
    engine, state = game(LONER3E)
    draft = state.draft()

    for _ in range(Loner3eWorld.meanwhile_every - 1):
        engine.count_turn(draft)
    assert (draft.world.turns_since_meanwhile, draft.world.meanwhile_due) == (
        Loner3eWorld.meanwhile_every - 1,
        False,
    )

    engine.count_turn(draft)

    assert (draft.world.turns_since_meanwhile, draft.world.meanwhile_due) == (0, True)


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
        sheet=Person(id=PLAYER_ID, name="Wren", brief="", known=True),
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


def test_a_direction_marks_the_draft_and_never_reaches_the_save() -> None:
    engine, state = game(LONER3E)
    draft = state.draft()

    _ = change(engine, draft, "direct", text="the cold off the stone reaches him")

    directed = engine.accept(draft)
    assert directed.directed
    assert "directed" not in json.loads(directed.model_dump_json())
    assert not engine.restore(directed.model_dump_json()).directed
