"""The composition root: build_client wires one game's graphical stack
together, and run() drives the whole client -- login once, then loop
showing the home dialog and playing games on the same connection until the
player quits.
"""

import logging

from client.board import _SnapshotBoard
from client.draw import _MUTE_SLOT_H, _PANEL_LINE_H, _PANEL_TOP
from client.events import GameEventSource
from client.homescreen import QUIT
from client.login import _login, _wait_for_assignment_or_error
from client.overlay import BannerOverlay, CountdownOverlay
from client.panel_overlay import PanelOverlay
from client.play import _play_one_game
from client.roomdialog import (
    CREATE, JOIN, PLAY, ask_room, shutdown as shutdown_dialogs,
    show_matchmaking_progress, show_no_opponent_found,
)
from client.sound import SoundPlayer
from common import net, protocol, topics
from common.bus import Bus
from input.board_mapper import BoardMapper
from input.controller import Controller
from model.config import Config
from view.animation_set import AnimationSet
from view.img import Img
from view.renderer import Renderer
from view.score_panel import ScorePanel
from view.sprite_library import SpriteLibrary

_ASSETS = "assets"
_PIECES = _ASSETS + "/pieces_mine"
_BOARD_PNG = _ASSETS + "/board.png"
_SOUNDS = _ASSETS + "/sounds"

_log = logging.getLogger(__name__)

# Matches server.session's Config exactly, so the pixel positions inside
# every snapshot line up with the sprites drawn from this same
# crystal-board asset.
_CONFIG = Config(cell_size=98, board_offset=(13, 15))


class _Overlays:  # pylint: disable=too-few-public-methods
    """The two things drawn on top of the rendered board itself, rather
    than the board or the side panel: the win/loss banner and the
    disconnect-countdown overlay. Bundled out of _GameUI's own
    constructor so it stays at 5 parameters, not 6 -- pylint's own
    threshold, not an arbitrary one."""

    def __init__(self, banner, countdown_overlay):
        self.banner = banner
        self.countdown_overlay = countdown_overlay


class _GameUI:  # pylint: disable=too-few-public-methods
    """Everything build_client wires for ONE game, bundled so
    client.play._play_one_game takes one object instead of six separate
    parameters."""

    def __init__(self, controller, renderer, bus, overlays, panel):
        self.controller = controller
        self.renderer = renderer
        self.bus = bus
        self.overlays = overlays
        self.panel = panel


def _build_controller_and_renderer(link):  # pragma: no cover
    """-> (controller, renderer): the input/render half of one game's
    stack. The board behind both is a _SnapshotBoard, never a
    model.Board -- see its own module docstring for why -- so a click
    decision and everything Renderer paints both always reflect whatever
    snapshot the server most recently sent."""
    board = _SnapshotBoard(link)
    proxy = net.ClientProxy(link.send)
    controller = Controller(proxy, BoardMapper(board, _CONFIG), board, _CONFIG)
    sprites = SpriteLibrary(_PIECES, cell_size=(_CONFIG.cell_size, _CONFIG.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)
    return controller, renderer


def _build_panel(link):  # pragma: no cover
    """-> a ScorePanel positioned in the side panel strip: the mute
    button's own _MUTE_SLOT_H below _PANEL_TOP, then one ordinary
    _PANEL_LINE_H for the room indicator (see client.play's draw loop),
    so ScorePanel's own content starts right after both instead of
    overlapping them (room used to be drawn on top of ScorePanel's first
    line -- a bug found by testing Step 7).

    Reads from PanelOverlay(link), not a real GameObserver: the server
    runs its own GameObserver per game and sends the current log/scores/
    names in a `history` message, so every client shows the same
    history -- including one that joined mid-game, which a client-side
    GameObserver (computing its own log from only what it happened to
    see) could never do."""
    board_image = Img().read(_BOARD_PNG)
    _image_h, image_w = board_image.img.shape[:2]
    return ScorePanel(PanelOverlay(link), x=image_w + 20,
                       y=_PANEL_TOP + _MUTE_SLOT_H + _PANEL_LINE_H)


def _wire_bus(sound_player, banner):  # pragma: no cover
    """-> a fresh Bus with event_source/sound_player/banner subscribed to
    the topics client.play's draw loop publishes to every frame. Adding a
    future subscriber never touches that loop -- that is the whole point
    of routing these through a bus instead of direct calls.

    Deliberately NOT bus.subscribe(topics.GAME_END, banner.on_game_end):
    GameEventSource's own GAME_END payload is always {} (see its module
    docstring -- it only ever sees snapshots, never who won), which is
    all on_game_end can show ("GAME OVER", left as-is for whatever else
    might still want that plain trigger). The server's own `game_over`
    message names the actual winner by username, so run()'s loop calls
    banner.show_result directly once that message has actually arrived
    -- see run() for why it waits rather than reading link.result() from
    inside a bus callback."""
    bus = Bus()
    # promotions is passed explicitly, the same way server.composition
    # passes king_type=CONFIG.king_type to GameRegistry instead of relying
    # on its default -- one source of truth (_CONFIG) instead of two
    # declarations of the same fact.
    event_source = GameEventSource(bus, promotions=_CONFIG.promotions)
    bus.subscribe(topics.SNAPSHOT, event_source.on_snapshot)
    bus.subscribe(topics.SOUND, sound_player.on_sound)
    bus.subscribe(topics.GAME_START, banner.on_game_start)
    return bus


def build_client(link, sound_player):  # pragma: no cover
    # This is the composition root: the one place that wires every
    # collaborator together, mirroring app.py's build_game() -- split
    # into _build_controller_and_renderer/_build_panel/_wire_bus by
    # subject, each returning the piece(s) it built rather than writing
    # into shared locals, which is what let this function's own local
    # count drop back under the ordinary threshold.
    """Compose the graphical stack for ONE game and return the _GameUI
    client.play._play_one_game drives. Mirrors app.py's build_game(),
    except the engine is a ClientProxy, the board is a _SnapshotBoard
    instead of a model.Board, there is a ServerLink instead of a
    GameClock, and score/log/sound/banner are wired through one Bus
    instead of being called directly.

    `link` and `sound_player` are built ONCE by run(), not here: both must
    survive from game to game on the same connection -- link because
    reopening one per game would look like a duplicate login to the
    server's own check, sound_player because muting should stay muted
    across games, not reset back to on. Everything bundled into the
    returned _GameUI (controller, renderer, bus, overlays, panel) is
    rebuilt fresh every game instead: simpler than auditing each one for
    cross-game state (e.g. Controller.selection potentially showing a
    stale highlight) at negligible cost, since none of them owns anything
    that needs to outlive one game."""
    controller, renderer = _build_controller_and_renderer(link)
    panel = _build_panel(link)
    # Not wired to the bus like _wire_bus's own three subscribers: its
    # number comes straight from link.countdown() every frame in
    # client.play's own draw loop (see CountdownOverlay's own docstring
    # for why it has no state machine of its own to feed via a
    # subscriber), not from anything the server-driven SNAPSHOT/GAME_END
    # topics carry.
    banner = BannerOverlay()
    countdown_overlay = CountdownOverlay()
    bus = _wire_bus(sound_player, banner)
    return _GameUI(controller, renderer, bus, _Overlays(banner, countdown_overlay), panel)


def _room_message_from_dialog(action, room_name):  # pragma: no cover
    """-> the protocol message to send for the Room dialog's outcome:
    room_create/room_join for Create/Join, or protocol.play() -- slide
    5's own message, sent explicitly rather than left implicit -- for
    Play, and, defensively, for any other value ask_room could not
    actually return."""
    if action == CREATE:
        return protocol.room_create(room_name)
    if action == JOIN:
        return protocol.room_join(room_name)
    return protocol.play()


def run():  # pragma: no cover
    """Log in (retrying on a refusal instead of exiting the process), then
    loop: show the home dialog (ask_room, the project's Home screen -- the
    logged-in username and rating, and Create/Join/Play/Quit), send its
    outcome on the SAME connection _login already opened, wait for a seat,
    play one game (client.play._play_one_game), and go back to the home
    dialog once it ends naturally -- until Quit is chosen or a game ends
    by the player quitting outright instead.

    Never closes and reopens the connection between games: see
    client.link's own module docstring for why that would look like a
    duplicate login to the server's own check. Only the OpenCV window
    itself (_play_one_game) and the per-game UI stack (build_client) are
    rebuilt fresh each round; `link` and `sound_player` persist across
    the whole loop.

    A room refusal ("room_exists", "no_such_room") ends the program
    outright rather than returning to the home dialog: the server closes
    the connection itself in those cases (see server.connection.
    _seat_for_choice), so there is no connection left to reuse for
    another attempt -- the same terminal ending this client always had
    for these refusals. A Play search finding no opponent is different:
    the server keeps this same connection open for it (see
    _seat_for_choice's own docstring), so this returns to the home dialog
    exactly as a finished game does, instead of ending the program.

    Every return path goes through a `finally` that calls roomdialog.
    shutdown() exactly once -- the one persistent Tk root every dialog in
    that module shares (see its own docstring) must be destroyed
    somewhere, and this is the one place that sees every way run() can
    end. A no-op if no dialog was ever shown (e.g. _login() itself quit
    first, before ask_room ever ran)."""
    _log.info("client starting")
    try:
        flow, link = _login()
        if link is None:
            return
        sound_player = SoundPlayer(_SOUNDS)
        while flow.state != QUIT:
            dialog_action, room_name = ask_room(username=flow.username, rating=link.rating())
            flow.chose(dialog_action, room_name)
            if flow.state == QUIT:
                break
            link.reset_for_new_round()
            link.send(_room_message_from_dialog(dialog_action, room_name))
            if dialog_action == PLAY:
                show_matchmaking_progress(link)  # live-testing fix: the
                #   search is shown, counting down, in its own small
                #   window instead of leaving the player watching nothing
                #   but a terminal line -- see its own docstring.
                if link.error() is not None:
                    print(f"Connection refused by server: {link.error()}")
                    return
                if link.matchmaking_status() == "timeout":
                    show_no_opponent_found()
                    flow.game_ended()  # PLAYING -> HOME: a search that
                    #   found no opponent ended without ever starting a
                    #   game, but the home loop it returns to is the same
                    #   one either way (live-testing fix: this used to
                    #   `return`, ending the whole client on a failed
                    #   search; see server.connection._seat_for_choice for
                    #   the matching server-side change that keeps this
                    #   same connection open for it).
                    continue
                # Either "found" (a real match) or a direct reconnect to
                # a held seat (no "found" ever sent) -- the server
                # already sent `assigned` either way, see
                # show_matchmaking_progress's own docstring, so falling
                # through into the ordinary wait below picks it up with
                # no special case of its own.
            _wait_for_assignment_or_error(link)
            if link.error() is not None:
                print(f"Connection refused by server: {link.error()}")
                return
            ui = build_client(link, sound_player)
            quit_outright = _play_one_game(ui, link, sound_player)
            flow.game_ended()
            if quit_outright:
                return
    finally:
        shutdown_dialogs()
