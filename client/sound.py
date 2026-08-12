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
    "jump": "jump.wav",
    # assets/sounds/illegal_move.wav exists but is deliberately NOT mapped
    # here: the server silently ignores an illegal command and sends no
    # rejection (common.net.GameSession.submit just drops it -- see its
    # docstring), so the client has no event to trigger this sound from.
    # This is a real gap, not an oversight. Closing it later needs a new
    # `error` message from the server plus one more entry in this dict --
    # nothing else here or in GameEventSource would need to change.
}


class _PygamePlayer:  # pragma: no cover -- needs real audio hardware, pylint: disable=too-few-public-methods
    """The real playback callable used when no `play` is injected. Replaces
    winsound.PlaySound, which reopened the OS audio device and re-read the
    file from disk on every call, causing an inconsistent delay (observed
    anywhere from immediate to ~1.5s); pygame.mixer decodes every sound
    into memory once in __init__, so play() only starts a buffer in RAM."""

    def __init__(self, folder, names):
        import pygame  # pylint: disable=import-outside-toplevel
        pygame.mixer.init()
        self._sounds = {}
        for filename in names.values():
            path = os.path.join(folder, filename)
            if os.path.isfile(path):
                self._sounds.setdefault(path, pygame.mixer.Sound(path))

    def __call__(self, path):
        sound = self._sounds.get(path)
        if sound is not None:
            sound.play()


class SoundPlayer:
    """Subscribe on_sound to topics.SOUND. `play` is injected, defaulting
    to the real pygame-backed player, so this is testable with no audio
    hardware. Mute lives here, not in GameEventSource: muting means "stop
    playing sounds", not "stop deciding what they'd be" -- the source
    keeps publishing regardless of whether anyone is listening."""

    def __init__(self, folder, play=None, names=None):
        """folder -- directory the sound files live in (assets/sounds).
        play -- callable(path); defaults to the real pygame-backed player.
        names -- {sound name: filename}; defaults to the five wired sounds."""
        self._folder = folder
        self._names = names if names is not None else _DEFAULT_NAMES
        self._play = play if play is not None else _PygamePlayer(folder, self._names)
        self._muted = False

    @property
    def muted(self):
        """-> whether sound is currently muted."""
        return self._muted

    def toggle_mute(self):
        """Flip muted on/off. -> the new state, so a caller (e.g. a key
        handler) can show it without a separate read."""
        self._muted = not self._muted
        return self._muted

    def on_sound(self, payload):
        """Play the sound named by payload["name"], unless muted. An
        unknown name, a missing file, or a payload without a "name" key is
        logged and ignored, never raised -- a missing sound must not take
        down the game."""
        if self._muted:
            return
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
