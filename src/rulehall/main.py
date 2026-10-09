from rulehall.app.runtime import Runtime
from rulehall.screens.registry import STYLES, build_screen_factories
from rulehall.ui import app


def start() -> None:
    app.start(build_screen_factories(), STYLES)


def mount(runtime: Runtime) -> None:
    app.mount(runtime, build_screen_factories(), STYLES)
