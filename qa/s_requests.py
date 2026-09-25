"""World-growth requests: one ends the turn, twice is refused, a failed write clears it."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    bubbles,
    cards,
    clean,
    composer,
    log,
    run,
    submit,
    wait_idle,
    wait_working,
)


def last_calls(role: str = "master") -> list[tuple[str, dict[str, object], str]]:
    spoken = [entry for entry in log() if entry["role"] == role]
    return spoken[-1]["calls"] if spoken else []


def body(s: Session) -> None:
    page = s.page()

    # 1. 24XX: a departure request, then two more calls. Both later calls get the wait line.
    page.goto(BASE + "/game/silent-relay/kael")
    wait_idle(page)
    submit(
        page,
        'I run for the docking ring.\n!next_scene pursuit="Down the docking ring"\n'
        '!roll what="Keep running" skill="Stealth"\n!change_hindrances gained=\'["Bruised"]\'',
    )
    wait_idle(page, timeout=60)
    calls = last_calls()
    s.note(f"24xx departure calls: {[(n, a[:70]) for n, _, a in calls]}")
    s.check(len(calls) == 3, f"expected 3 calls, saw {len(calls)}")
    s.check(
        all("worldsmith writes what you asked for" in answer for _, _, answer in calls[1:]),
        f"a call after the request was not waited: {[a for _, _, a in calls[1:]]}",
    )
    s.check(
        "QA Scene" in clean(page.inner_text("body")),
        "the departure never installed a new scene",
    )
    s.shot(page, "24xx-departure")

    # 2. The same request tool twice in one turn: the second must not queue a second write.
    before = len([entry for entry in log() if entry["role"] == "worldsmith"])
    submit(
        page,
        'I run again.\n!next_scene pursuit="Through the airlock"\n'
        '!next_scene pursuit="Back to the hub"',
    )
    wait_idle(page, timeout=60)
    smiths = len([entry for entry in log() if entry["role"] == "worldsmith"]) - before
    calls = last_calls()
    s.note(f"double request: {smiths} worldsmith spawns, answers {[a[:60] for _, _, a in calls]}")
    s.check(smiths == 1, f"a doubled request spawned the worldsmith {smiths} times")
    s.check(page.locator(".game-composer textarea").count() == 1, "the composer vanished")
    s.shot(page, "double-request")

    # 3. A crash after the request landed: the request must not survive into the next turn.
    before = len([entry for entry in log() if entry["role"] == "worldsmith"])
    submit(page, 'I bolt.\n!next_scene pursuit="Down the service shaft"\n!crash')
    page.wait_for_timeout(6000)
    wait_idle(page, timeout=60)
    s.note(
        f"crash after request: {len([e for e in log() if e['role'] == 'worldsmith']) - before}"
        " worldsmith spawns"
    )
    page.reload()
    wait_idle(page, timeout=40)
    text = clean(page.inner_text("body"))
    s.check("Internal Server Error" not in text, "a reload after a crashed request errored")
    s.check(not composer(page).is_disabled(), "the composer stayed shut after a crashed request")
    before = len([entry for entry in log() if entry["role"] == "worldsmith"])
    submit(page, "I look around.\n!none")
    wait_idle(page, timeout=60)
    after = len([entry for entry in log() if entry["role"] == "worldsmith"]) - before
    s.check(after == 0, f"a stale request ran the worldsmith {after} times on the next turn")
    s.shot(page, "crash-after-request")

    # 4. Loner 3e: a complication at the same place, then a call after it.
    page.goto(BASE + "/game/whispering-vault/kael")
    wait_idle(page)
    submit(
        page,
        'I hold position.\n!next_scene complication="Sirens open up"\n!reveal target_id=vault-map',
    )
    wait_idle(page, timeout=60)
    calls = last_calls()
    s.note(f"loner complication calls: {[(n, a[:70]) for n, _, a in calls]}")
    s.check(
        len(calls) > 1 and "worldsmith writes what you asked for" in calls[-1][2],
        f"the call after a complication was not waited: {[a for _, _, a in calls]}",
    )
    s.check("QA Scene" in clean(page.inner_text("body")), "the complication installed no scene")
    s.shot(page, "loner-complication")

    # 5. Tunnel Goons: walk the authored map out, unlock the last cell, then push on for more.
    page.goto(BASE + "/game/buried-keep/kael")
    wait_idle(page)
    walk = (
        "!move to_id=corridor",
        "!move to_id=storeroom",
        "!unlock_way to_id=sealed-cell",
        "!move to_id=sealed-cell",
        "!move to_id=storeroom",
        "!move to_id=corridor",
        "!move to_id=cellar",
    )
    for script in walk:
        submit(page, f"I walk on.\n{script}")
        wait_idle(page, timeout=60)
    s.check("Internal Server Error" not in clean(page.inner_text("body")), "the goons walk errored")
    s.note(f"goons trail: {clean(page.inner_text('.game-drawer'))[-200:]}")

    # The whole authored map is walked: the way on is offered, and pushing on asks the worldsmith.
    text = clean(page.inner_text("body"))
    offered = page.locator(".game-banner button", has_text="More map")
    labels = [clean(t) for t in page.locator(".game-banner button").all_inner_texts()]
    s.note(f"goons banner buttons: {labels}")
    s.check(offered.count() == 1, f"no More map button once the map ran out: {text[-400:]}")
    if offered.count() == 1:
        before = len([entry for entry in log() if entry["role"] == "worldsmith"])
        composer(page).fill("Deeper, past the rubble.")
        offered.click()
        s.check(wait_working(page), "More map never started a turn")
        wait_idle(page, timeout=60)
        smiths = len([entry for entry in log() if entry["role"] == "worldsmith"]) - before
        s.check(smiths == 1, f"pushing on spawned the worldsmith {smiths} times")
        s.check(
            page.locator(".game-banner button", has_text="More map").count() == 0,
            "the More map button stayed after the map was written",
        )
        s.check(
            "Deeper, past the rubble." in " ".join(bubbles(page)),
            f"the push-on words never reached the transcript: {bubbles(page)[-3:]}",
        )
        s.note(f"goons cards after the write: {cards(page)[-2:]}")
    s.shot(page, "goons-more-map")


run("requests", body)
