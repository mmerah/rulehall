from support.game import with_entity
from support.table import ENGINES_BUILT, LONER3E, game, narrowed

from rulehall.app.spawn import PROMPT_MAX_BYTES
from rulehall.core.play import Chapter, Exchange, SpokenLine
from rulehall.core.source import SOURCE_MAX_BYTES
from rulehall.engines.loner3e.engine import Loner3eEngine
from rulehall.engines.loner3e.world import Loner3eEntity, Loner3eGame

PACKS_DIR = ENGINES_BUILT[LONER3E].directory / "packs"
CAST_SIZE = 30
CHAPTER_COUNT = 40
WRITTEN_CHAPTERS = 2
EXCHANGES_PER_CHAPTER = 20
TRANSCRIPT_CHARS = 400


def test_a_heavy_game_still_fits_the_command_line() -> None:
    engine, raw_state = game(LONER3E)
    engine = narrowed(engine, Loner3eEngine)
    state = narrowed(raw_state, Loner3eGame)

    draft = state.draft()
    draft.pack_id = _heaviest_pack()
    draft.source = "x" * SOURCE_MAX_BYTES
    draft.log = _chapters()
    state = draft.commit()

    for index in range(CAST_SIZE):
        member = Loner3eEntity(id=f"cast-{index}", name=f"Member {index}", brief="", known=True)
        state = with_entity(state, member)

    engine.validate(state)
    prompt = engine.render_next(state, "…")
    assert len(prompt.text.encode()) < PROMPT_MAX_BYTES


def _heaviest_pack() -> str:
    """The worst case a pack can hand the prompt: the largest file on the shelf."""
    return max(PACKS_DIR.glob("ap*.json"), key=lambda path: path.stat().st_size).stem


def _chapters() -> list[Chapter]:
    recapped = [
        Chapter(title=f"Scene {index}", recap=f"A short recap of scene {index}.")
        for index in range(CHAPTER_COUNT - WRITTEN_CHAPTERS)
    ]
    written = [
        Chapter(title=f"Scene {index}", exchanges=_exchanges())
        for index in range(CHAPTER_COUNT - WRITTEN_CHAPTERS, CHAPTER_COUNT)
    ]
    return [*recapped, *written]


def _exchanges() -> list[Exchange]:
    line = SpokenLine(text="x" * TRANSCRIPT_CHARS)
    return [Exchange(words="", lines=(line,)) for _ in range(EXCHANGES_PER_CHAPTER)]
