from rulehall.core.decisions import ActionOption, Decision
from rulehall.core.validation import Frozen, Slug
from rulehall.core.views import Meter, Panel, PanelRow, PanelRows, Tag
from rulehall.engines.panels import described_tag, tag_list, text_rows
from rulehall.engines.pokemon.champions.args import PresetEdit, TeamEdit
from rulehall.engines.pokemon.champions.data import CompetitiveSet, champions_data
from rulehall.engines.pokemon.champions.rules import TEAM_SLOT_PREFIX, require_archetype
from rulehall.engines.pokemon.champions.season import TIERS, Event, Finish, TierRule
from rulehall.engines.pokemon.champions.sheet import ChampionsSheet, ChampionsTrainer
from rulehall.engines.pokemon.champions.world import ChampionsWorld
from rulehall.engines.pokemon.dex import dex, species_name
from rulehall.engines.pokemon.rules import STAT_NAMES
from rulehall.engines.pokemon.sprites import (
    STAT_COLOUR,
    ability_tag,
    move_tag,
    nature_arrows,
    nature_tag,
    type_tag,
)
from rulehall.engines.sheet import PLAYER_ID

TEAM_TAB = "Team"
UNSAVED = "Unsaved changes in the team builder"
UNSAVED_BRIEF = "Save them there before you register the team."
UNSAVED_REGISTERED_BRIEF = "Save them there once the event ends."
SHEET_HELP = {
    "Team": "The six Pokemon this trainer brings to an event; each match picks four of them.",
    "Tier": "The event tiers open to this trainer.",
    "CP": "Championship Points: the best four finishes of each tier count.",
    "Registered": "A registered team is locked from registration until the event ends.",
}
TRAINER_HELP = {
    "Rival": "The player's rival: code builds their team for every event.",
    "Archetype": "The kind of team this trainer brings.",
    "Ace": "The Pokemon this trainer leans on.",
    "Style": "How this trainer battles.",
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
PRACTICE_HELP = (
    "Play a practice match against an archetype you pick, with your saved team. It counts for "
    "nothing at the event."
)
NEXT_EVENT = ActionOption(
    id="next-event",
    name="Go to the next event",
    help="Travel on: the next host city and its event appear.",
    action_name="extend",
    args={"words": "I set out for the next event"},
    told_in_turn=True,
)
PLAY_NEXT_ROUND = ActionOption(
    id="play-next-round",
    name="Play next round",
    help="Sit down for your next match of the event.",
    action_name="start_match",
)


def person_rows(trainer: ChampionsTrainer) -> PanelRows:
    sheet = trainer.sheet
    if sheet is None:
        archetype_id = trainer.archetype_id
        ace_id = trainer.ace_species_id
        return (
            *text_rows(
                "Rival", TRAINER_HELP["Rival"], "the rival of the season" if trainer.rival else ""
            ),
            *text_rows(
                "Archetype",
                TRAINER_HELP["Archetype"],
                "" if archetype_id is None else require_archetype(archetype_id).name,
            ),
            *text_rows("Ace", TRAINER_HELP["Ace"], "" if ace_id is None else species_name(ace_id)),
            *text_rows("Style", TRAINER_HELP["Style"], trainer.style),
        )
    team = [Tag(name=species_name(each.species_id), help=_set_line(each)) for each in sheet.team]
    tiers = [
        Tag(name=TIERS[tier].name, help=_tier_line(TIERS[tier])) for tier in sheet.unlocked_tiers()
    ]
    registered = "yes: the team is locked" if sheet.registered else "no"
    return (
        *tag_list("Team", SHEET_HELP["Team"], team),
        *(
            tag_list("Tier", SHEET_HELP["Tier"], tiers)
            or (PanelRow(name="Tier", brief="none", help=SHEET_HELP["Tier"]),)
        ),
        PanelRow(name="CP", brief=str(sheet.cp()), help=SHEET_HELP["CP"]),
        PanelRow(name="Registered", brief=registered, help=SHEET_HELP["Registered"]),
    )


def team_panel(world: ChampionsWorld) -> Panel:
    registered = world.player_sheet.registered is not None
    brief = UNSAVED_REGISTERED_BRIEF if registered else UNSAVED_BRIEF
    unsaved = (PanelRow(name=UNSAVED, brief=brief),) if world.unsaved_team_dirty() else ()
    return Panel(
        title="Team",
        rows=(
            *(
                competitive_set_row(each, number)
                for number, each in enumerate(world.player_sheet.team, 1)
            ),
            *unsaved,
        ),
        help=SHEET_HELP["Team"]
        + (" Registered: locked until the event ends." if world.player_sheet.registered else ""),
        tab=TEAM_TAB,
    )


def competitive_set_row(competitive_set: CompetitiveSet, number: int) -> PanelRow:
    pokedex = dex()
    species = pokedex.require_species(competitive_set.species_id)
    arrows = nature_arrows(competitive_set.nature)
    sp_max = champions_data().legal.sp_max
    return PanelRow(
        name=species.name,
        brief="",
        icon_id=f"{TEAM_SLOT_PREFIX}{number}",
        tags=(
            *(type_tag(kind) for kind in species.types),
            described_tag(
                pokedex.item_name(competitive_set.item_id),
                pokedex.item_text(competitive_set.item_id),
            ),
            ability_tag(pokedex.ability_names[competitive_set.ability_id]),
            nature_tag(competitive_set.nature),
        ),
        lower_tags=tuple(move_tag(pokedex.moves[move_id]) for move_id in competitive_set.move_ids),
        meters=tuple(
            Meter(
                name=f"SP {STAT_NAMES[index]}{arrows.get(index, '')}",
                current=points,
                maximum=sp_max,
                colour=STAT_COLOUR,
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
        tab=TEAM_TAB,
    )


def practice_panel(world: ChampionsWorld) -> Panel:
    refusal = world.practice_refusal()
    return Panel(
        title="Practice",
        rows=tuple(
            PanelRow(
                name=archetype.name,
                brief=", ".join(species_name(each.species_id) for each in archetype.team.sets),
                options=(
                    ActionOption(
                        id=f"practice-{archetype.archetype_id}",
                        name="Practice",
                        action_name="practice_match",
                        args={"archetype_id": archetype.archetype_id},
                        refusal=refusal,
                    ),
                ),
            )
            for archetype in champions_data().archetypes
        ),
        help=PRACTICE_HELP,
        tab=TEAM_TAB,
    )


def prize_decision(sheet: ChampionsSheet) -> Decision | None:
    if not sheet.prize_species_ids:
        return None
    return Decision(
        kind="prize",
        prompt="A prize for the top cut: which Pokemon joins your roster?",
        options=tuple(
            ActionOption(
                id=species_id,
                name=dex().species[species_id].name,
                action_name="claim_prize",
                args={"species_id": species_id},
            )
            for species_id in sheet.prize_species_ids
        ),
        allows_text=False,
    )


def team_option(
    edit: TeamEdit, args: Frozen | None = None, *, name: str = "", option_id: str = ""
) -> ActionOption:
    return ActionOption(
        id=option_id or edit.replace("_", "-"),
        name=name or edit.replace("_", " ").capitalize(),
        action_name=edit,
        args={} if args is None else args.model_dump(mode="json"),
    )


def preset_option(slot: int, preset_id: Slug, name: str) -> ActionOption:
    return team_option(
        "apply_preset",
        PresetEdit(slot=slot, preset_id=preset_id),
        name=name,
        option_id=f"apply-preset-{slot}-{preset_id}",
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


def _set_line(competitive_set: CompetitiveSet) -> str:
    pokedex = dex()
    moves = ", ".join(pokedex.moves[move_id].name for move_id in competitive_set.move_ids)
    item = pokedex.item_name(competitive_set.item_id)
    return f"{item} · {pokedex.ability_names[competitive_set.ability_id]} · {moves}"


def _tier_line(rule: TierRule) -> str:
    earns = f" First place earns {rule.placing_cp(1)} CP." if rule.cp else ""
    return f"{rule.swiss_rounds} Swiss rounds, then a top {rule.cut_size} cut.{earns}"
