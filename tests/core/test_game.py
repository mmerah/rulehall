from support.table import TWENTYFOURXX, game

from rulehall.core.game import MASTER_NOTES_KEPT


def test_the_master_keeps_only_its_latest_notes() -> None:
    _, begun = game(TWENTYFOURXX)
    draft = begun.draft()

    for number in range(MASTER_NOTES_KEPT + 1):
        draft.remember(f"note {number}")

    assert len(draft.master_notes) == MASTER_NOTES_KEPT
    assert draft.master_notes[0] == "note 1"
    assert draft.master_notes[-1] == f"note {MASTER_NOTES_KEPT}"
