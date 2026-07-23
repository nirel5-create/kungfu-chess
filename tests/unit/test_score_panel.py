import unittest

from model.config import Config
from model.snapshot import GameSnapshot, PieceView, STATE_IDLE
from view.observer import GameObserver
from view.score_panel import ScorePanel


def _snap(tokens_at):
    pieces = tuple(
        PieceView(t[1], t[0], r, c, 0, 0, STATE_IDLE)
        for (r, c), t in tokens_at.items()
    )
    return GameSnapshot(8, 8, 100, pieces, None, False)


class FakeImage:
    """Records every put_text call so the panel's drawing can be asserted."""

    def __init__(self):
        self.texts = []

    def put_text(self, txt, x, y, font_size, color=(255, 255, 255, 255), thickness=1):
        self.texts.append((txt, x, y, font_size))


class TestScorePanelLines(unittest.TestCase):
    def setUp(self):
        self.obs = GameObserver(Config(), white_name="Alice", black_name="Bob")
        self.panel = ScorePanel(self.obs, x=850, y=40)

    def test_it_shows_both_players_names_and_scores(self):
        lines = self.panel.lines()
        texts = [ln.text for ln in lines]
        self.assertIn("Alice: 0", texts)
        self.assertIn("Bob: 0", texts)

    def test_scores_update_after_a_capture(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.obs.observe(_snap({(0, 1): "wR"}))           # Alice took a knight
        texts = [ln.text for ln in self.panel.lines()]
        self.assertIn("Alice: 3", texts)

    def test_a_capture_appears_in_the_log_lines(self):
        self.obs.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        self.obs.observe(_snap({(0, 1): "wR"}))
        texts = [ln.text for ln in self.panel.lines()]
        self.assertTrue(any("took bN" in t for t in texts))

    def test_the_log_is_capped_so_the_panel_stays_bounded(self):
        # Feed 20 captures; only the last 12 log lines should show (plus 2 score
        # lines).
        self.obs.observe(_snap({(r, 0): "wP" for r in range(20)}
                               | {(r, 1): "bP" for r in range(20)}))
        for r in range(20):
            remaining = {(rr, 0): "wP" for rr in range(20)}
            remaining |= {(rr, 1): "bP" for rr in range(r + 1, 20)}
            self.obs.observe(_snap(remaining))
        lines = self.panel.lines()
        self.assertLessEqual(len(lines), 2 + 12)          # 2 scores + 12 log max

    def test_lines_advance_down_the_panel(self):
        ys = [ln.y for ln in self.panel.lines()]
        self.assertEqual(ys, sorted(ys))                  # each line below the last


class TestScorePanelDraw(unittest.TestCase):
    def test_draw_paints_every_line_onto_the_image(self):
        obs = GameObserver(Config())
        panel = ScorePanel(obs, x=850, y=40)
        image = FakeImage()
        panel.draw(image)
        self.assertEqual(len(image.texts), len(panel.lines()))

    def test_the_two_score_lines_are_drawn_larger_than_log_lines(self):
        obs = GameObserver(Config())
        obs.observe(_snap({(0, 0): "wR", (0, 1): "bN"}))
        obs.observe(_snap({(0, 1): "wR"}))
        panel = ScorePanel(obs, x=850, y=40)
        image = FakeImage()
        panel.draw(image)
        score_sizes = {image.texts[0][3], image.texts[1][3]}
        log_size = image.texts[2][3]
        self.assertTrue(all(s > log_size for s in score_sizes))


if __name__ == "__main__":
    unittest.main()
