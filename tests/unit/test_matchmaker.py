from common.matchmaker import MatchMaker


def test_one_seeker_alone_is_never_paired():
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    pairs, timed_out = matchmaker.advance(1000)
    assert pairs == []
    assert timed_out == []
    assert matchmaker.waiting() == ("alice",)


def test_two_seekers_within_the_window_are_paired():
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    matchmaker.enqueue("bob", 1250)
    pairs, timed_out = matchmaker.advance(1000)
    assert pairs == [("alice", "bob")]
    assert timed_out == []


def test_two_seekers_outside_the_window_are_not_paired():
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    matchmaker.enqueue("bob", 1350)  # 150 apart, default window is 100
    pairs, _timed_out = matchmaker.advance(1000)
    assert pairs == []
    assert matchmaker.waiting() == ("alice", "bob")


def test_a_paired_seeker_leaves_the_queue():
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    matchmaker.enqueue("bob", 1250)
    matchmaker.advance(1000)
    assert matchmaker.waiting() == ()


def test_with_three_seekers_the_closest_pair_is_chosen_not_the_first_two():
    # alice/bob are enqueued first (the "first two"), but carol's rating is
    # much closer to bob's -- the window exists to prefer that pairing.
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    matchmaker.enqueue("bob", 1290)     # 90 from alice
    matchmaker.enqueue("carol", 1250)   # 50 from alice, 40 from bob
    pairs, _timed_out = matchmaker.advance(1000)
    assert pairs == [("carol", "bob")]
    assert matchmaker.waiting() == ("alice",)


def test_advance_past_timeout_ms_reports_the_seeker_as_timed_out():
    matchmaker = MatchMaker(timeout_ms=60000)
    matchmaker.enqueue("alice", 1200)
    pairs, timed_out = matchmaker.advance(60000)
    assert pairs == []
    assert timed_out == ["alice"]


def test_a_timed_out_seeker_leaves_the_queue():
    matchmaker = MatchMaker(timeout_ms=60000)
    matchmaker.enqueue("alice", 1200)
    matchmaker.advance(60000)
    assert matchmaker.waiting() == ()


def test_a_seeker_just_under_the_timeout_is_neither_paired_nor_timed_out():
    matchmaker = MatchMaker(timeout_ms=60000)
    matchmaker.enqueue("alice", 1200)
    pairs, timed_out = matchmaker.advance(59999)
    assert pairs == []
    assert timed_out == []
    assert matchmaker.waiting() == ("alice",)


def test_cancel_removes_a_seeker_so_a_later_advance_reports_nothing_for_them():
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    matchmaker.cancel("alice")
    pairs, timed_out = matchmaker.advance(60000)
    assert pairs == []
    assert timed_out == []
    assert matchmaker.waiting() == ()


def test_cancel_on_an_unknown_username_does_not_raise():
    matchmaker = MatchMaker()
    matchmaker.cancel("nobody")  # must not raise


def test_enqueuing_the_same_username_twice_does_not_duplicate_them():
    matchmaker = MatchMaker()
    matchmaker.enqueue("alice", 1200)
    matchmaker.enqueue("alice", 1200)
    assert matchmaker.waiting() == ("alice",)


def test_reenqueuing_an_already_waiting_seeker_does_not_reset_their_wait_counter():
    # The reasoning enqueue's own docstring gives for the no-op: a client
    # retrying its own play() must not get an ever-fresh wait counter.
    matchmaker = MatchMaker(timeout_ms=60000)
    matchmaker.enqueue("alice", 1200)
    matchmaker.advance(59000)
    matchmaker.enqueue("alice", 1200)  # retried -- must not reset to 0
    _pairs, timed_out = matchmaker.advance(1000)
    assert timed_out == ["alice"]


def test_a_seeker_who_could_be_paired_and_has_just_timed_out_is_paired_not_timed_out():
    matchmaker = MatchMaker(timeout_ms=60000)
    matchmaker.enqueue("alice", 1200)
    matchmaker.advance(59000)  # alice has waited 59s, not yet timed out
    matchmaker.enqueue("bob", 1250)  # arrives just before alice's deadline
    pairs, timed_out = matchmaker.advance(1000)  # alice now at exactly 60000ms
    assert pairs == [("alice", "bob")]
    assert timed_out == []


def test_a_custom_window_and_timeout_ms_are_honoured():
    matchmaker = MatchMaker(window=10, timeout_ms=5000)
    matchmaker.enqueue("alice", 1200)
    matchmaker.enqueue("bob", 1215)  # 15 apart -- outside the custom window of 10
    pairs, timed_out = matchmaker.advance(5000)
    assert pairs == []
    assert timed_out == ["alice", "bob"]
