import sys
from pathlib import Path

from playwright.sync_api import Page

sys.path.insert(0, str(Path(__file__).parent))
from drive import BASE, Device, Session, open_drawer, run, submit, wait_idle

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
    ("/create", "create"),
    ("/scenario", "scenario"),
    ("/packs", "packs"),
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
            page.wait_for_timeout(900)
            s.shot(page, f"{name}-{label}")
            _no_sideways(s, page, f"{name} {label}")
        page.goto(GAME)
        wait_idle(page, timeout=40)
        submit(page, "I search the desk.")
        wait_idle(page)
        page.wait_for_timeout(2600)
        s.shot(page, f"{name}-game")
        _no_sideways(s, page, f"{name} game")
        submit(
            page, 'I fight.\n!roll what="Strike" actor_id=player question="Land it?" target_id=mara'
        )
        wait_idle(page)
        page.wait_for_timeout(2600)
        s.shot(page, f"{name}-decision")
        submit(page, "I break off.\n!none")
        wait_idle(page)
        submit(page, "Done here.\n!next_scene")
        wait_idle(page)
        page.wait_for_timeout(600)
        s.shot(page, f"{name}-way-on")
        open_drawer(page)
        page.wait_for_timeout(500)
        s.shot(page, f"{name}-drawer")
        context.close()


def _no_sideways(s: Session, page: Page, where: str) -> None:
    s.check(
        page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
        f"{where} scrolls sideways",
    )


run("gallery", body)
