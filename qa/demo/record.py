"""Record the demo in one take against `serve.py`.

Run: uv run python qa/demo/record.py /tmp/rulehall-demo

The app runs in an iframe of `stage.html`, which draws the window, cursor, captions, zoom, slams
and the end card. Chromium's screencast saves every frame with its time; `cut.py` turns them into
a video. A slow AI turn is marked with a speed, so the cut plays it faster instead of dropping it,
and a badge on the frame says so. A page load under a slam plays faster too.
"""

import base64
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Frame, Locator, Page, sync_playwright

HERE = Path(__file__).parent
BASE = "http://localhost:8190"
# How many times faster an AI turn plays; the worldsmith writes a whole opening.
FAST = 20
WORLDSMITH_SPEED = 90
LOAD_SPEED = 60
# Where `stage.html` puts the iframe, and its scale.
FRAME_LEFT, FRAME_TOP, FRAME_SCALE = 192, 74, 1.2
TRANSCRIPT = ".game-transcript .q-scrollarea__container"
THEMES = {
    "title": ("#6b4fd8", "#c0507a"),
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

    def caption(self, text: str | None = None, sub: str | None = None) -> None:
        """A word that starts with `*` takes the accent colour."""
        self.demo("caption", text, sub)

    def zoom(
        self, scale: float, target: Target | None = None, dy: float = 0.5, ms: int = 850
    ) -> None:
        x, y = (960, 540) if target is None else self.point(target, dy=dy, zoomed=False)
        self.demo("zoom", scale, x, y, ms)


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

    def run(self) -> None:
        scenes: list[Callable[[], None]] = [
            self.hook,
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
        self.st.demo("speed", factor)

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

    def load(self, path: str) -> None:
        """Go to a page while the slam covers the window; the load plays fast."""
        self.rec.speed(LOAD_SPEED)
        self.st.goto(path)
        self.st.demo("url", "localhost:8080" + path)
        if path.startswith("/game"):
            self.idle()
        self.page.wait_for_timeout(1000)
        self.scroll_to_end()
        self.page.wait_for_timeout(500)
        self.app.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        self.rec.speed(1)

    def slam(self, word: str, kicker: str, theme: str, path: str) -> None:
        """A full-screen word, the next page loading under it, then a punch back in."""
        self.st.caption()
        self.st.zoom(1, ms=350)
        self.theme(theme)
        self.st.demo("window", "blur")
        self.st.demo("slam", True, word, kicker)
        self.wait(0.75)
        self.load(path)
        self.st.zoom(1.1, ms=0)
        self.st.demo("window", "on")
        self.st.demo("slam", False)
        self.st.zoom(1, ms=600)
        self.wait(0.35)

    def scroll_to_end(self) -> None:
        self.app.evaluate(
            f"() => {{ const t = document.querySelector('{TRANSCRIPT}');"
            " if (t) t.scrollTop = t.scrollHeight; }"
        )

    def turn(self, text: str) -> None:
        box = self.app.locator(".game-composer textarea")
        self.st.zoom(1.7, box, ms=600)
        self.page.wait_for_timeout(650)  # the click lands only once the zoom stops
        self.st.click(box, 350, dx=0.2)
        box.focus()
        self.st.type(text, 38)
        self.st.click(self.app.locator('button[aria-label="Send"]'), 350)
        self.wait(0.25)
        self.st.zoom(1, ms=600)
        self.wait(0.3)
        self.wait_for_roles()
        commit = self.app.get_by_role("button", name="Commit")
        if commit.is_visible():
            self.st.caption("See the odds. Then *commit.", "every die, shown before it rolls")
            self.st.zoom(1.5, commit, dy=-1.2, ms=600)
            self.wait(1.6)
            self.st.click(commit, 450)
            self.wait(0.2)
            self.st.zoom(1, ms=500)
            self.wait_for_roles()

    def wait_for_roles(self) -> None:
        self.fast(FAST)
        self.idle()
        self.page.wait_for_timeout(600)
        self.scroll_to_end()
        self.page.wait_for_timeout(500)
        self.fast(1)

    def show(self, target: Locator, scale: float, hold: float, dy: float = 0.5) -> None:
        """Scroll a part of the page into view and zoom on it."""
        target.evaluate("e => e.scrollIntoView({block: 'center'})")
        self.st.demo("unscroll")
        self.page.wait_for_timeout(150)
        self.st.move_to(target, 500, dy=dy + 0.9)
        self.st.zoom(scale, target, dy=dy)
        self.wait(hold)

    def last_die(self) -> Locator | None:
        die = self.app.locator(".game-transcript .game-die").last
        return die if die.count() and die.is_visible() else None

    # Scenes.
    def hook(self) -> None:
        self.theme("title")
        self.st.demo("cursor", False)
        self.st.goto("/game/whispering-vault/kael")
        self.idle()
        self.page.wait_for_timeout(1000)
        self.scroll_to_end()
        self.st.demo("url", "localhost:8080/game/whispering-vault/kael")
        self.rec.start()
        self.wait(0.2)
        for word, kicker in (
            ("You write<br>the hero.", "SOLO TABLETOP RPG"),
            ("AI runs<br>the table.", "GAME MASTER · NARRATOR · WORLDSMITH"),
            ("Code rolls<br>the dice.", "NO FUDGED ROLLS"),
        ):
            self.st.demo("slam", True, word, kicker)
            self.wait(0.95)
        self.st.demo("slam", False)
        self.st.demo("window", "on")
        self.wait(0.7)
        self.st.demo("cursor", True)

    def loner(self) -> None:
        app, st = self.app, self.st
        st.caption("Type *anything.", "Loner 4e · a gothic mystery")
        self.turn("I search the abbot's desk for what he tried to hide.")
        if die := self.last_die():
            st.caption("The engine rolls. *For real.", "The AI proposes. Code decides.")
            self.show(die, 2.1, 1.7)
        message = app.locator(".game-transcript .game-message").last
        st.caption("The narrator *tells the story.", "It only knows what you have found.")
        self.show(message, 1.5, 1.9, dy=0.3)

    def goons(self) -> None:
        st = self.st
        self.slam("Dungeon<br>crawl.", "TUNNEL GOONS", "goons", "/game/buried-keep/kael")
        st.caption("Walk into the *dark.")
        self.turn("I follow the scrape marks deeper into the dark.")
        st.caption("The map *grows as you explore.")
        self.show(self.app.locator(".nicegui-echart").first, 1.8, 1.7)

    def relay(self) -> None:
        st = self.st
        self.slam("Hard<br>sci-fi.", "24XX", "relay", "/game/silent-relay/kael")
        st.caption("Four *rule sets. One table.")
        self.turn("I cut the ring's power and slip through the airlock.")
        if die := self.last_die():
            st.caption("One skill die. *Everything rides on it.")
            self.show(die, 2.1, 1.6)

    def poke(self) -> None:
        app, st = self.app, self.st
        self.slam("Pokémon.", "A WHOLE REGION", "poke", "/game/tern-isles/kael")
        st.caption("Catch them *all.", "d20 checks, gyms and battles")
        self.turn("I walk into the tall grass to find a wild Pokemon.")
        battle = app.get_by_role("button", name="Battle")
        self.fast(FAST)
        battle.wait_for(timeout=60000)
        self.fast(1)
        st.click(battle, 600)
        st.caption("Real *Showdown battles.", "Pick a move. The simulator plays it.")
        choices = app.locator(".game-battle-choices button:enabled")
        self.fast(FAST)
        choices.first.wait_for(timeout=60000)
        self.page.wait_for_timeout(1500)
        self.fast(1)
        st.zoom(1.35, app.locator(".game-battle").first, dy=0.3, ms=600)
        st.click(choices.first, 600)  # sends out the starter
        # Weaken, then throw; the battle may end at any step.
        thrown = False
        for move in ("Scratch", "Poké Ball", "Scratch", "Poké Ball", "Poké Ball"):
            button = app.locator(".game-battle-choices button:enabled").filter(has_text=move)
            self.fast(FAST)
            end = time.time() + 40
            while not button.count() and not self.closed_battle() and time.time() < end:
                self.page.wait_for_timeout(150)
            self.page.wait_for_timeout(1500)
            self.fast(1)
            if self.closed_battle() or not button.count():
                break
            if move == "Poké Ball" and not thrown:
                st.caption("Throw a ball. The *dice decide.")
                thrown = True
            self.wait(0.5)
            st.click(button, 550)
        self.fast(FAST)
        end = time.time() + 40
        while not self.closed_battle() and time.time() < end:
            self.page.wait_for_timeout(200)
        self.page.wait_for_timeout(800)
        self.scroll_to_end()
        self.fast(1)
        st.zoom(1, ms=500)
        if self.closed_battle() and (die := self.last_die()):
            self.show(die, 1.9, 1.6)

    def create(self) -> None:
        app, st = self.app, self.st
        document = self._lighthouse_pdf()
        self.slam("Your<br>world.", "BRING ANY ADVENTURE", "create", "/rules/loner4e/scenario")
        app.get_by_label("Backdrop").fill("A storm coast of fishing towns and old lighthouses.")
        app.get_by_label("Scope").fill("One night. It ends when the lamp goes dark.")
        st.caption("Drop in *any adventure.", "a PDF, a text, or one idea")
        title = app.get_by_label("Title")
        st.click(title, 500)
        title.focus()
        st.type("The Drowned Lighthouse", 40)
        uploader = app.locator(".q-uploader").first
        uploader.evaluate("e => e.scrollIntoView({block: 'center'})")
        self.st.demo("unscroll")
        st.zoom(1.4, uploader, dy=0.8, ms=600)
        # The file comes in from outside the window, carried by the cursor.
        st.move_to((1760, 1000), 400)
        st.demo("carry", True)
        st.move_to(uploader, 900, dy=0.45)
        st.demo("click")
        st.demo("carry", False)
        app.locator(".q-uploader input[type=file]").set_input_files(document)
        self.wait(1.0)
        st.zoom(1, ms=500)
        st.caption("The worldsmith *builds it.", "and writes the opening scene")
        st.click(app.get_by_role("button", name="Write the opening"), 600)
        self.wait(0.4)
        self.fast(WORLDSMITH_SPEED)
        app.wait_for_url("**/game/**", timeout=600000)
        app.wait_for_load_state("networkidle")
        self.idle(600)
        self.page.wait_for_timeout(2500)
        self.fast(1)
        st.caption("Then *play it.")
        header = app.locator(".game-scene").first
        if header.count():
            st.zoom(1.35, header, ms=900)
        self.wait(2.0)

    def end(self) -> None:
        self.st.caption()
        self.st.demo("cursor", False)
        self.st.zoom(1, ms=400)
        self.st.demo("window", "blur")
        self.theme("title")
        self.st.demo("flash")
        self.st.demo("card", "end", True)
        self.wait(4.2)
        self.rec.stop(0.2)

    def _lighthouse_pdf(self) -> Path:
        path = self.out / "The Drowned Lighthouse.pdf"
        printer = self.browser.new_page()
        printer.goto((HERE / "lighthouse.html").as_uri())
        printer.pdf(path=str(path), format="A5")
        printer.close()
        return path


if __name__ == "__main__":
    Demo(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rulehall-demo")).run()
