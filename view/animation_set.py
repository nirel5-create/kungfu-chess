"""Holds one Animation per (token, state), built from the config.json files.

This is the bridge between the raw config data and the renderer: the renderer
asks "which frame of wR/move at 1200ms?" and this answers, having already read
that state's frames_per_sec and is_loop. Configs are read once and cached.

Pure timing and JSON: no image library, so it is fully testable.
"""

from view.animation import Animation, load_state_config


class AnimationSet:
    def __init__(self, root, config_loader=None):
        """root -- the piece-assets folder.
        config_loader -- callable(root, token, state) -> dict. Defaults to
            reading config.json; a test injects a fake. Never patched."""
        self._root = root
        self._load = config_loader if config_loader is not None else load_state_config
        self._cache = {}

    def animation(self, token, state):
        """The Animation for one (token, state), built from its config once."""
        key = (token, state)
        if key not in self._cache:
            self._cache[key] = Animation.from_config(self._load(self._root, token, state))
        return self._cache[key]

    def frame(self, frames, token, state, clock_ms):
        """The frame object to draw for this (token, state) at clock_ms. Shaped
        to be handed to Renderer as its frame picker."""
        return self.animation(token, state).pick(frames, clock_ms)
