import pytest
from support.twentyfourxx import small_world

from rulehall.engines.twentyfourxx.world import TwentyFourXXGame, TwentyFourXXWorld


@pytest.fixture
def draft() -> TwentyFourXXGame:
    return small_world().draft()


@pytest.fixture
def world(draft: TwentyFourXXGame) -> TwentyFourXXWorld:
    return draft.world
