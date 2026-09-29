import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drive import (
    BASE,
    Device,
    Session,
    fits_width,
    open_drawer,
    reach_breather,
    run,
    still,
    submit,
    take_breather,
    wait_idle,
)

GAME = BASE + "/game/whispering-vault/kael"
DESKTOP: Device = {
    "viewport": {"width": 1440, "height": 900},
    "device_scale_factor": 1,
    "is_mobile": False,
    "has_touch": False,
}
TABLET: Device = {
    "viewport": {"width": 820, "height": 1180},
    "device_scale_factor": 2,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
}
PHONE: Device = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
}
DEVICES: tuple[tuple[str, Device], ...] = (
    ("desktop", DESKTOP),
    ("tablet", TABLET),
    ("phone", PHONE),
)
PLAIN_PAGES = (
    ("/", "home"),
    ("/rules/loner4e", "hall"),
    ("/rules/loner4e/character", "create"),
    ("/rules/loner4e/scenario", "scenario"),
    ("/rules/loner4e/packs", "packs"),
    ("/settings", "settings"),
)


def body(s: Session) -> None:
    for name, device in DEVICES:
        context = s.browser.new_context(**device)
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on("pageerror", lambda e: s.issues.append(f"pageerror: {e}"))
        for path, label in PLAIN_PAGES:
            page.goto(BASE + path)
            still(page)
            s.shot(page, f"{name}-{label}")
            s.check(fits_width(page), f"{name} {label} scrolls sideways")
        page.goto(GAME)
        wait_idle(page, timeout=40)
        submit(page, "I search the desk.")
        wait_idle(page)
        still(page)
        s.shot(page, f"{name}-game")
        s.check(fits_width(page), f"{name} game scrolls sideways")
        # Two or more foes share one Fight chip, which opens a pick.
        submit(page, 'Tomas comes in.\n!enter target_id=tomas\n!direct text="He enters."')
        wait_idle(page)
        page.locator(".game-moves button.game-choice", has_text="Fight").click()
        page.locator(".game-row-dialog").wait_for()
        still(page, ".game-row-dialog")
        s.shot(page, f"{name}-fight-pick")
        page.mouse.click(8, 8)
        page.locator(".game-row-dialog").wait_for(state="hidden")
        submit(page, 'I fight.\n!ask question="Do I land it?" opponent_id=mara')
        wait_idle(page)
        still(page)
        s.shot(page, f"{name}-conflict")
        submit(page, "I break off.\n!withdraw")
        wait_idle(page)
        reach_breather(page)
        still(page, ".game-action-bar")
        s.shot(page, f"{name}-composer")
        take_breather(page, 'I rest.\n!direct text="He rests."')
        open_drawer(page)
        still(page, ".game-drawer")
        s.shot(page, f"{name}-drawer")
        context.close()


run("gallery", body)
