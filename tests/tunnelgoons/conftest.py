import pytest
from support.tunnelgoons import small_world

from rulehall.engines.tunnelgoons.world import TunnelGoonsGame, TunnelGoonsWorld


@pytest.fixture
def draft() -> TunnelGoonsGame:
    return small_world().draft()


@pytest.fixture
def world(draft: TunnelGoonsGame) -> TunnelGoonsWorld:
    return draft.world
