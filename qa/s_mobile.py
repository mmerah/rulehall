"""A phone: the game page, the drawer, Enter as a newline, the other pages."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Device,
    Session,
    clean,
    composer,
    fits_width,
    move,
    placeholder,
    reach_breather,
    run,
    send,
    still,
    submit,
    take_breather,
    wait_idle,
    wait_started,
    wait_until,
    working,
)

GAME = BASE + "/game/whispering-vault/kael"
PLACEHOLDER_FITS = """() => {
  const box = document.querySelector('.game-composer textarea'), style = getComputedStyle(box);
  const pen = document.createElement('canvas').getContext('2d');
  pen.font = `${style.fontSize} ${style.fontFamily}`;
  const room = box.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  return pen.measureText(box.placeholder).width <= room;
}"""


def body(s: Session, device: Device) -> None:
    context = s.browser.new_context(**device)
    page = context.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: s.issues.append(f"pageerror: {e}"))
    page.goto(BASE + "/")
    still(page)
    s.shot(page, "home")
    s.check(fits_width(page), "home scrolls sideways")
    page.goto(GAME)
    wait_idle(page, timeout=40)
    s.shot(page, "game")
    s.check(fits_width(page), "game scrolls sideways")
    s.check(not page.locator(".game-drawer").is_visible(), "drawer open on a phone")
    phone = device["viewport"]["width"] < 600
    if phone:
        s.check(
            not page.locator(".q-header .q-badge").is_visible(), "engine badge shown on a phone"
        )
    cells = page.locator(".game-moves .game-choice").evaluate_all(
        "cells => cells.map(cell => cell.getBoundingClientRect().height)"
    )
    s.check(bool(cells) and min(cells) >= 42, f"move cells under 42px: {cells}")
    s.check(page.evaluate(PLACEHOLDER_FITS), f"the play hint is cut: {placeholder(page)!r}")
    # The explain toggle puts each move's help under its name and plays nothing.
    explain = page.locator(".game-explain")
    explain.tap()
    s.check(
        wait_until(page, lambda: "the dice decide" in move(page, "Move on").inner_text()),
        "no help line on Move on",
    )
    s.check(working(page).count() == 0, "the explain toggle played a move")
    s.check(not composer(page).is_disabled(), "the explain toggle started a turn")
    s.shot(page, "move-help")
    explain.tap()
    s.check(
        wait_until(page, lambda: "the dice decide" not in move(page, "Move on").inner_text()),
        "help line stayed",
    )
    # Enter is a newline on a touch screen; Send sends.
    composer(page).fill("one")
    started = time.monotonic()
    composer(page).press("Enter")
    s.check(
        composer(page).input_value() == "one\n", f"enter on touch: {composer(page).input_value()!r}"
    )
    s.check(not wait_started(started, timeout=1), "enter sent on a touch screen")
    composer(page).fill("I look around.")
    box = page.locator('button[aria-label="Send"]').bounding_box()
    s.check(
        box is not None and box["width"] >= 44 and box["height"] >= 44,
        f"send button too small: {box}",
    )
    submit(page, "I look around.")
    wait_idle(page)
    s.shot(page, "game-turn")
    # The drawer as an overlay with its own close button.
    page.locator('button:has(i:text("menu_book"))').click()
    page.locator(".game-drawer").wait_for()
    still(page, ".game-drawer")
    s.shot(page, "drawer")
    s.check(page.locator(".game-drawer").is_visible(), "drawer did not open")
    close = page.locator(".game-drawer button:has(i:text('close'))")
    if phone:
        s.check(close.is_visible(), "drawer close button missing on a phone")
        close.click()
    else:
        s.check(not close.is_visible(), "drawer close button shown on a tablet")
        page.locator(".q-drawer__backdrop").click(position={"x": 20, "y": 300})
    s.check(
        wait_until(page, lambda: not page.locator(".game-drawer").is_visible()),
        "drawer did not close",
    )
    sheet = page.locator(".game-sheet-button")
    s.check(sheet.get_attribute("aria-label") == "Sheet", "the drawer button is not named Sheet")
    s.check(
        sheet.get_by_text("Sheet").is_visible() != phone,
        f"the drawer button label on a {'phone' if phone else 'tablet'}",
    )
    # A conflict exchange, then the forced breather move.
    submit(page, 'I fight.\n!ask question="Do I land it?" opponent_id=mara')
    wait_idle(page)
    s.shot(page, "conflict")
    submit(page, "I break off.\n!withdraw")
    wait_idle(page)
    s.check(reach_breather(page), "no breather after eight closes")
    s.shot(page, "composer")
    s.check(
        page.locator(".game-moves button", has_text="Take the breather").is_visible(),
        "Take the breather hidden on a phone",
    )
    s.check(
        "Take the breather" in send(page).inner_text(),
        "the breather is not armed on the send",
    )
    s.check(fits_width(page), "the action bar overflows")
    take_breather(page, 'I rest.\n!direct text="He rests."')
    s.note(f"placeholder: {placeholder(page)}")
    # The restart menu.
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.locator(".q-dialog").wait_for()
    still(page, ".q-dialog")
    s.shot(page, "restart")
    page.get_by_role("button", name="Keep playing").click()
    for path, name in (
        ("/settings", "settings"),
        ("/rules/loner4e", "hall"),
        ("/rules/loner4e/character", "create"),
        ("/rules/loner4e/scenario", "scenario"),
    ):
        page.goto(BASE + path)
        still(page)
        s.shot(page, name)
        s.check(fits_width(page), f"{name} scrolls sideways")
    s.note(f"body text sample: {clean(page.inner_text('body'))[:120]}")
    context.close()


PHONE: Device = {
    "viewport": {"width": 390, "height": 664},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15",
}
TABLET: Device = {
    "viewport": {"width": 768, "height": 1024},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": "Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X) AppleWebKit/605.1.15",
}


def both(s: Session) -> None:
    body(s, PHONE)
    body(s, TABLET)


run("mobile", both)
