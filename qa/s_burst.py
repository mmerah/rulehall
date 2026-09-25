"""Input and concurrency stress: double sends, huge text, reload storms, two tabs at once."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    bubbles,
    clean,
    composer,
    log,
    run,
    send,
    submit,
    wait_idle,
    wait_working,
)

GAME = BASE + "/game/whispering-vault/kael"


def masters() -> int:
    return len([spoken for spoken in log() if spoken["role"] == "master"])


def body(s: Session) -> None:
    page = s.page()
    page.goto(GAME)
    wait_idle(page)

    # 1. Two fast clicks on Send must buy one turn, not two.
    before = masters()
    composer(page).fill("I push the door.\n!none")
    send(page).click()
    send(page).click(force=True)
    page.wait_for_timeout(200)
    send(page).click(force=True)
    wait_idle(page, timeout=40)
    spawned = masters() - before
    s.check(spawned == 1, f"three clicks on Send spawned {spawned} master turns, not 1")
    s.shot(page, "double-send")

    # 2. Whitespace only: nothing should run.
    before = masters()
    composer(page).fill("   \n\t  \n ")
    send(page).click()
    page.wait_for_timeout(1500)
    s.check(masters() == before, "a whitespace-only send started a turn")
    s.check(not composer(page).is_disabled(), "a whitespace-only send locked the composer")

    # 3. A very long action. The prompt must still go out and the page must survive it.
    before = masters()
    huge = "I recite the whole ledger. " * 900  # ~24k characters
    composer(page).fill(huge + "\n!none")
    send(page).click()
    started = wait_working(page, timeout=8)
    s.check(started, "a 24k-character action never started a turn")
    wait_idle(page, timeout=60)
    s.check(masters() == before + 1, f"24k action spawned {masters() - before} masters")
    spoken = log()
    s.note(f"longest master prompt: {max(len(e['prompt']) for e in spoken)} chars")
    s.shot(page, "huge-action")

    # 4. Reload storm while a role is slow: three reloads inside one turn.
    submit(page, 'I wait a while.\n!slow narrator\n!drive actor_id=player goal="Hold on"')
    for index in range(3):
        page.wait_for_timeout(700)
        page.reload()
        page.wait_for_timeout(500)
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
    composer(page).fill("Tab one moves.\n!none")
    composer(other).fill("Tab two moves.\n!none")
    send(page).click()
    send(other).click(force=True)
    page.wait_for_timeout(300)
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
    submit(page, 'I stall again.\n!slow narrator\n!drive actor_id=player goal="Stall"')
    page.wait_for_timeout(600)
    page.goto(BASE + "/")
    page.wait_for_timeout(1200)
    page.go_back()
    page.wait_for_timeout(1500)
    wait_idle(page, timeout=60)
    s.check(
        "I stall again." in clean(page.inner_text("body")), "the turn was lost by navigating away"
    )
    s.shot(page, "navigate-away")

    other.close()


run("burst", body)
