"""Input and concurrency stress: double sends, huge text, reload storms, two tabs at once."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    bubbles,
    clean,
    composer,
    held,
    log,
    run,
    send,
    submit,
    wait_idle,
    wait_started,
    wait_working,
)

GAME = BASE + "/game/whispering-vault/kael"


def masters() -> int:
    return len([spoken for spoken in log() if spoken["role"] == "master"])


def body(s: Session) -> None:
    page = s.page()
    page.goto(GAME)
    wait_idle(page)

    # 1. Three clicks on Send inside one turn must buy one turn, not three.
    before = masters()
    with held("master"):
        composer(page).fill("I push the door.\n!none")
        send(page).click()
        send(page).click(force=True)
        wait_working(page)
        send(page).click(force=True)
    wait_idle(page, timeout=40)
    spawned = masters() - before
    s.check(spawned == 1, f"three clicks on Send spawned {spawned} master turns, not 1")
    s.shot(page, "double-send")

    # 2. Whitespace only: nothing should run.
    before = masters()
    composer(page).fill("   \n\t  \n ")
    started = time.monotonic()
    send(page).click()
    s.check(not wait_started(started, timeout=1), "a whitespace-only send started a turn")
    s.check(masters() == before, "a whitespace-only send spawned a master")
    s.check(not composer(page).is_disabled(), "a whitespace-only send locked the composer")

    # 3. A very long action. The prompt must still go out and the page must survive it.
    before = masters()
    huge = "I recite the whole ledger. " * 900  # ~24k characters
    s.check(submit(page, huge + "\n!none"), "a 24k-character action never started a turn")
    wait_idle(page, timeout=60)
    s.check(masters() == before + 1, f"24k action spawned {masters() - before} masters")
    spoken = log()
    s.note(f"longest master prompt: {max(len(e['prompt']) for e in spoken)} chars")
    s.shot(page, "huge-action")

    # 4. Reload storm while a role works: three reloads inside one turn.
    with held("narrator"):
        submit(page, 'I wait a while.\n!drive actor_id=player goal="Hold on"')
        wait_working(page)
        for index in range(3):
            page.reload()
            s.check(wait_working(page), f"reload {index + 1} mid-turn lost the live turn")
            s.check(
                "Internal Server Error" not in clean(page.inner_text("body")),
                f"reload {index + 1} mid-turn showed a server error",
            )
    wait_idle(page, timeout=60)
    text = clean(page.inner_text("body"))
    s.check("I wait a while." in text, "the turn was lost across three reloads")
    s.shot(page, "reload-storm")

    # 5. Two tabs send at the same moment. One turn wins; the other must be told, not crash.
    other = s.page()
    other.goto(GAME)
    wait_idle(other)
    before, lines = masters(), len(bubbles(page))
    with held("master"):
        composer(page).fill("Tab one moves.\n!none")
        composer(other).fill("Tab two moves.\n!none")
        send(page).click()
        send(other).click(force=True)
        wait_working(other)
    wait_idle(page, timeout=60)
    wait_idle(other, timeout=60)
    spawned = masters() - before
    s.note(f"two tabs at once spawned {spawned} master turns")
    s.check(spawned <= 2, f"two simultaneous sends spawned {spawned} turns")
    both = clean(page.inner_text("body"))
    s.check("Internal Server Error" not in both, "a simultaneous send showed a server error")
    s.check(len(bubbles(page)) > lines, "neither tab's action reached the transcript")
    s.shot(page, "two-tabs")
    s.shot(other, "two-tabs-other")

    # 6. Leave mid-turn, come back: the turn is still there and still lands.
    with held("narrator"):
        submit(page, 'I stall again.\n!drive actor_id=player goal="Stall"')
        wait_working(page)
        page.goto(BASE + "/")
        page.locator(".game-door").first.wait_for()
        page.go_back()
        s.check(wait_working(page), "the live turn is gone after coming back")
    wait_idle(page, timeout=60)
    s.check(
        "I stall again." in clean(page.inner_text("body")), "the turn was lost by navigating away"
    )
    s.shot(page, "navigate-away")

    other.close()


run("burst", body)
