"""The Silent Relay (24XX): a hire, then a death that opens the succession decision."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import BASE, Session, cards, clean, drawer_text, open_drawer, run, submit, wait_idle

GAME = BASE + "/game/silent-relay/kael"


def body(s: Session) -> None:
    page = s.page()
    page.goto(GAME)
    wait_idle(page)

    submit(page, 'I hire Vessa.\n!join_party target_id=vessa-rune terms="Fly us out"')
    wait_idle(page, timeout=40)

    # Risking death until the d4 disaster lands: succession is an option-only decision.
    opened, attempt = False, 0
    for attempt in range(1, 9):
        submit(
            page,
            f'I cross the fire ({attempt}).\n!roll what="Cross the fire" risk="burned to death" deadly=true hindered="Bruised"',  # noqa: E501
        )
        page.wait_for_timeout(4000)
        if "Who leads now?" in clean(page.inner_text("body")):
            opened = True
            break
        wait_idle(page)
    s.note(f"succession opened after {attempt} attempt(s)")
    s.check(opened, "no succession decision after eight crossings")
    if opened:
        page.locator(".game-decision button", has_text="Vessa Rune").click()
        page.wait_for_timeout(4000)
        wait_idle(page)
        s.check("Vessa Rune leads now" in " ".join(cards(page)), f"lead card: {cards(page)[-3:]}")
        side = clean(drawer_text(page))
        sheet = side.split("SHIP")[0]  # the character card, before the panel that follows it
        s.check("Vessa Rune" in sheet, f"the new lead does not head the drawer: {side[:400]}")
    open_drawer(page)
    s.shot(page, "succession")


run("24xx", body)
