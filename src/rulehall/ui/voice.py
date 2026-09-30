from collections import deque
from collections.abc import Sequence
from time import monotonic

from rulehall.app.game_session import GameSession
from rulehall.core.log import SpokenLine
from rulehall.ui.widgets import Speech, warn


class VoicePlayer:
    def __init__(self, session: GameSession, speech: Speech) -> None:
        self.session = session
        self.speech = speech
        self.auto_read = False
        self.queued: deque[tuple[SpokenLine, int]] = deque()
        self.head_queued_at = monotonic()
        self.speaking_id: int | None = None
        self.off_screen = False
        self.replay_bubble_id: int | None = None

    def hear(self, landed: Sequence[tuple[SpokenLine, int]]) -> None:
        if self.auto_read and landed:
            self.session.speak_later([line for line, _ in landed])
            if not self.queued:
                self.head_queued_at = monotonic()
            self.queued.extend(landed)
        self.drain()

    def read_aloud(self, line: SpokenLine, bubble_id: int) -> None:
        if bubble_id in (self.speaking_id, self.replay_bubble_id):
            self.stop()
            return
        self.stop()
        self.queued.append((line, bubble_id))
        self.replay_bubble_id = bubble_id
        self.head_queued_at = monotonic()
        if self.session.find_clip(line) is None:
            self.session.speak_later([line])
            self.speech.wait(bubble_id)
        self.drain()

    def show_speaking(self, bubble_id: int | None, *, off_screen: bool) -> None:
        self.speaking_id = bubble_id
        self.off_screen = off_screen

    def stop(self) -> None:
        self.queued.clear()
        self.replay_bubble_id = None
        self.speech.stop()

    def switch(self, *, on: bool) -> None:
        self.auto_read = on
        if not on:
            self.queued.clear()
            self.replay_bubble_id = None

    def drain(self) -> None:
        timeout = self.session.live_settings.current.speech.timeout
        while self.queued:
            line, bubble_id = self.queued[0]
            clip = self.session.find_clip(line)
            if (
                clip is None
                and not self.session.clip_refused(line)
                and monotonic() - self.head_queued_at <= timeout
            ):
                return
            self.queued.popleft()
            self.head_queued_at = monotonic()
            if bubble_id != self.replay_bubble_id:
                if clip is not None:
                    self.speech.play(clip, bubble_id)
                continue
            self.replay_bubble_id = None
            if clip is None:
                self.speech.stop()
                warn("The voice could not read this line.")
            else:
                self.speech.replay(clip, bubble_id)
