"""Long play on every engine: many turns, reloads between them, and the saves still load.

Each turn notes the websocket traffic it cost; the `long` run plays 30 turns to show growth."""

import os
import sys
from itertools import cycle, islice
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    SocketTraffic,
    bubbles,
    clean,
    composer,
    run,
    submit,
    wait_idle,
    wait_working,
)

WORK = Path(os.environ.get("QA_WORK", "/tmp/rulehall-qa-work"))
LONG_TURNS = 30

RUNS: dict[str, tuple[str, ...]] = {
    "whispering-vault": (
        '!roll what="Listen at the door" actor_id=player question="Is anyone there?"',
        "!reveal target_id=vault-map",
        '!drive actor_id=mara goal="Finish the catalogue"',
        "!change_tags actor_id=player kind=condition gained='[\"winded\"]'",
        "!restore_luck actor_id=player",
        '!roll what="Force the lid" actor_id=player question="Does it lift?"',
        "!change_tags actor_id=player kind=condition lost='[\"winded\"]'",
        '!roll what="Read the seal" actor_id=player question="Does it name a year?"',
    ),
    "buried-keep": (
        "!move to_id=corridor",
        '!roll what="Shoulder the door" ability=brute difficulty=8',
        "!move to_id=storeroom",
        "!rest",
        '!roll what="Search the shelves" ability=erudite difficulty=10',
        "!move to_id=corridor",
        "!meanwhile dweller_id=grix dweller_to_id=corridor",
        "!move to_id=entrance",
    ),
    "silent-relay": (
        '!roll what="Slip the hatch" skill="Stealth"',
        '!gain_item name="Cutting torch"',
        '!roll what="Cut the lock" skill="Stealth"',
        '!drop_item item_id="cutting-torch"',
        '!spend amount=2 why="Docking fees"',
        "!change_hindrances gained='[\"Bruised\"]'",
        '!ask_world question="Are the relays still warm?"',
        '!roll what="Run the board" skill="Stealth"',
    ),
}


def body(s: Session) -> None:
    for scenario, scripts in RUNS.items():
        page = s.page()
        traffic = SocketTraffic(page)
        page.goto(f"{BASE}/game/{scenario}/kael")
        wait_idle(page, timeout=40)
        play(s, page, traffic, scenario, scripts, reload_after={3, 6})
        s.shot(page, f"endure-{scenario}")
        page.close()

    saves = sorted(WORK.glob("saves/*.json"))
    s.note(f"saves written: {[p.name for p in saves]}")
    s.check(len(saves) == len(RUNS), f"expected {len(RUNS)} saves, found {len(saves)}")

    # The long run shares the buried-keep save, so it restarts that game first.
    page = s.page()
    traffic = SocketTraffic(page)
    page.goto(f"{BASE}/game/buried-keep/kael")
    wait_idle(page, timeout=40)
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.get_by_role("button", name="Restart", exact=True).click()
    s.check(wait_working(page), "long: the restart did not re-open the game")
    wait_idle(page, timeout=40)
    scripts = tuple(islice(cycle(RUNS["buried-keep"]), LONG_TURNS))
    play(s, page, traffic, "long", scripts, reload_after={10, 20})
    traffic.mark()
    page.wait_for_timeout(5000)
    idle = traffic.mark()
    s.note(f"idle kb={idle.kilobytes:.1f} frames={idle.frames}")
    s.shot(page, "endure-long")
    page.close()


def play(
    s: Session,
    page: Page,
    traffic: SocketTraffic,
    name: str,
    scripts: tuple[str, ...],
    *,
    reload_after: set[int],
) -> None:
    """Each turn logs its traffic; a reload after the turns named must not lose the story.

    Marks sit only after an idle page, so frames that land late count toward the next turn.
    """
    traffic.mark()
    for turn, script in enumerate(scripts, start=1):
        submit(page, f"Turn {turn} of {name}.\n{script}")
        wait_idle(page, timeout=60)
        s.note(f"timing {name} turn={turn} {traffic.mark().line()}")
        text = clean(page.inner_text("body"))
        if not s.check(
            "Internal Server Error" not in text and "Traceback" not in text,
            f"{name} turn {turn} ({script}) broke the page",
        ):
            return
        if turn in reload_after:
            seen = len(bubbles(page))
            page.reload()
            wait_idle(page, timeout=40)
            traffic.mark()
            s.check(
                len(bubbles(page)) >= seen,
                f"{name} lost {seen - len(bubbles(page))} bubbles on a reload",
            )
    s.check(
        not composer(page).is_disabled()
        or page.locator(".game-decision").count() > 0
        or "over" in clean(page.inner_text("body")).lower(),
        f"{name} left the composer shut with no decision and no ending",
    )
    s.note(f"{name}: {len(bubbles(page))} bubbles after {len(scripts)} turns")


run("endure", body)
