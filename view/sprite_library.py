"""Loads the sprite images that live under a piece-assets folder.

The folder layout (given, not ours) is:

    <root>/<token>/states/<state>/sprites/<n>.png

e.g. pieces_mine/wR/states/idle/sprites/1.png. Tokens are colour+type (wR, bK),
which is exactly the board's token format, so no name translation is needed.

Two responsibilities are kept apart on purpose:
  * discovery -- which files exist for a (token, state). Pure path work, so it
    is testable with no image library and no display.
  * loading   -- turning a path into an Img. This is the only part that touches
    OpenCV, and it is done lazily and cached.

The engine never sees this class; it belongs entirely to the view.
"""

import pathlib


class SpriteLibrary:
    def __init__(self, root, loader=None, cell_size=None):
        """root -- the assets folder holding one directory per piece token.
        loader -- a callable(path, size) -> image. Defaults to the real Img
                  loader; a test passes a fake so no window or file decode is
                  needed. Injected, never patched.
        cell_size -- (w, h) each sprite is resized to, or None to keep original.
        """
        self._root = pathlib.Path(root)
        self._loader = loader if loader is not None else _load_with_img
        self._cell_size = cell_size
        self._cache = {}

    def tokens(self):
        """Every piece token that has a directory, sorted for determinism."""
        return sorted(p.name for p in self._root.iterdir() if p.is_dir())

    def sprite_paths(self, token, state):
        """The sprite files for one (token, state), in numeric order (1, 2, ...,
        10) rather than the lexical order that would put 10 before 2. Empty if
        the state folder is missing."""
        folder = self._root / token / "states" / state / "sprites"
        if not folder.is_dir():
            return []
        return sorted(folder.glob("*.png"), key=_frame_number)

    def frames(self, token, state):
        """The loaded, cell-sized images for one (token, state), cached so a
        given animation is decoded once. Returns a list; empty if none exist."""
        key = (token, state)
        if key not in self._cache:
            self._cache[key] = [
                self._loader(str(path), self._cell_size)
                for path in self.sprite_paths(token, state)
            ]
        return self._cache[key]


def _frame_number(path):
    """The integer in a sprite filename ('3.png' -> 3), so frames sort by number
    and not by text. Falls back to the name if it is not a number."""
    stem = path.stem
    return int(stem) if stem.isdigit() else stem


def _load_with_img(path, size):
    """Default loader: decode a PNG (keeping transparency) into an Img.

    Why not just Img().read(path)? On Windows, OpenCV's cv2.imread fails on paths
    containing non-ASCII characters (e.g. an emoji in a folder name) even when
    the file exists -- a known OpenCV limitation. So we read the raw bytes with
    numpy.fromfile, which handles unicode paths, then decode them with
    cv2.imdecode and hand the pixels to the mentor's Img via its public buffer.
    Img itself is untouched; we only avoid its imread path. Resizing still uses
    Img so behaviour matches everywhere else.

    Imported here, not at module top, so tests that inject a fake loader never
    need OpenCV present -- the deliberate reason for the local import."""
    import cv2  # noqa: C0415 -- keep OpenCV out of test imports
    import numpy as np

    from view.img import Img

    raw = np.fromfile(str(path), dtype=np.uint8)     # unicode-safe file read
    decoded = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if decoded is None:
        raise FileNotFoundError(f"Cannot load image: {path}")

    img = Img()
    img.img = decoded
    if size is not None:
        img.img = cv2.resize(img.img, size, interpolation=cv2.INTER_AREA)
    return img
