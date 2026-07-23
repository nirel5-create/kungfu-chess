import pathlib
import unittest

from view.sprite_library import SpriteLibrary, _frame_number, _load_with_img

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets" / "pieces_mine"


class RecordingLoader:
    """A stand-in for the Img loader: records what it was asked to load instead
    of decoding anything. Handed in through the constructor -- nothing patched."""

    def __init__(self):
        self.calls = []

    def __call__(self, path, size):
        self.calls.append((path, size))
        return ("sprite", path, size)


class TestSpriteDiscovery(unittest.TestCase):
    """Discovery is pure path work, so it runs with no image library."""

    def setUp(self):
        self.lib = SpriteLibrary(ASSETS, loader=RecordingLoader())

    def test_tokens_lists_every_piece_folder(self):
        tokens = self.lib.tokens()
        self.assertIn("wR", tokens)
        self.assertIn("bK", tokens)
        self.assertEqual(len(tokens), 12)                 # 6 types x 2 colours

    def test_tokens_use_the_boards_colour_plus_type_format(self):
        # Every token is a colour letter (w/b) followed by a type letter.
        for token in self.lib.tokens():
            self.assertEqual(len(token), 2)
            self.assertIn(token[0], ("w", "b"))

    def test_sprite_paths_are_returned_in_numeric_order(self):
        paths = self.lib.sprite_paths("wR", "idle")
        self.assertTrue(paths)
        numbers = [_frame_number(p) for p in paths]
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(numbers[0], 1)                   # first frame is 1, not 10

    def test_every_state_folder_exists_for_every_piece(self):
        for token in self.lib.tokens():
            for state in ("idle", "move", "jump", "short_rest", "long_rest"):
                with self.subTest(token=token, state=state):
                    self.assertTrue(self.lib.sprite_paths(token, state),
                                    f"{token}/{state} has no sprites")

    def test_a_missing_state_gives_an_empty_list_not_an_error(self):
        self.assertEqual(self.lib.sprite_paths("wR", "no_such_state"), [])


class TestSpriteLoading(unittest.TestCase):
    """Loading uses the injected loader, so we can assert what it decodes and
    that it happens once."""

    def test_frames_calls_the_loader_once_per_sprite(self):
        loader = RecordingLoader()
        lib = SpriteLibrary(ASSETS, loader=loader, cell_size=(100, 100))
        frames = lib.frames("wR", "idle")
        self.assertEqual(len(frames), len(loader.calls))
        for _, size in loader.calls:
            self.assertEqual(size, (100, 100))            # each resized to a cell

    def test_frames_are_cached_so_a_second_call_decodes_nothing_new(self):
        loader = RecordingLoader()
        lib = SpriteLibrary(ASSETS, loader=loader)
        lib.frames("wR", "idle")
        first = len(loader.calls)
        lib.frames("wR", "idle")                          # same animation again
        self.assertEqual(len(loader.calls), first)        # no new decode


class TestFrameNumber(unittest.TestCase):
    def test_numeric_names_sort_as_numbers(self):
        self.assertEqual(_frame_number(pathlib.Path("10.png")), 10)
        self.assertEqual(_frame_number(pathlib.Path("2.png")), 2)


if __name__ == "__main__":
    unittest.main()


class TestRealLoaderIntegration(unittest.TestCase):
    """One test that exercises the real Img loader (covers the default path).
    Skipped automatically where OpenCV is unavailable."""

    def test_the_default_loader_decodes_a_real_sprite(self):
        try:
            import cv2
        except ImportError:
            self.skipTest("OpenCV not installed")
        self.assertTrue(hasattr(cv2, "imread"))            # real library, not a stub
        lib = SpriteLibrary(ASSETS, cell_size=(64, 64))   # real loader
        frames = lib.frames("wR", "idle")
        self.assertTrue(frames)
        self.assertEqual(frames[0].img.shape, (64, 64, 4))  # resized, with alpha

class TestRealLoaderRejectsUndecodableFile(unittest.TestCase):
    """The default loader must fail loudly on a file it cannot decode.

    A missing path is caught by numpy before we ever decode, so the only way to
    reach our own guard is a file that exists but holds bytes that are not an
    image -- a truncated or corrupted sprite, which is exactly the real-world
    case the guard is there for.
    """

    def test_a_file_that_is_not_an_image_raises_file_not_found(self):
        try:
            import cv2  # noqa: F401 -- the loader needs it present
        except ImportError:
            self.skipTest("OpenCV not installed")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            junk = pathlib.Path(tmp) / "not_really.png"
            junk.write_bytes(b"this is not a png")
            with self.assertRaises(FileNotFoundError):
                _load_with_img(str(junk), None)