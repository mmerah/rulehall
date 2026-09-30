import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path

from rulehall.app.background import BackgroundTasks, Claims
from rulehall.app.http_client import post
from rulehall.config import LiveSettings, SpeechConfig
from rulehall.core.log import SpokenLine
from rulehall.core.stores import publish
from rulehall.core.validation import Loose, Refusal, parse_json

LOGGER = logging.getLogger(__name__)

VOICE_DIR = "voice"
RECORDING_SUFFIXES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4"}


@dataclass(frozen=True, slots=True)
class Speaker:
    live_settings: LiveSettings
    saves: Path
    claims: Claims = field(default_factory=Claims)
    tasks: BackgroundTasks = field(default_factory=BackgroundTasks)
    refused: set[str] = field(default_factory=set)

    def find_clip(self, line: SpokenLine) -> Path | None:
        speech = self.live_settings.current.speech
        if not speech.enabled:
            return None
        path = self._clip_path(_clip_key(speech, line))
        return path if path.is_file() else None

    def clip_refused(self, line: SpokenLine) -> bool:
        return _clip_key(self.live_settings.current.speech, line) in self.refused

    def speak_later(self, lines: Sequence[SpokenLine]) -> None:
        self.tasks.start(self.speak(lines), "speech failed")

    async def speak(self, lines: Sequence[SpokenLine]) -> None:
        speech = self.live_settings.current.speech
        if not speech.enabled:
            return
        for line in lines:
            key = _clip_key(speech, line)
            try:
                with self.claims.hold(key) as speaking:
                    if speaking and not self._clip_path(key).is_file():
                        self.refused.discard(key)
                        await self._generate_clip(speech, line, key)
            except Refusal as failed:
                self.refused.add(key)
                LOGGER.warning("speech generation failed: %s", failed)

    async def transcribe(self, audio: bytes, mime: str) -> str:
        settings = self.live_settings.current
        if not settings.speech.enabled:
            raise Refusal("speech is off")
        suffix = RECORDING_SUFFIXES.get(mime.partition(";")[0].strip())
        if suffix is None:
            raise Refusal(f"a recording in {mime!r} is not supported")
        content = await post(
            settings.providers.for_name(settings.speech.provider),
            "audio/transcriptions",
            timeout=settings.speech.timeout,
            files={"file": (f"speech{suffix}", audio, mime)},
            data={"model": settings.speech.transcription_model},
        )
        text = parse_json(_Transcript, content).text.strip()
        if not text:
            raise Refusal("the transcription held no words")
        return text

    async def close(self) -> None:
        await self.tasks.close()

    def _clip_path(self, key: str) -> Path:
        return self.saves / VOICE_DIR / f"{key}.mp3"

    async def _generate_clip(self, speech: SpeechConfig, line: SpokenLine, key: str) -> None:
        audio = await post(
            self.live_settings.current.providers.for_name(speech.provider),
            "audio/speech",
            timeout=speech.timeout,
            json={
                "model": speech.speech_model,
                "input": line.text,
                "voice": _voice_for(speech, line),
                "response_format": "mp3",
            },
        )
        if not audio:
            raise Refusal("speech reply held no audio")
        publish(self._clip_path(key), lambda staged: staged.write_bytes(audio))


class _Transcript(Loose):
    text: str


def _voice_for(speech: SpeechConfig, line: SpokenLine) -> str:
    if line.voice is None or line.speaker_id is None:
        return speech.narrator_voice
    voices = speech.pool(line.voice)
    return voices[int(_digest(line.speaker_id), 16) % len(voices)]


def _clip_key(speech: SpeechConfig, line: SpokenLine) -> str:
    return _digest(f"{speech.speech_model}\0{_voice_for(speech, line)}\0{line.text}")[:12]


def _digest(text: str) -> str:
    return sha1(text.encode(), usedforsecurity=False).hexdigest()
