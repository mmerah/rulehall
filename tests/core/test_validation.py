from rulehall.core.validation import slug


def test_an_accented_name_is_named_without_its_accents() -> None:
    """The shipped packs name `Naïve` `naive`, so an id made here must read the same."""
    assert slug("Naïve", ()) == "naive"
