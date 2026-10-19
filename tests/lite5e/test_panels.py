from support.lite5e import PACK, hero, sheet_proposal, world

from rulehall.core.decisions import ActionOption
from rulehall.core.views import Panel
from rulehall.engines.lite5e.panels import gear_panel, person_rows


def _option(panel: Panel | None, option_id: str) -> ActionOption:
    assert panel is not None
    return next(option for option in panel.options() if option.id == option_id)


def test_the_gear_panel_refuses_untrained_armor() -> None:
    built = world(player=hero(sheet_proposal("wizard", background_id="sage")))
    built.player.require_sheet().add_gear("leather-armor", 1)

    assert _option(gear_panel(built), "equip-player-leather-armor").refusal


def test_the_ability_detail_names_each_part_of_the_score() -> None:
    built = world(player=hero(sheet_proposal("wizard", background_id="sage")))
    sheet = built.player.require_sheet()
    backgrounds = {background.id: background for background in PACK.backgrounds}
    scores = {
        score.name: score
        for row in person_rows(built.player, backgrounds.__getitem__, built)
        for score in row.scores
    }

    for ability, increase in sheet.background_increases.items():
        score = scores[ability[:3].upper()]
        base = sheet.base_scores[ability]
        assert score.detail.startswith(f"{base + increase} = {base} base + {increase} background")
        assert score.help.startswith(score.detail)
