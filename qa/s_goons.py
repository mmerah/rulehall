"""The Buried Keep (Tunnel Goons): the level-up decision, answered."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    cards,
    clean,
    composer,
    drawer_text,
    open_drawer,
    run,
    send,
    start_turn,
    submit,
    wait_idle,
)

GAME = BASE + "/game/buried-keep/kael"


def body(s: Session) -> None:
    page = s.page()
    page.goto(GAME)
    wait_idle(page)

    # Level up: an option-only decision, the words box hidden, then it lands.
    submit(page, "The adventure ends here.\n!level_up")
    wait_idle(page)
    text = clean(page.inner_text("body"))
    s.check("Level up: Kael" in text, "level-up decision missing")
    s.check(
        not composer(page).is_visible() and not send(page).is_visible(),
        "the words box shows on an option-only decision",
    )
    start_turn(page.locator(".game-asking .game-moves button", has_text="Brute +1, Health +1"))
    wait_idle(page)
    s.check(
        "Level 2: Brute +1, Health +1" in " ".join(cards(page)),
        f"level card missing: {cards(page)[-3:]}",
    )
    side = clean(drawer_text(page))
    s.check("Health 11/11" in side, f"health did not rise: {side[:300]}")
    open_drawer(page)
    s.shot(page, "level-up")


run("goons", body)
