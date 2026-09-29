import asyncio
import json
from pathlib import Path

import pytest
from pydantic import Field
from support.game import TOMAS, open_game
from support.table import (
    narrated,
    offline_settings,
    updated,
)

import rulehall.app.processes as processes
from rulehall.app.cli_roles import CodexDriver
from rulehall.app.roles import ProviderRoleRunner, final_message
from rulehall.config import LiveSettings
from rulehall.core.decisions import PlayerInput
from rulehall.core.log import Narration
from rulehall.core.prompt import Prompt
from rulehall.core.tools import tool_schema
from rulehall.core.validation import Frozen, Refusal, Slug
from rulehall.engines.args import ACTOR


class _SchemaProbe(Frozen):
    actor_id: Slug | None = Field(default=None, description=ACTOR)
    title: str = Field(default="", description="a field whose name spells a noise key")


def test_tool_schema_drops_noise_and_collapses_a_nullable() -> None:
    schema = tool_schema(_SchemaProbe)

    dumped = json.dumps(schema)
    assert '"pattern"' not in dumped
    assert "title" not in schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert "title" in properties
    actor_id = properties["actor_id"]
    assert isinstance(actor_id, dict)
    assert actor_id["type"] == ["string", "null"]


async def test_a_change_lands_on_the_draft_as_it_is_made_and_on_disk_at_the_end(
    tmp_path: Path,
) -> None:
    counts: list[int] = []

    table = open_game(tmp_path)

    def script() -> None:
        _ = table.call("enter", {"target_id": "Not An Id"})
        _ = table.call("enter", {"target_id": TOMAS})
        turn = table.session.turn
        assert turn is not None
        counts.append(len(turn.facts))

    table.roles.turns.append(script)
    table.roles.answers["narrator"] = [narrated("A monk steps in from the cold.")]
    await table.session.choose(PlayerInput(text="I wait for whoever comes."))

    assert "target_id" in table.refusals[0]
    assert counts == [1]
    saved = table.saved()
    assert TOMAS in saved.world.scene.here_ids
    assert len(saved.log_entries()[-1].facts) == 1


async def test_abandoning_a_spawn_kills_the_process_group_it_started(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The CLI's own children must not outlive the turn, and the killed child is reaped."""
    killed: list[int] = []
    reaped: list[int] = []

    class FakeStdin:
        def write(self, data: bytes) -> None:
            del data

        def close(self) -> None:
            pass

    class FakeProcess:
        pid = 1234
        returncode = None

        stdin = FakeStdin()
        stdout = asyncio.StreamReader()

        async def wait(self) -> int:
            reaped.append(self.pid)
            return 0

    async def fake_create(*_argv: str, **_kwargs: object) -> FakeProcess:
        return FakeProcess()

    def found(name: str, path: str | None) -> str:
        del path
        return name

    monkeypatch.setattr(processes.subprocess, "create_subprocess_exec", fake_create)
    monkeypatch.setattr(processes.shutil, "which", found)
    monkeypatch.setattr(processes, "_kill_tree", killed.append)
    settings = updated(
        offline_settings(tmp_path),
        roles={"master": {"timeout": 0.01}},
    )

    with pytest.raises(Refusal, match="answered nothing in"):
        _ = await ProviderRoleRunner(LiveSettings(settings)).answer(
            "master", Prompt(system="", user="go")
        )
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
    said = CodexDriver().read_result(CODEX_STREAM)

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
