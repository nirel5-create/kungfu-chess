from client.homescreen import HOME, LOGIN, PLAYING, QUIT, HomeFlow


def test_a_fresh_flow_starts_at_login():
    flow = HomeFlow()
    assert flow.state == LOGIN
    assert flow.username is None


def test_logged_in_moves_to_home():
    flow = HomeFlow()
    flow.logged_in("alice")
    assert flow.state == HOME
    assert flow.username == "alice"


def test_login_refused_returns_to_login_keeping_no_stale_username():
    flow = HomeFlow()
    flow.logged_in("alice")  # in case a caller retries after a mid-session refusal
    flow.login_refused("bad_password")
    assert flow.state == LOGIN
    assert flow.username is None


def test_choosing_play_moves_to_playing():
    flow = HomeFlow()
    flow.logged_in("alice")
    flow.chose("play")
    assert flow.state == PLAYING


def test_game_ended_returns_to_home_not_login():
    # A player who has logged in stays logged in.
    flow = HomeFlow()
    flow.logged_in("alice")
    flow.chose("play")
    flow.game_ended()
    assert flow.state == HOME
    assert flow.username == "alice"


def test_choosing_quit_from_home_reaches_quit():
    flow = HomeFlow()
    flow.logged_in("alice")
    flow.chose(QUIT)
    assert flow.state == QUIT


def test_the_chosen_room_name_is_remembered_and_readable_while_playing():
    flow = HomeFlow()
    flow.logged_in("alice")
    flow.chose("create", "cocorico")
    assert flow.state == PLAYING
    assert flow.room_name == "cocorico"


def test_game_ended_clears_the_room_name():
    flow = HomeFlow()
    flow.logged_in("alice")
    flow.chose("create", "cocorico")
    flow.game_ended()
    assert flow.room_name == ""
