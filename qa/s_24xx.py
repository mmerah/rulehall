"""The Silent Relay (24XX): a hire, the commit and defence pauses, succession, the raise and a
newcomer after a lone death."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Session,
    cards,
    clean,
    drawer_text,
    open_drawer,
    run,
    start_turn,
    submit,
    wait_idle,
)
from playwright.sync_api import Page

GAME = BASE + "/game/silent-relay/kael"
DECISION = ".game-asking"
CROSSING = '!roll what="Cross the fire" risk="burned to death" deadly=true hindered="Bruised"'


def body(s: Session) -> None:
    page = s.page()
    page.goto(GAME)
    wait_idle(page)
    s.check(
        page.locator(".game-moves button", has_text="Move on").is_visible(),
        "Move on is not on the page",
    )
    submit(page, "The beacon is lit already.\n!job verb=finish")
    wait_idle(page)
    s.check("Which skill" not in decision_text(page), "a job finished with no roll played")

    submit(page, 'I hire Vessa.\n!join_party target_id=vessa-rune terms="Fly us out"')
    wait_idle(page, timeout=40)

    submit(page, f"I cross the fire.\n{CROSSING}")
    wait_idle(page)
    prompt = decision_text(page)
    s.note(f"commit prompt: {prompt}")
    s.check("d4" in prompt and "burned to death (deadly)" in prompt, f"stakes: {prompt}")
    s.check("Cannot succeed without help." in prompt, f"no warning on a d4: {prompt}")
    s.shot(page, "commit")

    # A hindered d4 lands a disaster or a deadly setback: each pauses for gear, then lands.
    opened, defended, attempt = False, False, 0
    for attempt in range(1, 9):
        if attempt > 1:
            submit(page, f"I cross the fire again ({attempt}).\n{CROSSING}")
            wait_idle(page)
        choose(page, "Commit")
        if "Break an item" in decision_text(page):
            if not defended:
                s.shot(page, "defence")
                defended = True
            choose(page, "Take it")
        if "Who leads now?" in decision_text(page):
            opened = True
            break
    s.note(f"succession opened after {attempt} attempt(s)")
    s.check(defended, "no defence pause after a landing hit")
    s.check(opened, "no succession decision after eight crossings")
    if opened:
        choose(page, "Vessa Rune")
        s.check("Vessa Rune leads now" in " ".join(cards(page)), f"lead card: {cards(page)[-3:]}")
        s.check(
            any("To the hold" in card for card in cards(page)),
            f"the dead lead's gear did not reach the hold: {cards(page)[-3:]}",
        )
        side = clean(drawer_text(page))
        sheet = side.split("SHIP")[0]  # the character card, before the panel that follows it
        s.check("Vessa Rune" in sheet, f"the new lead does not head the drawer: {side[:400]}")
    open_drawer(page)
    s.shot(page, "succession")

    submit(page, "The run is done.\n!job verb=finish")
    wait_idle(page)
    s.check("Which skill do you raise?" in decision_text(page), "no raise decision after a job")
    s.shot(page, "raise")
    choose(page, "")
    s.check(any("Job done" in card for card in cards(page)), f"no raise card: {cards(page)[-3:]}")
    submit(page, 'We take the work.\n!job verb=find where="Relay"\n!job verb=take terms="Fix it"')
    wait_idle(page)

    submit(page, "The hull gives way.\n!kill target_id=player")
    wait_idle(page)
    s.check("Who joins the crew?" in decision_text(page), "no newcomer decision on a lone death")
    s.shot(page, "newcomer")
    submit(page, 'A pilot called Juno signs on.\n!bring_in who="Juno, a pilot"')
    wait_idle(page, timeout=60)
    s.check(
        any("leads now" in card for card in cards(page)),
        f"the newcomer does not lead: {cards(page)[-3:]}",
    )

    submit(page, 'I hire the dock hand.\n!join_party target_id=dock-hand terms="Carry the crates"')
    wait_idle(page, timeout=40)
    s.check(
        any("Dock Hand signs on" in card for card in cards(page)),
        f"a stranger was not hired: {cards(page)[-3:]}",
    )
    submit(page, "You're off the crew.\n!leave_party target_id=dock-hand")
    wait_idle(page)
    s.check(
        any("Dock Hand leaves the crew" in card for card in cards(page)),
        f"the master could not let a hired member go: {cards(page)[-3:]}",
    )


def decision_text(page: Page) -> str:
    banner = page.locator(DECISION)
    return clean(banner.first.inner_text()) if banner.count() else ""


def choose(page: Page, name: str) -> None:
    start_turn(page.locator(f"{DECISION} .game-moves button", has_text=name).first)
    wait_idle(page)


run("24xx", body)
