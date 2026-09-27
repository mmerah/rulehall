from collections.abc import Iterable

from rulehall.core.views import Panel, PanelRow


def trail_panel(titles: Iterable[str]) -> Panel:
    return Panel(title="Trail", rows=tuple(PanelRow(name=title, brief="") for title in titles))
