"""Picks which sprite frame to show at a given moment.

Animation is pure arithmetic on time: given a frame count, a frames-per-second
rate and whether the animation loops, it maps a clock reading in milliseconds to
a frame index. It draws nothing and reads no files, so it is fully testable
without a display.

The two graphics fields come straight from each state's config.json:
  frames_per_sec -- how fast the sprites advance
  is_loop        -- true: cycle forever (idle, walking); false: stop on the last
                    frame (a jump, a rest -- it plays once and holds).
"""

import json
import pathlib

_DEFAULT_FPS = 6


class Animation:
    def __init__(self, frames_per_sec=_DEFAULT_FPS, is_loop=True):
        self.frames_per_sec = frames_per_sec
        self.is_loop = is_loop

    @classmethod
    def from_config(cls, config_dict):
        """Build from a parsed state config.json. Missing graphics fields fall
        back to sensible defaults rather than raising, so a sparse or partial
        config still animates."""
        graphics = config_dict.get("graphics", {})
        return cls(
            frames_per_sec=graphics.get("frames_per_sec", _DEFAULT_FPS),
            is_loop=graphics.get("is_loop", True),
        )

    def frame_index(self, frame_count, clock_ms):
        """Which frame (0-based) is showing at clock_ms, for an animation with
        `frame_count` sprites. A looping animation wraps; a non-looping one
        advances to the last frame and holds there."""
        if frame_count <= 0:
            return 0
        step = int(clock_ms * self.frames_per_sec // 1000)
        if self.is_loop:
            return step % frame_count
        return min(step, frame_count - 1)

    def pick(self, frames, clock_ms):
        """The frame object to draw right now, or None if there are none."""
        if not frames:
            return None
        return frames[self.frame_index(len(frames), clock_ms)]


def load_state_config(root, token, state):
    """Read one state's config.json, or {} if it is absent. Path work plus a
    JSON parse -- no image library involved."""
    path = pathlib.Path(root) / token / "states" / state / "config.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text())
