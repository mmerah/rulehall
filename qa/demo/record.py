"""Record the demo in one take against `serve.py`.

Run: uv run python qa/demo/record.py /tmp/rulehall-demo

The app runs in an iframe of `stage.html`, which draws the window, cursor, captions, zoom and
cards. Chromium's screencast saves every frame with its time; `cut.py` turns them into a video.
A slow AI turn is marked with a speed, so the cut plays it faster instead of dropping it.
"""

import base64
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Frame, Locator, Page, sync_playwright

HERE = Path(__file__).parent
BASE = "http://localhost:8190"
FAST = 7
LOAD_SPEED = 25
# Where `stage.html` puts the iframe, and its scale.
FRAME_LEFT, FRAME_TOP, FRAME_SCALE = 192, 74, 1.2
TRANSCRIPT = ".game-transcript .q-scrollarea__container"
THEMES = {
    "title": ("#6b4fd8", "#c0507a"),
    "home": ("#a8672e", "#7a3b5a"),
    "loner": ("#6b4fd8", "#b0507a"),
    "goons": ("#b0702a", "#6a2f1a"),
    "relay": ("#2f5fb0", "#1f8a9a"),
    "poke": ("#d8a800", "#3050c0"),
    "create": ("#7a4fd0", "#3a6ab0"),
}

type Target = Locator | tuple[float, float]


class Recorder:
    """Saves screencast frames with their wall time, plus speed marks and scene marks."""

    def __init__(self, page: Page, out: Path) -> None:
        self.page = page
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        for old in out.glob("*.jpg"):
            old.unlink()
        self.frames: list[tuple[float, str]] = []
        self.speeds: list[tuple[float, float]] = []
        self.marks: list[tuple[str, float]] = []
        self.stopped = False
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def start(self) -> None:
        self.speed(1)
        self.cdp.send(
            "Page.startScreencast",
            {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080},
        )

    def speed(self, factor: float) -> None:
        self.speeds.append((time.time(), factor))

    def wait(self, seconds: float) -> None:
        self.page.wait_for_timeout(int(seconds * 1000))

    def stop(self, hold: float) -> None:
        self.stopped = True
        self.wait(hold)
        self.cdp.send("Page.stopScreencast")
        self.page.wait_for_timeout(300)
        timeline = {
            "frames": self.frames,
            "speeds": self.speeds,
            "marks": self.marks,
            "end": time.time(),
        }
        (self.out / "frames.json").write_text(json.dumps(timeline))

    def _frame(self, event: dict[str, Any]) -> None:
        name = f"{len(self.frames):06d}.jpg"
        (self.out / name).write_bytes(base64.b64decode(event["data"]))
        self.frames.append((time.time(), name))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})


class Stage:
    """Drives `stage.html`: every action moves the drawn cursor before it acts."""

    def __init__(self, page: Page) -> None:
        self.page = page
        page.goto((HERE / "stage.html").as_uri())
        page.evaluate("document.fonts.ready")
        app = page.frame(name="app")
        assert app is not None
        self.app: Frame = app

    def demo(self, method: str, *args: object) -> object:
        return self.page.evaluate(f"(a) => window.demo.{method}(...a)", list(args))

    def goto(self, path: str) -> None:
        self.app.goto(BASE + path)
        self.app.wait_for_load_state("networkidle")
        self.app.evaluate("document.fonts.ready")

    def point(
        self, target: Target, dx: float = 0.5, dy: float = 0.5, *, zoomed: bool = True
    ) -> tuple[float, float]:
        """Stage coordinates of a target; `zoomed` maps them through the current zoom."""
        if isinstance(target, tuple):
            x, y = target
        else:
            left, top, width, height = target.evaluate(
                "e => { const r = e.getBoundingClientRect();"
                " return [r.x, r.y, r.width, r.height]; }",
                timeout=3000,
            )
            x = FRAME_LEFT + (left + width * dx) * FRAME_SCALE
            y = FRAME_TOP + (top + height * dy) * FRAME_SCALE
        if not zoomed:
            return x, y
        shown = self.page.evaluate("([x, y]) => window.demo.project(x, y)", [x, y])
        return shown[0], shown[1]

    def move_to(self, target: Target, ms: int = 900, dx: float = 0.5, dy: float = 0.5) -> None:
        x, y = self.point(target, dx, dy)
        self.demo("move", x, y, ms)
        self.page.mouse.move(x, y)

    def click(self, target: Target, ms: int = 900, dx: float = 0.5, dy: float = 0.5) -> None:
        self.move_to(target, ms, dx, dy)
        self.page.wait_for_timeout(110)
        self.demo("click")
        self.page.mouse.down()
        self.page.wait_for_timeout(70)
        self.page.mouse.up()

    def type(self, text: str, per_second: float = 24) -> None:
        self.page.keyboard.type(text, delay=1000 / per_second)

    def caption(
        self, step: str | None = None, text: str | None = None, sub: str | None = None
    ) -> None:
        self.demo("caption", step, text, sub)

    def zoom(self, scale: float, target: Target | None = None, dy: float = 0.5) -> None:
        x, y = (960, 540) if target is None else self.point(target, dy=dy, zoomed=False)
        self.demo("zoom", scale, x, y)


class Demo:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            args=["--font-render-hinting=none", "--force-color-profile=srgb"]
        )
        self.page = self.browser.new_page(viewport={"width": 1920, "height": 1080})
        self.page.set_default_timeout(30000)
        self.st = Stage(self.page)
        self.app = self.st.app
        self.rec = Recorder(self.page, out / "frames")
        self.has_relay = False

    def run(self) -> None:
        scenes: list[Callable[[], None]] = [
            self.title,
            self.home,
            self.loner,
            self.goons,
            self.relay,
            self.poke,
            self.create,
            self.end,
        ]
        try:
            for scene in scenes:
                self.rec.marks.append((scene.__name__, time.time()))
                scene()
        finally:
            if not self.rec.stopped:
                self.rec.stop(0.3)
            self.browser.close()
            self.playwright.stop()

    # Helpers. Every `wait` lands on the recorded timeline.
    def wait(self, seconds: float) -> None:
        self.rec.wait(seconds)

    def fast(self, factor: float) -> None:
        self.rec.speed(factor)
        self.st.demo("speed", factor, None)

    def theme(self, name: str) -> None:
        self.st.demo("theme", *THEMES[name])

    def closed_battle(self) -> bool:
        return self.app.locator(".game-transcript").is_visible()

    def idle(self, timeout: float = 300) -> None:
        """No role works and the composer takes words, or a battle waits for its button."""
        end = time.time() + timeout
        while time.time() < end:
            working = self.app.locator(".game-working:visible").count()
            box = self.app.locator(".game-composer textarea")
            disabled = box.is_disabled() if box.count() else True
            battle = self.app.get_by_role("button", name="Battle").is_visible()
            if not working and (not disabled or battle):
                return
            self.page.wait_for_timeout(200)
        raise TimeoutError("the game never went idle")

    def scene(self, path: str, theme: str, scroll_up: int = 0) -> None:
        """Go to another page under the veil; the load plays fast."""
        self.st.caption()
        self.st.demo("veil", True)
        self.theme(theme)
        self.wait(0.35)
        self.rec.speed(LOAD_SPEED)
        self.st.goto(path)
        self.st.demo("url", "localhost:8080" + path)
        if path.startswith("/game"):
            self.idle()
        self.page.wait_for_timeout(1200)
        self.app.evaluate(
            f"(up) => {{ const t = document.querySelector('{TRANSCRIPT}');"
            " if (t) t.scrollTop = t.scrollHeight - t.clientHeight - up; }",
            scroll_up,
        )
        self.page.wait_for_timeout(600)
        self.app.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        self.rec.speed(1)
        self.st.demo("veil", False)
        self.wait(0.6)

    def turn(self, text: str) -> None:
        box = self.app.locator(".game-composer textarea")
        self.st.click(box, 800, dx=0.25)
        self.st.move_to(box, 450, dx=0.62, dy=1.9)
        self.st.type(text)
        self.wait(0.4)
        self.st.click(self.app.locator('button[aria-label="Send"]'), 500)
        self.wait(1.4)
        self.fast(FAST)
        self.idle()
        self.page.wait_for_timeout(600)
        self.fast(1)

    def reveal(self, target: Locator) -> None:
        target.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'smooth'})")
        self.wait(0.9)

    # Scenes.
    def title(self) -> None:
        self.theme("title")
        self.st.demo("cursor", False)
        self.st.goto("/")
        self.page.wait_for_timeout(1000)
        self.has_relay = self.app.get_by_text("The Silent Relay").count() > 0
        self.rec.start()
        self.wait(0.4)
        self.st.demo("card", "title", True)
        self.wait(3.6)
        self.st.demo("card", "title", False)
        self.wait(0.5)
        self.theme("home")
        self.st.demo("window", True)
        self.wait(1.2)
        self.st.demo("cursor", True)

    def home(self) -> None:
        app, st = self.app, self.st
        st.caption("01", "Pick a scenario and a character")
        self.wait(1.0)
        st.click(app.get_by_label("Scenario"), 1000, dx=0.3)
        self.wait(0.8)
        st.click(app.get_by_role("option", name="The Whispering Vault"), 800, dx=0.25)
        self.wait(1.0)
        # The click is drawn only: the next scene goes to the game under the veil.
        start = app.get_by_role("button", name=re.compile("^(Start game|Resume)$")).first
        st.move_to(start, 900)
        self.page.wait_for_timeout(110)
        st.demo("click")
        self.wait(0.35)

    def loner(self) -> None:
        app, st = self.app, self.st
        self.scene("/game/whispering-vault/kael", "loner")
        st.caption("02", "Type what your character does", "in plain words")
        self.wait(1.2)
        self.turn("I raise my lantern and search the abbot's desk for anything he tried to hide.")
        st.caption("03", "Code rolls every die", "the AI proposes, the engine decides")
        die = app.locator(".game-die").last
        self.reveal(die)
        st.move_to(die, 700, dy=1.3)
        st.zoom(1.75, die)
        self.wait(3.2)
        st.zoom(1)
        self.wait(0.9)
        st.caption(
            "04",
            "The narrator writes what you see",
            "it knows only what your character has learned",
        )
        app.evaluate(
            f"() => {{ const t = document.querySelector('{TRANSCRIPT}');"
            " t.scrollTo({top: t.scrollHeight, behavior: 'smooth'}); }"
        )
        self.wait(1.0)
        st.zoom(1.4, app.locator(".game-transcript .game-message").last, dy=0.2)
        st.move_to((1500, 700), 1400)
        self.wait(4.4)
        st.zoom(1)
        self.wait(1.0)
        st.caption("05", "The journal keeps every clue and thread")
        st.click(app.locator(".q-tab").filter(has_text="Journal").last, 900)
        self.wait(0.9)
        entry = app.locator(".q-tab-panel:visible .q-expansion-item").first
        if entry.count():
            st.click(entry, 700, dx=0.3, dy=0.2)
        self.wait(2.8)

    def goons(self) -> None:
        app, st = self.app, self.st
        self.scene("/game/buried-keep/kael", "goons")
        st.caption(
            "06",
            "Four rule sets, each with its own table",
            "Tunnel Goons: a dungeon that maps itself",
        )
        self.wait(1.5)
        self.turn("I follow the scrape marks deeper into the dark, torch held low.")
        chart = app.locator(".nicegui-echart").first
        st.move_to(chart, 900)
        st.zoom(1.5, chart)
        self.wait(2.6)
        st.zoom(1)
        self.wait(0.8)

    def relay(self) -> None:
        """Shows a played 24XX save, scrolled back to a skill roll; skipped without one."""
        if not self.has_relay:
            return
        self.scene("/game/silent-relay/kael", "relay", scroll_up=1450)
        self.st.caption("07", "24XX: hard science fiction", "one skill die, gear that breaks")
        self.app.evaluate(
            f"() => document.querySelector('{TRANSCRIPT}')"
            ".scrollBy({top: -380, behavior: 'smooth'})"
        )
        self.st.move_to((1250, 420), 1200)
        self.wait(3.4)

    def poke(self) -> None:
        app, st = self.app, self.st
        self.scene("/game/tern-isles/kael", "poke")
        st.caption("08", "Pokemon: battles in the real Showdown simulator")
        self.wait(0.5)
        self.turn("I walk into the tall grass beside the road, looking for a wild Pokemon.")
        battle = app.get_by_role("button", name="Battle")
        battle.wait_for(timeout=60000)
        self.wait(0.5)
        st.click(battle, 900)
        choices = app.locator(".game-battle-choices button:enabled")
        self.rec.speed(5)
        choices.first.wait_for()
        self.page.wait_for_timeout(2500)
        self.rec.speed(1)
        self.wait(0.6)
        st.click(choices.first, 900)  # sends out the starter
        self.wait(0.6)
        st.zoom(1.25, app.locator(".game-battle").first, dy=0.35)
        self.wait(1.2)
        # Weaken, then throw; the battle may end at any step.
        thrown = False
        for move in ("Scratch", "Poké Ball", "Scratch", "Poké Ball", "Ember"):
            button = app.locator(".game-battle-choices button:enabled").filter(has_text=move)
            end = time.time() + 25
            while not button.count() and not self.closed_battle() and time.time() < end:
                self.page.wait_for_timeout(150)
            if self.closed_battle() or not button.count():
                break
            if move == "Poké Ball" and not thrown:
                st.zoom(1)
                st.caption("08", "Throw a ball and the dice decide", "catch rates, rolled in code")
                thrown = True
                self.wait(0.8)
            self.wait(1.8)
            if self.closed_battle() or not button.count():
                break
            st.click(button, 800)
        self.wait(1.2)
        st.zoom(1)
        if self.closed_battle():
            die = app.locator(".game-transcript .game-die").last
            self.reveal(die)
            st.zoom(1.5, die)
            self.wait(3.0)
            st.zoom(1)
        self.wait(1.2)

    def create(self) -> None:
        app, st = self.app, self.st
        document = self._lighthouse_pdf()
        self.scene("/scenario", "create")
        st.caption("09", "Write your own world", "or drop in an adventure as a PDF")
        self.wait(0.6)
        st.click(app.get_by_label("Title"), 900)
        st.type("The Drowned Lighthouse", 26)
        self.wait(0.4)
        uploader = app.locator(".q-uploader").first
        self.reveal(uploader)
        st.zoom(1.3, uploader, dy=0.8)
        self.wait(1.0)
        # The file comes in from outside the window, carried by the cursor.
        st.move_to((1760, 1000), 700)
        st.demo("carry", True)
        self.wait(0.3)
        st.move_to(uploader, 1300, dy=0.45)
        self.wait(0.2)
        st.demo("click")
        st.demo("carry", False)
        app.locator(".q-uploader input[type=file]").set_input_files(document)
        self.wait(2.0)
        st.zoom(1)
        st.caption("10", "The worldsmith reads it", "and writes the opening scene")
        st.move_to(app.get_by_role("button", name="Write the opening"), 1000)
        self.wait(2.6)

    def end(self) -> None:
        self.st.caption()
        self.st.demo("cursor", False)
        self.st.demo("window", False)
        self.theme("title")
        self.st.demo("card", "end", True)
        self.wait(5.5)
        self.rec.stop(0.3)

    def _lighthouse_pdf(self) -> Path:
        path = self.out / "The Drowned Lighthouse.pdf"
        printer = self.browser.new_page()
        printer.goto((HERE / "lighthouse.html").as_uri())
        printer.pdf(path=str(path), format="A5")
        printer.close()
        return path


if __name__ == "__main__":
    Demo(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rulehall-demo")).run()
