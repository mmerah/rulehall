import pytest
from pydantic import ValidationError

from rulehall.core.decisions import ActionOption
from rulehall.core.views import Panel, PanelRow, PlayerView, Subject

DROP = ActionOption(id="drop", name="Drop", action_name="drop_here", args={"item_id": "rope"})


def _view(*rows: PanelRow) -> PlayerView:
    return PlayerView(
        premise="",
        player=Subject(id="player", name="Wren"),
        scene_title="The Cloister Walk",
        situation="Rain drums the arcade.",
        panels=(Panel(title="Carrying", rows=rows),),
        decision=None,
        ending=None,
        moves=(DROP,),
        hint="Say what Wren does.",
    )


def test_one_option_id_names_one_option_across_moves_and_rows() -> None:
    assert _view(PanelRow(name="Rope", brief="", options=(DROP,))).require_option("drop") == DROP

    lamp = DROP.model_copy(update={"args": {"item_id": "lamp"}})
    with pytest.raises(ValidationError, match="name two options"):
        _ = _view(PanelRow(name="Lamp", brief="", options=(lamp,)))
