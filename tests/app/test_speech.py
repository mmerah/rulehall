from asyncio import gather, sleep
from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import JsonValue
from support.table import offline_settings, updated

from rulehall.app.speech import Speaker
from rulehall.config import ApiProvider, LiveSettings, ProviderConfig
from rulehall.core.log import SpokenLine
from rulehall.core.validation import Refusal

NARRATION = SpokenLine(text="The door creaks open.")
WARDEN = SpokenLine(speaker_id="brass-warden", speaker="Brass Warden", voice="other", text="Halt.")
MARA = SpokenLine(speaker_id="mara", speaker="Mara", voice="feminine", text="Row on.")
REFUSED = SpokenLine(text="Nobody may voice this.")


def _speaker(saves: Path, *, enabled: bool = True, provider: ApiProvider = "openrouter") -> Speaker:
    settings = updated(offline_settings(), speech={"enabled": enabled, "provider": provider})
    return Speaker(live_settings=LiveSettings(settings), saves=saves)


def _scripted(monkeypatch: pytest.MonkeyPatch) -> list[Mapping[str, JsonValue]]:
    posted: list[Mapping[str, JsonValue]] = []

    async def post(
        _provider: ProviderConfig, _endpoint: str, *, json: Mapping[str, JsonValue], **_: float
    ) -> bytes:
        posted.append(json)
        await sleep(0)  # a real request suspends; without this nothing can interleave
        if json["input"] == REFUSED.text:
            raise Refusal("the provider failed: 400")
        return b"ID3"

    monkeypatch.setattr("rulehall.app.speech.post", post)
    return posted


async def test_concurrent_speech_of_the_same_lines_generates_each_clip_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = _scripted(monkeypatch)
    speaker = _speaker(tmp_path)
    _ = await gather(speaker.speak((NARRATION, WARDEN)), speaker.speak((NARRATION, WARDEN)))
    assert [body["input"] for body in posted] == [NARRATION.text, WARDEN.text]
    assert speaker.find_clip(NARRATION) is not None
    assert speaker.find_clip(WARDEN) is not None
    assert speaker.claims.held == set()


async def test_a_character_keeps_one_voice_of_its_kind_and_narration_uses_the_narrator_voice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = _scripted(monkeypatch)
    speaker = _speaker(tmp_path)
    again = WARDEN.model_copy(update={"text": "Turn back."})
    await speaker.speak((NARRATION, WARDEN, again, MARA))
    speech = speaker.live_settings.current.speech
    narrator, first, second, mara = (body["voice"] for body in posted)
    assert narrator == speech.narrator == "bm_george"
    assert first == second
    assert first in speech.pool("other")
    assert mara in speech.pool("feminine")
    assert narrator not in speech.pool("masculine")


async def test_an_other_voice_without_an_other_list_draws_from_both_genders_but_the_narrator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = _scripted(monkeypatch)
    settings = updated(
        offline_settings(), speech={"enabled": True, "speech_model": "deepgram/aura-2"}
    )
    speaker = Speaker(live_settings=LiveSettings(settings), saves=tmp_path)
    await speaker.speak((NARRATION, WARDEN))
    choice = settings.speech.speech_choice
    both = {voice.id for voice in choice.feminine + choice.masculine}
    pool = settings.speech.pool("other")
    narrator, warden = (body["voice"] for body in posted)
    assert choice.other == ()
    assert narrator == "aura-2-draco-en"
    assert set(pool) == both - {"aura-2-draco-en"}
    assert warden in pool


async def test_accents_are_folded_in_the_spoken_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = _scripted(monkeypatch)
    await _speaker(tmp_path).speak((SpokenLine(text="A wild Pokémon café."),))
    assert [body["input"] for body in posted] == ["A wild Pokemon cafe."]


async def test_the_local_provider_asks_for_the_local_model_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = _scripted(monkeypatch)
    await _speaker(tmp_path, provider="local").speak((NARRATION,))
    assert [body["model"] for body in posted] == ["kokoro"]


async def test_no_clip_is_found_or_generated_when_speech_is_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    posted = _scripted(monkeypatch)
    await _speaker(tmp_path).speak((NARRATION,))
    speaker = _speaker(tmp_path, enabled=False)
    await speaker.speak((WARDEN,))
    assert len(posted) == 1
    assert speaker.find_clip(NARRATION) is None


async def test_a_refused_line_is_reported_and_the_next_line_still_speaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = _scripted(monkeypatch)
    speaker = _speaker(tmp_path)
    await speaker.speak((REFUSED, NARRATION))
    assert speaker.clip_refused(REFUSED)
    assert not speaker.clip_refused(NARRATION)
    assert speaker.find_clip(NARRATION) is not None
