import pathlib
import unittest

from view.animation_set import AnimationSet

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets" / "pieces_mine"


class FakeConfigLoader:
    """Returns a canned config per (token, state) so timing can be asserted with
    no files. Handed in through the constructor."""

    def __init__(self, configs):
        self._configs = configs
        self.calls = 0

    def __call__(self, root, token, state):
        self.calls += 1
        return self._configs.get((token, state), {})


class TestAnimationSet(unittest.TestCase):
    def test_it_builds_an_animation_from_a_states_config(self):
        loader = FakeConfigLoader({
            ("wR", "move"): {"graphics": {"frames_per_sec": 8, "is_loop": True}},
        })
        aset = AnimationSet("root", config_loader=loader)
        anim = aset.animation("wR", "move")
        self.assertEqual(anim.frames_per_sec, 8)

    def test_configs_are_read_once_and_cached(self):
        loader = FakeConfigLoader({})
        aset = AnimationSet("root", config_loader=loader)
        aset.animation("wR", "move")
        aset.animation("wR", "move")
        self.assertEqual(loader.calls, 1)                  # second call cached

    def test_frame_picks_the_current_sprite(self):
        loader = FakeConfigLoader({
            ("wR", "idle"): {"graphics": {"frames_per_sec": 10, "is_loop": True}},
        })
        aset = AnimationSet("root", config_loader=loader)
        frames = ["a", "b", "c"]
        self.assertEqual(aset.frame(frames, "wR", "idle", 0), "a")
        self.assertEqual(aset.frame(frames, "wR", "idle", 100), "b")


class TestAnimationSetOnRealConfigs(unittest.TestCase):
    def test_real_move_config_is_a_loop(self):
        aset = AnimationSet(ASSETS)                         # real loader
        self.assertTrue(aset.animation("wR", "move").is_loop)


if __name__ == "__main__":
    unittest.main()
