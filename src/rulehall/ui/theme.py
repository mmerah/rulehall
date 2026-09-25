from collections.abc import Mapping
from pathlib import Path

from nicegui import ui

from rulehall.core.io import read_cached_text
from rulehall.core.views import Look

NEUTRAL_PALETTE: Mapping[str, str] = {
    "game-bg": "#111519",
    "game-surface": "#1a2026",
    "game-surface-raised": "#232c33",
    "game-text": "#eeeae0",
    "game-muted": "#b0b8be",
    "game-border": "#39434b",
    "game-accent": "#dbc18b",
    "game-wash": "rgba(219, 193, 139, .07)",
    "game-success": "#85c6a3",
    "game-danger": "#f09696",
    "game-radius": "16px",
    "game-inset": ".75rem",
    "game-measure": "60rem",
    "game-body": "'Inter', 'Segoe UI', system-ui, sans-serif",
    "game-heading": "'EB Garamond', Georgia, 'Times New Roman', serif",
}
EXPAND_ICON = "sym_r_expand_more"
FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    "?family=EB+Garamond:wght@400;600;700"
    "&family=Inter:wght@400;600;700"
    '&display=swap">'
)


# iOS slides the page up under the soft keyboard instead of shrinking it, hiding the fixed header.
KEYBOARD_FIT = """<script>
(() => {
  const view = window.visualViewport;
  if (!view) return;
  const fit = () => {
    if (view.scale !== 1) return;
    document.documentElement.style.setProperty("--game-vh", view.height + "px");
    window.scrollTo(0, 0);
  };
  view.addEventListener("resize", fit);
  view.addEventListener("scroll", fit);
})();
</script>"""


def palette(look: Look | None) -> dict[str, str]:
    return {**NEUTRAL_PALETTE, **(look.palette if look is not None else {})}


def set_look(look: Look | None) -> None:
    colours = palette(look)
    ui.query("body").style("; ".join(f"--{key}: {value}" for key, value in colours.items()))
    ui.colors(
        primary=colours["game-accent"],
        secondary=colours["game-muted"],
        dark=colours["game-surface"],
        dark_page=colours["game-bg"],
        positive=colours["game-success"],
        negative=colours["game-danger"],
    )


def install() -> None:
    ui.add_head_html(FONTS, shared=True)
    ui.add_body_html(KEYBOARD_FIT, shared=True)
    ui.button.default_props("no-caps unelevated")
    ui.badge.default_props("outline")
    ui.tooltip.default_props("delay=350 transition-show=jump-up transition-hide=fade")
    ui.menu.default_props("transition-show=jump-down transition-hide=fade")
    ui.dialog.default_props("transition-show=jump-up transition-hide=fade")
    ui.expansion.default_props(f"expand-icon={EXPAND_ICON}")
    ui.input.default_props("outlined stack-label")
    ui.textarea.default_props("outlined stack-label autogrow")
    ui.select.default_props(f"outlined stack-label dropdown-icon={EXPAND_ICON}")
    ui.number.default_props("outlined stack-label")
    for field in (ui.input, ui.textarea, ui.select, ui.number, ui.switch, ui.upload):
        field.default_classes("w-full")
    ui.card.default_classes("game-card")
    # A layer before Quasar's own outranks it; `:root` keeps the first paint dark before `body`.
    root = "".join(f"--{key}: {value};" for key, value in NEUTRAL_PALETTE.items())
    css = read_cached_text(Path(__file__).parent / "theme.css")
    ui.add_css(f":root {{{root}}}@layer overrides {{{css}}}", shared=True)
