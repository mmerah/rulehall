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
# Chromium shows no soft keyboard: a stand-in visual viewport that `setKeyboard` covers and pans.
FAKE_KEYBOARD = """(() => {
  const view = new EventTarget();
  let covered = 0, pan = 0;
  const fit = () => {
    Object.assign(view, {
      scale: 1, offsetTop: pan, offsetLeft: 0,
      width: window.innerWidth, height: window.innerHeight - covered,
    });
    view.dispatchEvent(new Event("resize"));
    view.dispatchEvent(new Event("scroll"));
  };
  window.setKeyboard = (keyboard, offset) => {
    covered = keyboard;
    pan = offset;
    fit();
  };
  window.addEventListener("resize", fit);
  Object.defineProperty(window, "visualViewport", { value: view, configurable: true });
  fit();
})()"""
TRANSCRIPT_GAP = """() => {
  const box = document.querySelector('.game-transcript .q-scrollarea__container');
  return box.scrollHeight - box.scrollTop - box.clientHeight;
}"""
VIEW_HEIGHT = "() => document.documentElement.style.getPropertyValue('--game-vh')"
SHELL = """() => {
  const shell = document.querySelector('.q-layout').getBoundingClientRect();
  const field = document.querySelector('.game-composer').getBoundingClientRect();
  return {top: shell.top, height: shell.height, composer: field.bottom,
          inner: window.innerHeight, scrollY: window.scrollY};
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


def keyboard(s: Session) -> None:
    context = s.browser.new_context(**{**PHONE, "viewport": {"width": 390, "height": 844}})
    context.add_init_script(FAKE_KEYBOARD)
    page = context.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: s.issues.append(f"pageerror: {e}"))
    page.goto(GAME)
    wait_idle(page, timeout=40)
    for words in ("I look around.", "I listen.", "I wait."):
        submit(page, words)
        wait_idle(page)
    jump = page.locator(".game-jump")

    def gap() -> float:
        return page.evaluate(TRANSCRIPT_GAP)

    s.check(wait_until(page, lambda: gap() <= 1), f"not at the end before the keyboard: {gap()}")
    page.evaluate("setKeyboard(300, 300)")
    s.check(wait_until(page, lambda: gap() <= 1), f"the keyboard hid the last message: {gap()}")
    shell = page.evaluate(SHELL)
    s.check(abs(shell["top"] - 300) <= 1, f"the shell is not at the visible offset: {shell}")
    s.check(
        abs(shell["height"] - (shell["inner"] - 300)) <= 1,
        f"the shell is not the visible height: {shell}",
    )
    s.check(shell["composer"] <= shell["inner"], f"the composer is under the keyboard: {shell}")
    s.check(shell["scrollY"] == 0, f"the page scrolled under the keyboard: {shell}")
    s.check(
        wait_until(page, lambda: not jump.is_visible()),
        "the jump button shows with the keyboard open",
    )
    s.shot(page, "keyboard-open")
    page.evaluate("setKeyboard(0, 0)")
    s.check(wait_until(page, lambda: gap() <= 1), f"closing the keyboard left the end: {gap()}")
    page.locator(".game-transcript").hover()
    page.mouse.wheel(0, -400)
    s.check(wait_until(page, lambda: gap() >= 300), f"the transcript did not scroll up: {gap()}")
    page.evaluate("setKeyboard(300, 300)")
    s.check(
        not wait_until(page, lambda: gap() <= 1, timeout=1),
        "the keyboard pinned a reader who scrolled up",
    )
    s.check(wait_until(page, jump.is_visible), "no jump button after scrolling up")
    page.evaluate("setKeyboard(0, 0)")
    jump.click()
    s.check(wait_until(page, lambda: gap() <= 1), f"the jump did not reach the end: {gap()}")
    context.close()


def resized(s: Session) -> None:
    context = s.browser.new_context(**{**PHONE, "viewport": {"width": 390, "height": 844}})
    page = context.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: s.issues.append(f"pageerror: {e}"))
    page.goto(GAME)
    wait_idle(page, timeout=40)
    for words in ("I look around.", "I listen.", "I wait."):
        submit(page, words)
        wait_idle(page)
    s.check(
        wait_until(page, lambda: page.evaluate(TRANSCRIPT_GAP) <= 1),
        "not at the end before the resize",
    )
    page.set_viewport_size({"width": 390, "height": 364})
    # The shell resizes one event after the call returns.
    s.check(
        wait_until(page, lambda: page.evaluate(VIEW_HEIGHT) == "364px"),
        "the shell did not follow the resize",
    )
    s.check(
        wait_until(page, lambda: page.evaluate(TRANSCRIPT_GAP) <= 1),
        f"a resized window left the end: {page.evaluate(TRANSCRIPT_GAP)}",
    )
    s.shot(page, "keyboard-resized")
    context.close()


def both(s: Session) -> None:
    body(s, PHONE)
    body(s, TABLET)
    keyboard(s)
    resized(s)


run("mobile", both)
