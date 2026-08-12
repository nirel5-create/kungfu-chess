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
    show_matchmaking_progress, show_no_opponent_found, show_room_refused,
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


class _Overlays:
    """The two things drawn on top of the rendered board itself, rather
    than the board or the side panel: the win/loss banner and the
    disconnect-countdown overlay. Bundled out of _GameUI's own
    constructor so it stays at 5 parameters, not 6, and exposes methods
    for both so client.play calls one thing, not two."""

    def __init__(self, banner, countdown_overlay):
        self.banner = banner
        self.countdown_overlay = countdown_overlay

    def show_result(self, winner, winner_username):  # pragma: no cover
        """Queue the end banner naming the actual outcome; see
        BannerOverlay.show_result."""
        self.banner.show_result(winner, winner_username)

    def show_reconnected(self, elapsed_ms):  # pragma: no cover
        """Queue the "Opponent reconnected" confirmation; see
        CountdownOverlay.show_reconnected."""
        self.countdown_overlay.show_reconnected(elapsed_ms)

    def draw_all(self, frame, elapsed_ms, countdown_seconds, waiting):  # pragma: no cover
        """Draw the banner then the countdown overlay onto `frame`. ->
        the banner text showing this frame, or None -- BannerOverlay.draw
        reads the identical text a second time internally, safe only
        because showing() is idempotent once already promoted this frame."""
        banner_text = self.banner.showing(elapsed_ms)
        self.banner.draw(frame, elapsed_ms)
        self.countdown_overlay.draw(frame, countdown_seconds, elapsed_ms, waiting=waiting)
        return banner_text


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
    stack. The board is a _SnapshotBoard rather than a model.Board, so
    both the click decision and everything Renderer paints always
    reflect whatever snapshot the server most recently sent."""
    board = _SnapshotBoard(link)
    proxy = net.ClientProxy(link.send)
    controller = Controller(proxy, BoardMapper(board, _CONFIG), board, _CONFIG)
    sprites = SpriteLibrary(_PIECES, cell_size=(_CONFIG.cell_size, _CONFIG.cell_size))
    animations = AnimationSet(_PIECES)
    renderer = Renderer(sprites, lambda p: Img().read(p), _BOARD_PNG,
                        animation=animations.frame)
    return controller, renderer


def _build_panel(link):  # pragma: no cover
    """-> a ScorePanel positioned below the mute button and room
    indicator, backed by PanelOverlay(link) rather than a client-side
    GameObserver: the server sends the full log/scores/names in a
    `history` message, so a client that joins mid-game shows the same
    history as one that was there from the start."""
    board_image = Img().read(_BOARD_PNG)
    _image_h, image_w = board_image.img.shape[:2]
    return ScorePanel(PanelOverlay(link), x=image_w + 20,
                       y=_PANEL_TOP + _MUTE_SLOT_H + _PANEL_LINE_H)


def _wire_bus(sound_player, banner):  # pragma: no cover
    """-> a fresh Bus with event_source/sound_player/banner subscribed to
    the topics client.play's draw loop publishes every frame -- a future
    subscriber never touches that loop. GAME_END is not wired to the
    banner: its payload never carries a winner, so run() calls
    banner.show_result once the server's own `game_over` names one."""
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
    """Compose the graphical stack for ONE game, returning the _GameUI
    client.play._play_one_game drives -- mirrors app.py's build_game(),
    but with a ClientProxy and a Bus wiring score/log/sound/banner.
    `link`/`sound_player` persist across games (built once by run());
    everything else is rebuilt fresh each game rather than audited."""
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
    room_create/room_join for Create/Join, or protocol.play() for Play
    and, defensively, for any other value ask_room could not actually
    return."""
    if action == CREATE:
        return protocol.room_create(room_name)
    if action == JOIN:
        return protocol.room_join(room_name)
    return protocol.play()


def run():  # pragma: no cover
    """Log in, then loop: show the home dialog, send its choice on the
    same connection, wait for a seat, and play one game, until Quit or
    a mid-game quit. The connection stays open across games -- reopening
    it would look like a duplicate login to the server -- so only the
    window and per-game UI stack are rebuilt each round."""
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
                # Shown in its own small window, counting down, rather
                # than leaving the player watching nothing but a
                # terminal line.
                show_matchmaking_progress(link)
                if link.error() is not None:
                    print(f"Connection refused by server: {link.error()}")
                    return
                if link.matchmaking_status() == "timeout":
                    show_no_opponent_found()
                    # PLAYING -> HOME: no game was ever started, but this
                    # returns to the home loop like a finished game does,
                    # since the server keeps this connection open for a
                    # search that found no opponent.
                    flow.game_ended()
                    continue
                # Either a real match or a reconnect to a held seat -- the
                # server already sent `assigned` either way, so the
                # ordinary wait below picks it up with no special case.
            _wait_for_assignment_or_error(link)
            if link.error() is not None:
                if link.error() in protocol.ROOM_REFUSAL_REASONS:
                    # The server kept this connection open for a bad room
                    # choice: show why, then go back to the home dialog on
                    # the same connection, the same PLAYING -> HOME shape
                    # the no-opponent-found branch above already uses.
                    show_room_refused(link.error())
                    flow.game_ended()
                    continue
                # Any other reason (e.g. already_connected) means the
                # server already closed this connection -- nothing left
                # to reuse.
                print(f"Connection refused by server: {link.error()}")
                return
            ui = build_client(link, sound_player)
            quit_outright = _play_one_game(ui, link, sound_player)
            flow.game_ended()
            if quit_outright:
                return
    finally:
        shutdown_dialogs()  # the one persistent Tk root every dialog
        # shares must be destroyed somewhere; a no-op if no dialog was
        # ever shown.
