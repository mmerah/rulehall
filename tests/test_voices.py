from rulehall.voices import voice_catalogue


def test_the_hd_model_shares_the_turbo_voices_under_its_own_label() -> None:
    hd = voice_catalogue().require_model("minimax/speech-2.8-hd")
    turbo = voice_catalogue().require_model("minimax/speech-2.8-turbo")
    assert hd.voice_ids() == turbo.voice_ids()
    assert hd.narrator == turbo.narrator
    assert hd.label == "MiniMax Speech 2.8 HD"
