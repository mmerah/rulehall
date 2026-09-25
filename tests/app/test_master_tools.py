import asyncio
import json
from pathlib import Path
from random import Random

import pytest
from pydantic import Field, JsonValue
from support.game import open_game
from support.table import (
    narrated,
    offline_settings,
    play_turn,
    the_way_on,
    tool_call,
    updated,
)

import rulehall.app.spawn as spawn_module
from rulehall.app.spawn import CodexDriver, RoleRunner, final_message
from rulehall.core.play import Answer, Narration
from rulehall.core.prompt import Prompt
from rulehall.core.tools import schema_of
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.args import ACTOR
from rulehall.engines.entities import PLAYER_ID
from rulehall.engines.scenes.engine import MOVE_ON, WAY_UNWRITTEN


class _SchemaProbe(Frozen):
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    title: str = Field(default="", description="a field whose name spells a noise key")


def test_schema_of_drops_noise_and_collapses_a_nullable() -> None:
    schema = schema_of(_SchemaProbe)

    dumped = json.dumps(schema)
    assert '"pattern"' not in dumped
    assert "title" not in schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert "title" in properties
    actor_id = properties["actor_id"]
    assert isinstance(actor_id, dict)
    assert actor_id["type"] == ["string", "null"]


VAULT_MAP = "vault-map"
PURSUIT = "Out into the cloister walk."
LEFT = tool_call("next_scene", pursuit=PURSUIT)
MARA = "mara"
A_CONFLICT: dict[str, JsonValue] = {
    "what": "Wrest the ledger from her",
    "actor_id": PLAYER_ID,
    "question": "Does he wrest the ledger out of her hands?",
    "target_id": MARA,
}
ARC = "Farther in, the chapter house still holds what Mara came for, and has not yet been found."
A_SCENE = {
    "place_id": "cloister-walk",
    "title": "The Cloister Walk",
    "situation": "Rain drums the open arcade and the flagstones run black with it, and Mara waits "
    "at the far end with the lantern shuttered to a slit.",
    "present": ["mara"],
    "hidden": ["tomas"],
    "arc": ARC,
}
RECAP = (
    "The player left the abbot's study behind, lantern shuttered, and made for the cloister "
    "walk with Mara close behind them."
)


def _scene(**changes: object) -> str:
    return json.dumps(A_SCENE | {"recap": RECAP} | changes)


async def test_a_change_lands_on_the_draft_as_it_is_made_and_on_disk_at_the_end(
    tmp_path: Path,
) -> None:
    counts: list[int] = []

    table = open_game(tmp_path)

    def script() -> None:
        _ = table.call("reveal", {"target_id": VAULT_MAP, "junk": 1})
        _ = table.call("reveal", {"target_id": VAULT_MAP})
        turn = table.service.turn
        assert turn is not None
        counts.append(len(turn.facts))

    table.spawner.turns.append(script)
    table.spawner.answers["narrator"] = [narrated("A chart, under the stone.")]
    await table.service.play(Answer(text="I lever up the flagstone."))

    assert "not permitted" in table.refusals[0]
    assert counts == [1]
    saved = table.saved()
    assert saved.world.require(VAULT_MAP).known
    assert len(saved.exchanges()[-1].facts) == 1


async def test_an_open_decision_blocks_every_other_tool_until_the_player_answers(
    tmp_path: Path,
) -> None:
    """An unfinished conflict: nothing else lands until the player's next message answers it."""
    table = open_game(tmp_path, rng=Random(0))

    state = await play_turn(
        table,
        "I grab for the ledger in her hands.",
        ("roll", A_CONFLICT),
        tool_call("reveal", target_id=VAULT_MAP),
        narration="She holds on.",
    )

    assert state.pending is not None
    assert any("waiting on the player" in answer for answer in table.answers)
    assert not state.world.require(VAULT_MAP).known

    state = await play_turn(table, "I let it be.", narration="You step back.")
    assert state.pending is None


async def test_next_scene_asks_the_player_and_writes_nothing_yet(tmp_path: Path) -> None:
    table = open_game(tmp_path)

    state = await play_turn(
        table,
        "I have what I came for.",
        the_way_on(),
        narration="The flagstone settles back.",
    )

    assert len(state.exchanges()) == 1
    # An offer, not a decision: nothing waits on the player and the scene is still playable.
    assert state.pending is None
    assert state.world.scene.way_offered
    assert not any(role == "worldsmith" for role, _ in table.spawner.prompts)


async def test_a_departure_crosses_after_the_leaving_turn_and_keeps_the_notes(
    tmp_path: Path,
) -> None:
    """One adjudication: the master played the leaving, so the crossing needs no second turn."""
    table = open_game(tmp_path)
    table.spawner.answers["worldsmith"] = [_scene()]
    table.service.save(updated(table.state, notes=["the adventure's end applies"]))

    state = await play_turn(table, "I go.", LEFT, arrival="The cold meets you.")

    assert [role for role, _ in table.spawner.prompts] == [
        "master",
        "narrator",
        "worldsmith",
        "narrator",
    ]
    assert state.notes == []
    assert state.log[-2].exchanges[-1].words == "I go."
    assert state.world.scene.title == "The Cloister Walk"
    assert not state.world.scene.way_offered


async def test_the_way_on_is_offered_once_and_a_departure_consumes_it(tmp_path: Path) -> None:
    table = open_game(tmp_path)
    table.spawner.answers["worldsmith"] = [_scene()]

    _ = await play_turn(table, "I go.", the_way_on())
    _ = await play_turn(table, "I linger.", the_way_on())
    assert "already offers" in table.refusals[-1]

    state = await play_turn(table, PURSUIT, LEFT, way_on=MOVE_ON.id, arrival="Rain.")

    assert state.world.scene.title == "The Cloister Walk"
    assert not state.world.scene.way_offered


async def test_a_scene_the_world_has_outgrown_is_dropped_and_the_offer_kept(
    tmp_path: Path,
) -> None:
    """The bar sees the turn's own changes; a failed write leaves the way on as it was."""
    table = open_game(tmp_path)
    table.spawner.answers["worldsmith"] = [_scene(), _scene()]

    _ = await play_turn(table, "I have what I came for.", the_way_on())
    state = await play_turn(table, PURSUIT, tool_call("enter", target_id="tomas"), LEFT)

    unwritten = state.exchanges()[-1]
    assert unwritten.cause == "story"
    assert unwritten.facts[0] == WAY_UNWRITTEN
    assert state.world.scene.title == "The Abbot's Study"
    assert state.world.scene.way_offered
    assert state.request is None


async def test_a_worldsmith_that_fails_leaves_the_scene_unchanged_and_says_why(
    tmp_path: Path,
) -> None:
    table = open_game(tmp_path)

    state = await play_turn(table, "I go.", LEFT)

    assert state.exchanges()[-1].facts[0] == WAY_UNWRITTEN
    assert table.service.state.world.scene.title == "The Abbot's Study"


async def test_abandoning_a_spawn_kills_the_process_group_it_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CLI's own children must not outlive the turn, and the killed child is reaped."""
    killed: list[int] = []
    reaped: list[int] = []

    class FakeProcess:
        pid = 1234
        returncode = None

        stdout = asyncio.StreamReader()

        async def wait(self) -> int:
            reaped.append(self.pid)
            return 0

    async def fake_create(*_argv: str, **_kwargs: object) -> FakeProcess:
        return FakeProcess()

    def found(name: str, path: str | None) -> str:
        del path
        return name

    monkeypatch.setattr(spawn_module.subprocess, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(spawn_module.shutil, "which", found)
    monkeypatch.setattr(spawn_module, "_kill_tree", killed.append)
    settings = updated(
        offline_settings(tmp_path),
        roles={"master": {"timeout": 0.01}},
    )

    with pytest.raises(Refusal, match="answered nothing in"):
        await RoleRunner(settings).run("master", Prompt(system="", user="go"), None)
    assert killed == [1234]
    assert reaped == [1234]


# What `codex exec --json` actually printed, banner line and all.
CODEX_STREAM = """Reading additional input from stdin...
{"type":"thread.started","thread_id":"01a055c7"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"{\\"lines\\": \
[{\\"speaker_id\\": null, \\"text\\": \\"ok\\"}]}"}}
{"type":"turn.completed","usage":{"input_tokens":16174,"output_tokens":20}}
"""


def test_a_codex_event_stream_reads_as_the_agent_message_it_carries() -> None:
    said = CodexDriver().read_result(CODEX_STREAM).text

    assert said == '{"lines": [{"speaker_id": null, "text": "ok"}]}'
    assert [line.text for line in Narration.model_validate_json(said).lines] == ["ok"]


@pytest.mark.parametrize(
    ("output", "wanted"),
    (
        ('{"lines": [{"speaker_id": null, "text": "ok"}]}', None),
        ('Here it is:\n{"lines": [{"speaker_id": null, "text": "ok"}]}', None),
        ('```json\n{"lines": [{"speaker_id": null, "text": "ok"}]}\n```', None),
        (
            'I read:\n```py\nx = 1\n```\nAnswer:\n{"lines": [{"speaker_id": null, "text": "ok"}]}',
            None,
        ),
    ),
    ids=("bare", "after prose", "fenced", "a fence that is not the answer"),
)
def test_every_shape_a_cli_answers_in_parses_to_the_same_narration(
    output: str, wanted: str | None
) -> None:
    narration = Narration.model_validate_json(final_message(output))

    assert [line.text for line in narration.lines] == ["ok"]
    if wanted is not None:
        assert final_message(output) == wanted
