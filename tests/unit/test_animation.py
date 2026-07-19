import pathlib
import unittest

from view.animation import Animation, load_state_config

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets" / "pieces_mine"


class TestLoopingAnimation(unittest.TestCase):
    """A looping animation (idle, walking) cycles through its frames forever."""

    def setUp(self):
        self.anim = Animation(frames_per_sec=10, is_loop=True)  # 1 frame / 100ms

    def test_it_starts_on_the_first_frame(self):
        self.assertEqual(self.anim.frame_index(5, 0), 0)

    def test_it_advances_one_frame_per_period(self):
        self.assertEqual(self.anim.frame_index(5, 100), 1)
        self.assertEqual(self.anim.frame_index(5, 200), 2)

    def test_it_wraps_back_to_the_start(self):
        # 5 frames at 10 fps: frame 5 would be at 500ms, wraps to 0.
        self.assertEqual(self.anim.frame_index(5, 500), 0)
        self.assertEqual(self.anim.frame_index(5, 600), 1)

    def test_a_frame_holds_for_its_whole_period(self):
        # Still on frame 0 at 99ms, flips to 1 at 100ms.
        self.assertEqual(self.anim.frame_index(5, 99), 0)
        self.assertEqual(self.anim.frame_index(5, 100), 1)


class TestNonLoopingAnimation(unittest.TestCase):
    """A one-shot animation (jump, rest) plays once and holds the last frame."""

    def setUp(self):
        self.anim = Animation(frames_per_sec=10, is_loop=False)

    def test_it_advances_then_stops_on_the_last_frame(self):
        self.assertEqual(self.anim.frame_index(5, 0), 0)
        self.assertEqual(self.anim.frame_index(5, 400), 4)     # last frame
        self.assertEqual(self.anim.frame_index(5, 5000), 4)    # still last, held

    def test_it_never_wraps(self):
        self.assertEqual(self.anim.frame_index(3, 9999), 2)    # holds at 2, not 0


class TestPick(unittest.TestCase):
    def test_pick_returns_the_frame_object_for_now(self):
        anim = Animation(frames_per_sec=10, is_loop=True)
        frames = ["a", "b", "c"]
        self.assertEqual(anim.pick(frames, 0), "a")
        self.assertEqual(anim.pick(frames, 100), "b")

    def test_pick_of_no_frames_is_none(self):
        self.assertIsNone(Animation().pick([], 0))

    def test_zero_frames_index_is_zero_not_a_crash(self):
        self.assertEqual(Animation().frame_index(0, 500), 0)


class TestFromConfig(unittest.TestCase):
    def test_it_reads_fps_and_loop_from_a_config_dict(self):
        anim = Animation.from_config(
            {"graphics": {"frames_per_sec": 8, "is_loop": False}})
        self.assertEqual(anim.frames_per_sec, 8)
        self.assertFalse(anim.is_loop)

    def test_missing_graphics_fields_fall_back_to_defaults(self):
        anim = Animation.from_config({})
        self.assertEqual(anim.frames_per_sec, 6)
        self.assertTrue(anim.is_loop)


class TestLoadStateConfig(unittest.TestCase):
    """Reads the real config.json files shipped with the assets."""

    def test_move_config_loops_at_its_stated_fps(self):
        cfg = load_state_config(ASSETS, "wR", "move")
        anim = Animation.from_config(cfg)
        self.assertTrue(anim.is_loop)                          # walking loops
        self.assertEqual(anim.frames_per_sec, cfg["graphics"]["frames_per_sec"])

    def test_a_missing_config_is_an_empty_dict_not_an_error(self):
        self.assertEqual(load_state_config(ASSETS, "wR", "no_such_state"), {})


if __name__ == "__main__":
    unittest.main()
