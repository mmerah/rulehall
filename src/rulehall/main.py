from rulehall.app.runtime import Runtime
from rulehall.screens.registry import SCREEN_FACTORIES, STYLES
from rulehall.ui import app


def start() -> None:
    app.start(SCREEN_FACTORIES, STYLES)


def mount(runtime: Runtime) -> None:
    app.mount(runtime, SCREEN_FACTORIES, STYLES)
