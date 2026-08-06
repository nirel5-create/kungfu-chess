from collections import namedtuple

from client.panel_overlay import PanelOverlay

_History = namedtuple("_History", "white_name black_name white_score black_score log")


class _FakeLink:
    def __init__(self, history=None):
        self._history = history

    def history(self):
        return self._history


def test_reports_the_log_scores_and_names_it_was_given():
    history = _History("alice", "bob", 3, 5, ("entry1", "entry2"))
    overlay = PanelOverlay(_FakeLink(history))
    assert overlay.log() == ("entry1", "entry2")
    assert overlay.score_of("w") == 3
    assert overlay.score_of("b") == 5
    assert overlay.name_of("w") == "alice"
    assert overlay.name_of("b") == "bob"


def test_a_received_but_empty_history_yields_an_empty_log_and_zero_scores():
    history = _History("Player 1", "Player 2", 0, 0, ())
    overlay = PanelOverlay(_FakeLink(history))
    assert overlay.log() == ()
    assert overlay.score_of("w") == 0
    assert overlay.score_of("b") == 0


def test_before_any_history_arrives_log_is_empty_and_scores_are_zero_no_raise():
    overlay = PanelOverlay(_FakeLink(None))
    assert overlay.log() == ()
    assert overlay.score_of("w") == 0
    assert overlay.score_of("b") == 0
    assert overlay.name_of("w") == "Player 1"
    assert overlay.name_of("b") == "Player 2"
