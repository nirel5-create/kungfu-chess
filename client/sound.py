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
    # nothing else here or in GameEventSource would change. That is the bus
    # paying off.
}


class _PygamePlayer:  # pragma: no cover -- needs real audio hardware, pylint: disable=too-few-public-methods
    """The real playback callable used when no `play` is injected. Callable,
    so it slots directly into SoundPlayer's injected `play` seam --
    SoundPlayer neither knows nor cares that this one, unlike a test's
    `play`, holds state.

    Replaces winsound.PlaySound, which opened and closed the OS audio
    device and re-read the file from disk on EVERY call -- Windows puts the
    device back to sleep between calls, so that open cost was paid again
    every time, producing an inconsistent delay (observed anywhere from
    immediate to ~1.5s) with no way to fix it from the calling side; a
    one-off warm-up sound could not help either, since the device just
    sleeps again after it. pygame.mixer instead opens the device ONCE, in
    __init__ below, and keeps it open; every sound named in `names` is
    decoded into memory as a pygame.mixer.Sound in that same __init__, so a
    later play() call only has to start a buffer already in RAM. Both of
    those happen once, at construction (client startup), never per call."""

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
    """Subscribe on_sound to topics.SOUND.

    `play` is injected, defaulting to the real pygame-backed player -- the
    same pattern as ClientProxy(send), GameRegistry(make_session) and
    db.connect(connector=). That is what makes this testable with no audio
    hardware, and it is why there is no monkeypatching anywhere in this
    project.

    Mute lives here, not in the draw loop and not in GameEventSource:
    muting is "stop playing sounds", not "stop deciding what the sounds
    would be" -- GameEventSource keeps publishing regardless of whether
    anyone is listening, which is what a bus is for."""

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
