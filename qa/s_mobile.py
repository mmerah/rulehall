"""A phone: the game page, the drawer, Enter as a newline, the other pages."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Device,
    Session,
    clean,
    composer,
    placeholder,
    submit,
    wait_idle,
    working,
)

GAME = BASE + "/game/whispering-vault/kael"


def body(s: Session, device: Device) -> None:
    context = s.browser.new_context(**device)
    page = context.new_page()
    page.set_default_timeout(15000)
    page.on("pageerror", lambda e: s.issues.append(f"pageerror: {e}"))
    page.goto(BASE + "/")
    page.wait_for_timeout(1000)
    s.shot(page, "home")
    s.check(
        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
        "home scrolls sideways",
    )
    page.goto(GAME)
    wait_idle(page, timeout=40)
    s.shot(page, "game")
    s.check(
        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
        "game scrolls sideways",
    )
    s.check(not page.locator(".game-drawer").is_visible(), "drawer open on a phone")
    phone = device["viewport"]["width"] < 600
    if phone:
        s.check(
            not page.locator(".q-header .q-badge").is_visible(), "engine badge shown on a phone"
        )
    # Enter is a newline on a touch screen; Send sends.
    composer(page).fill("one")
    composer(page).press("Enter")
    page.wait_for_timeout(300)
    s.check(
        composer(page).input_value() == "one\n", f"enter on touch: {composer(page).input_value()!r}"
    )
    s.check(
        working(page).count() == 0,
        "enter sent on a touch screen",
    )
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
    page.wait_for_timeout(600)
    s.shot(page, "drawer")
    s.check(page.locator(".game-drawer").is_visible(), "drawer did not open")
    close = page.locator(".game-drawer button:has(i:text('close'))")
    if phone:
        s.check(close.is_visible(), "drawer close button missing on a phone")
        close.click()
    else:
        s.check(not close.is_visible(), "drawer close button shown on a tablet")
        page.locator(".q-drawer__backdrop").click(position={"x": 20, "y": 300})
    page.wait_for_timeout(600)
    s.check(not page.locator(".game-drawer").is_visible(), "drawer did not close")
    # A conflict decision and the way-on banner on a narrow footer.
    submit(page, 'I fight.\n!roll what="Strike" actor_id=player question="Land it?" target_id=mara')
    wait_idle(page)
    s.shot(page, "decision")
    submit(page, "I break off.\n!none")
    wait_idle(page)
    submit(page, "Done here.\n!next_scene")
    wait_idle(page)
    s.shot(page, "way-on")
    s.check(
        page.locator(".game-banner button", has_text="Move on").is_visible(),
        "Move on hidden on a phone",
    )
    s.check(
        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
        "way-on banner overflows",
    )
    s.note(f"placeholder: {placeholder(page)}")
    # The restart menu.
    page.locator(".q-header button").last.click()
    page.get_by_text("Restart this game").click()
    page.wait_for_timeout(500)
    s.shot(page, "restart")
    page.get_by_role("button", name="Keep playing").click()
    for path, name in (("/settings", "settings"), ("/create", "create"), ("/scenario", "scenario")):
        page.goto(BASE + path)
        page.wait_for_timeout(1000)
        s.shot(page, name)
        s.check(
            page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
            f"{name} scrolls sideways",
        )
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


def main() -> None:
    from drive import run

    def both(s: Session) -> None:
        body(s, PHONE)
        body(s, TABLET)

    run("mobile", both)


main()
