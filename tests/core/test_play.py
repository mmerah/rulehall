import pytest

from rulehall.core.play import Debrief
from rulehall.core.validation import Refusal


def test_a_debrief_with_a_blank_field_is_refused() -> None:
    debrief = Debrief(
        story_so_far="You reached the vault.",
        current_aim=" ",
        open_threads=("You could open the door.",),
        last_beats=("You lit a torch.", ""),
    )

    with pytest.raises(Refusal, match="current_aim, last_beats"):
        debrief.check()
