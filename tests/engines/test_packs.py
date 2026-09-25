from pathlib import Path

import pytest
from support.table import ENGINES_BUILT, LONER3E

from rulehall.core.io import ENCODING
from rulehall.core.play import DecisionOption
from rulehall.core.validation import EngineId, Refusal, parse
from rulehall.engines.loner3e.pack import Loner3ePack
from rulehall.engines.packs import SRD_PACK, Names, Pack, PackSet, read_packs
from rulehall.engines.twentyfourxx.pack import (
    OriginProposal,
    SpecialtyProposal,
    TwentyFourXXHead,
    TwentyFourXXPack,
)

TEST_ENGINE = EngineId("test")


def _loner3e_pack(name: str) -> Loner3ePack:
    return Loner3ePack(
        name=name,
        source="",
        license="",
        concepts=(DecisionOption(id="concept", name="Concept"),),
        skills=(DecisionOption(id="skill", name="Skill"),),
        frailties=(DecisionOption(id="frailty", name="Frailty"),),
        gear=(DecisionOption(id="gear", name="Gear"),),
    )


def test_read_packs_lists_a_written_pack_alongside_the_shipped_ones(tmp_path: Path) -> None:
    shipped = ENGINES_BUILT[LONER3E].directory / "packs"
    (tmp_path / "mine.json").write_text(_loner3e_pack("Mine").model_dump_json(), encoding=ENCODING)

    packs = read_packs(LONER3E, shipped, tmp_path, Loner3ePack)

    assert "mine" in packs.written
    assert "mine" in packs.installed
    assert "mine" not in packs.shipped


def test_read_packs_skips_a_written_pack_that_shadows_a_shipped_id(tmp_path: Path) -> None:
    shipped = ENGINES_BUILT[LONER3E].directory / "packs"
    (tmp_path / "srd.json").write_text(
        _loner3e_pack("Fake SRD").model_dump_json(), encoding=ENCODING
    )

    packs = read_packs(LONER3E, shipped, tmp_path, Loner3ePack)

    assert packs.written == {}
    assert packs.installed[SRD_PACK] == packs.shipped[SRD_PACK]


def test_require_refuses_an_uninstalled_pack() -> None:
    packs = PackSet(TEST_ENGINE, {SRD_PACK: Pack(name="SRD", source="", license="")}, {})

    with pytest.raises(Refusal, match="is not installed"):
        packs.require("gone")


def test_played_reads_the_srd_once_then_the_chosen_pack() -> None:
    srd = Pack(name="SRD", source="", license="")
    second = Pack(name="Second", source="", license="")
    packs = PackSet(TEST_ENGINE, {SRD_PACK: srd, "second": second}, {})

    assert packs.played(SRD_PACK) == (srd,)
    assert packs.played("second") == (srd, second)


def test_a_twentyfourxx_head_never_gives_two_picks_the_same_id() -> None:
    head = TwentyFourXXHead(
        backdrop="A belt station and the ships that dock there.",
        names=Names(),
        specialties=(
            SpecialtyProposal(name="Face", brief="You talk the docks down.", skills=("Talk",)),
            SpecialtyProposal(name="Face", brief="You wear another name.", skills=("Bluff",)),
        ),
        origins=(OriginProposal(name="Face", brief="Known on every deck."),),
    )

    made = parse(
        TwentyFourXXPack, {"name": "Test", "source": "", "license": "", **head.pack_fields()}
    )

    made_ids = tuple(option.id for option in (*made.specialties, *made.origins))
    assert made_ids == ("face", "face-2", "face-3")
