"""Plays a named sound in reaction to topics.SOUND events.

What this module owns: mapping a sound name to a file under a folder, and
playing it.
What it does NOT own: deciding WHEN a sound should play -- that is
client.events.GameEventSource, which derives sound names by comparing
consecutive snapshots -- or anything about the game itself.
"""

import logging
import os

_log = logging.getLogger(__name__)

_DEFAULT_NAMES = {
    "move": "move.wav",
    "capture": "capture.wav",
    "promotion": "promotion.wav",
    "game_over": "game_over.wav",
    # assets/sounds/illegal_move.wav exists but is deliberately NOT mapped
    # here: the server silently ignores an illegal command and sends no
    # rejection (common.net.GameSession.submit just drops it -- see its
    # docstring), so the client has no event to trigger this sound from.
    # This is a real gap, not an oversight. Closing it later needs a new
    # `error` message from the server plus one more entry in this dict --
    # nothing else here or in GameEventSource would change. That is the bus
    # paying off.
}


def _play_with_winsound(path):  # pragma: no cover -- needs Windows audio hardware
    # Imported locally, not at module top, so this module (and its pure
    # logic below) can be imported and tested on the non-Windows machine
    # tests run on -- the same reason view/sprite_library.py imports cv2
    # locally rather than at module scope.
    import winsound  # pylint: disable=import-outside-toplevel
    # SND_ASYNC matters twice: it does not block the draw loop, and
    # starting a new sound replaces the one still playing. The provided
    # files are ~2s long and moves happen about every 2s, so without
    # replacement they would pile up.
    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)


class SoundPlayer:  # pylint: disable=too-few-public-methods
    # A bus subscriber is meant to have exactly one public entry point --
    # the handler it is subscribed with -- so one public method is the
    # design, not a gap.
    """Subscribe on_sound to topics.SOUND.

    `play` is injected, defaulting to the real Windows player -- the same
    pattern as ClientProxy(send), GameRegistry(make_session) and
    db.connect(connector=). That is what makes this testable with no audio
    hardware, and it is why there is no monkeypatching anywhere in this
    project."""

    def __init__(self, folder, play=None, names=None):
        """folder -- directory the sound files live in (assets/sounds).
        play -- callable(path); defaults to the real Windows player.
        names -- {sound name: filename}; defaults to the four wired sounds."""
        self._folder = folder
        self._play = play if play is not None else _play_with_winsound
        self._names = names if names is not None else _DEFAULT_NAMES

    def on_sound(self, payload):
        """Play the sound named by payload["name"]. An unknown name, a
        missing file, or a payload without a "name" key is logged and
        ignored, never raised -- a missing sound must not take down the
        game."""
        name = payload.get("name")
        if name is None:
            return
        filename = self._names.get(name)
        if filename is None:
            _log.warning("no sound file mapped for %r", name)
            return
        path = os.path.join(self._folder, filename)
        if not os.path.isfile(path):
            _log.warning("sound file missing: %s", path)
            return
        self._play(path)
