from functools import cache
from pathlib import Path
from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from rulehall.core.log import Voice
from rulehall.core.stores import read_model
from rulehall.core.validation import Frozen, check_unique

type SpeechModel = Literal[
    "hexgrad/kokoro-82m",
    "minimax/speech-2.8-turbo",
    "minimax/speech-2.8-hd",
    "microsoft/mai-voice-2",
    "deepgram/aura-2",
    "deepgram/flux-tts:free",
    "x-ai/grok-voice-tts-1.0",
]
VOICES_FILE = Path(__file__).parent / "voices.json"


class VoiceChoice(Frozen):
    id: str
    label: str
    note: str


class SpeechModelChoice(Frozen):
    label: str
    note: str
    local_model: str | None
    narrator: str
    feminine: tuple[VoiceChoice, ...] = Field(min_length=1)
    masculine: tuple[VoiceChoice, ...] = Field(min_length=1)
    other: tuple[VoiceChoice, ...]

    @model_validator(mode="after")
    def _valid_voices(self) -> Self:
        check_unique("voice ids", (choice.id for choice in self._choices()))
        if self.narrator not in self.voice_ids():
            raise ValueError(f"the narrator {self.narrator!r} is none of the model's voices")
        return self

    def voice_ids(self) -> set[str]:
        return {choice.id for choice in self._choices()}

    def pool(self, voice: Voice, narrator: str) -> tuple[str, ...]:
        match voice:
            case "feminine":
                choices = self.feminine
            case "masculine":
                choices = self.masculine
            case "other":
                choices = self.other
        pool = tuple(choice.id for choice in choices if choice.id != narrator)
        if pool or voice != "other":
            return pool
        return self.pool("feminine", narrator) + self.pool("masculine", narrator)

    def _choices(self) -> tuple[VoiceChoice, ...]:
        return self.feminine + self.masculine + self.other


class VoiceCatalogue(Frozen):
    models: dict[SpeechModel, SpeechModelChoice]

    @model_validator(mode="after")
    def _every_speech_model(self) -> Self:
        if set(self.models) != set(get_args(SpeechModel.__value__)):
            raise ValueError("the voice catalogue holds each speech model, and no other")
        return self

    def require_model(self, model_id: SpeechModel) -> SpeechModelChoice:
        return self.models[model_id]


@cache
def voice_catalogue() -> VoiceCatalogue:
    return read_model(VOICES_FILE, VoiceCatalogue)
