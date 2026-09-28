from rulehall.core.validation import slug, slugs


def test_an_accented_name_is_named_without_its_accents() -> None:
    """The shipped packs name `Naïve` `naive`, so an id made here must read the same."""
    assert slug("Naïve", ()) == "naive"


def test_slugs_avoid_the_taken_ids_and_each_other() -> None:
    assert slugs(("Rope", "Rope", "Lamp"), ("lamp",)) == ["rope", "rope-2", "lamp-2"]
