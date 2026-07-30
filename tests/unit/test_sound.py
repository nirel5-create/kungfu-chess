import os

from client.sound import _DEFAULT_NAMES, SoundPlayer


def test_a_known_name_calls_play_with_the_matching_file_path(tmp_path):
    (tmp_path / "move.wav").write_bytes(b"")
    calls = []
    player = SoundPlayer(str(tmp_path), play=calls.append, names={"move": "move.wav"})
    player.on_sound({"name": "move"})
    assert calls == [os.path.join(str(tmp_path), "move.wav")]


def test_an_unknown_name_does_not_call_play_and_does_not_raise(tmp_path):
    calls = []
    player = SoundPlayer(str(tmp_path), play=calls.append, names={"move": "move.wav"})
    player.on_sound({"name": "nonexistent"})
    assert calls == []


def test_a_missing_file_does_not_call_play_and_does_not_raise(tmp_path):
    calls = []
    player = SoundPlayer(str(tmp_path), play=calls.append, names={"move": "move.wav"})
    player.on_sound({"name": "move"})  # move.wav was never created
    assert calls == []


def test_on_sound_reads_the_name_out_of_the_payload_dict(tmp_path):
    (tmp_path / "capture.wav").write_bytes(b"")
    calls = []
    player = SoundPlayer(str(tmp_path), play=calls.append, names={"capture": "capture.wav"})
    player.on_sound({"name": "capture", "extra": "ignored"})
    assert calls == [os.path.join(str(tmp_path), "capture.wav")]


def test_a_payload_with_no_name_key_does_not_raise(tmp_path):
    calls = []
    player = SoundPlayer(str(tmp_path), play=calls.append)
    player.on_sound({})
    assert calls == []


def test_illegal_move_is_deliberately_not_in_the_default_names_mapping():
    # The server never rejects an illegal command, so the client has no
    # event to trigger this sound from -- see client/sound.py's comment.
    assert "illegal_move" not in _DEFAULT_NAMES
