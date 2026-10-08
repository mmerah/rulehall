from rulehall.core.views import Meter, Panel, PanelRow, Tag
from rulehall.engines.pokemon.champions.data import CompetitiveSet, champions_data
from rulehall.engines.pokemon.champions.rules import TEAM_SLOT_PREFIX
from rulehall.engines.pokemon.champions.season import TIERS, Event, Finish
from rulehall.engines.pokemon.champions.world import ChampionsWorld
from rulehall.engines.pokemon.dex import dex
from rulehall.engines.pokemon.rules import STAT_NAMES
from rulehall.engines.pokemon.sprites import nature_arrows, nature_tag, type_tag
from rulehall.engines.sheet import PLAYER_ID

SP_COLOUR = "#6890f0"
SHEET_HELP = {
    "Team": "The six Pokemon this trainer brings to an event; each match picks four of them.",
    "Tier": "The event tiers open to this trainer.",
    "CP": "Championship Points: the best four finishes of each tier count.",
    "Registered": "A registered team is locked from registration until the event ends.",
}
SEASON_HELP = {
    "Tier": "The tier of this event.",
    "CP": "Championship Points so far: the best four finishes of each tier count.",
    "Next unlock": "The CP the next tier needs.",
    "Event": "The event this map hosts.",
    "Stage": "Registration, the Swiss rounds, the top cut, or over.",
    "Round": "The round of the Swiss or of the cut.",
    "Record": "The player's wins and losses in the Swiss rounds.",
    "Placing": "The player's placing at the last event played, and the CP it earned.",
}
STAGE_NAMES = {"open": "registration", "swiss": "Swiss rounds", "cut": "top cut", "done": "over"}


def team_panel(world: ChampionsWorld) -> Panel:
    return Panel(
        title="Team",
        rows=tuple(
            competitive_set_row(each, number)
            for number, each in enumerate(world.player_sheet.team, 1)
        ),
        help=SHEET_HELP["Team"]
        + (" Registered: locked until the event ends." if world.player_sheet.registered else ""),
        tab="Team",
    )


def competitive_set_row(competitive_set: CompetitiveSet, number: int) -> PanelRow:
    pokedex = dex()
    species = pokedex.require_species(competitive_set.species_id)
    arrows = nature_arrows(competitive_set.nature)
    sp_max = champions_data().legal.sp_max
    return PanelRow(
        name=species.name,
        brief=" · ".join(pokedex.moves[move_id].name for move_id in competitive_set.move_ids),
        icon_id=f"{TEAM_SLOT_PREFIX}{number}",
        tags=(
            *(type_tag(kind) for kind in species.types),
            Tag(name=pokedex.item_name(competitive_set.item_id)),
            Tag(name=pokedex.ability_names[competitive_set.ability_id]),
            nature_tag(competitive_set.nature),
        ),
        meters=tuple(
            Meter(
                name=f"SP {STAT_NAMES[index]}{arrows.get(index, '')}",
                current=points,
                maximum=sp_max,
                colour=SP_COLOUR,
                help="Stat Points spent on this stat.",
            )
            for index, points in enumerate(competitive_set.sp)
        ),
    )


def season_panel(world: ChampionsWorld) -> Panel:
    sheet = world.player_sheet
    cp = sheet.cp()
    upcoming = [rule.unlock_cp for rule in TIERS.values() if rule.unlock_cp > cp]
    event = world.event
    shown = (
        ("CP", str(cp)),
        ("Next unlock", f"{upcoming[0]} CP" if upcoming else "every tier is open"),
        *(() if event is None else _event_rows(event)),
        *(_placing_rows(sheet.finishes[-1]) if sheet.finishes else ()),
    )
    rows = tuple(PanelRow(name=name, brief=brief, help=SEASON_HELP[name]) for name, brief in shown)
    standings = () if event is None or event.stage == "open" else _standing_rows(event)
    return Panel(
        title="Season",
        rows=(*rows, *standings),
        help="The circuit season: events, placings and Championship Points.",
        tab="Team",
    )


def _event_rows(event: Event) -> tuple[tuple[str, str], ...]:
    player = next((each for each in event.entrants if each.entrant_id == PLAYER_ID), None)
    return (
        ("Event", event.name),
        ("Tier", TIERS[event.tier].name),
        ("Stage", STAGE_NAMES[event.stage]),
        *((("Round", str(event.round)),) if event.stage in ("swiss", "cut") else ()),
        *(() if player is None else (("Record", f"{player.wins}-{player.losses}"),)),
    )


def _placing_rows(finish: Finish) -> tuple[tuple[str, str]]:
    return (
        ("Placing", f"{finish.placing} at {finish.event_name} ({finish.record}), +{finish.cp} CP"),
    )


def _standing_rows(event: Event) -> tuple[PanelRow, ...]:
    return tuple(
        PanelRow(name=f"{rank}. {each.name}", brief=f"{each.wins}-{each.losses}")
        for rank, each in event.shown_standings()
    )
