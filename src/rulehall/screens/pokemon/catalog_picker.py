from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from nicegui import ui
from nicegui.events import GenericEventArguments

from rulehall.core.validation import Frozen, Slug, parse
from rulehall.core.views import Sprite
from rulehall.engines.pokemon.champions.views import Catalog, Choice
from rulehall.ui.widgets import media_url

type FindSprite = Callable[[Sprite], Sprite | None]
type PickChoice = Callable[[Slug], Awaitable[object]]


class Picked(Frozen):
    choice_id: Slug


class CatalogPickerView(ui.element, component="catalog_picker.js"):
    pass


class CatalogPicker:
    def __init__(self, find_sprite: FindSprite) -> None:
        self.find_sprite = find_sprite
        self.sheets: dict[Path, Path | None] = {}
        self.on_pick: PickChoice | None = None
        with (
            ui.dialog() as self.dialog,
            ui.card().classes("game-picker-card game-gap-0"),
        ):
            self.view = CatalogPickerView()
        self.view.on("pick", self.picked)
        self.view.on("close", self.dialog.close)

    @property
    def open(self) -> bool:
        return bool(self.dialog.value)

    def show(
        self,
        catalog: Catalog,
        on_pick: PickChoice,
        *,
        picked: Sequence[Slug] = (),
        pinned: Sequence[Choice] = (),
        pinned_title: str = "Suggested",
    ) -> None:
        self.on_pick = on_pick
        self.view.props.update(
            {
                "title": catalog.title,
                "choices": [self.choice_props(choice) for choice in catalog.choices],
                "facets": list(catalog.facets),
                "orders": [
                    {"name": order.name, "ids": list(order.choice_ids)} for order in catalog.orders
                ],
                "columns": catalog.columns,
                "picked": list(picked),
                "pinned": [self.choice_props(choice) for choice in pinned],
                "pinned-title": pinned_title,
            }
        )
        self.view.update()
        self.dialog.open()

    def choice_props(self, choice: Choice) -> dict[str, object]:
        return {
            "id": choice.choice_id,
            "name": choice.name,
            "brief": choice.brief,
            "help": choice.help,
            "sprites": [props for sprite in choice.sprites if (props := self.sprite_props(sprite))],
            "tags": [{"name": tag.name, "colour": tag.colour} for tag in choice.tags],
            "badge": choice.badge,
            "group": choice.group,
            "refusal": choice.refusal,
            "search": f"{choice.name} {choice.search_text}".lower(),
            "facets": [[facet.name, facet.value] for facet in choice.facets],
        }

    def sprite_props(self, sprite: Sprite) -> dict[str, object] | None:
        if sprite.path not in self.sheets:
            found = self.find_sprite(sprite)
            self.sheets[sprite.path] = None if found is None else found.path
        if (path := self.sheets[sprite.path]) is None:
            return None
        return {
            "url": media_url(path),
            "x": sprite.x,
            "y": sprite.y,
            "width": sprite.width,
            "height": sprite.height,
        }

    async def picked(self, event: GenericEventArguments) -> None:
        choice_id = parse(Picked, event.args).choice_id
        self.dialog.close()
        if self.on_pick is not None:
            await self.on_pick(choice_id)
