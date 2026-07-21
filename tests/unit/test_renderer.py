import unittest

from model.board import Board
from model.config import Config
from model.snapshot import (
    GameSnapshot, PieceView, STATE_IDLE, STATE_MOVING, STATE_JUMPING,
    STATE_RESTING_LONG, STATE_RESTING_SHORT,
)
from tests.helpers import make_game
from view.renderer import Renderer


class FakeFrame:
    """A stand-in sprite. Records where it was told to draw itself."""

    def __init__(self, tag):
        self.tag = tag
        self.drawn_at = None

    def draw_on(self, board, x, y):
        self.drawn_at = (board, x, y)


class FakeSprites:
    """A SpriteLibrary stand-in: hands back one FakeFrame per (token, state) so
    a test can assert which sprite was chosen without decoding a real png."""

    def __init__(self, missing=()):
        self.requested = []
        self._missing = set(missing)

    def frames(self, token, state):
        self.requested.append((token, state))
        if (token, state) in self._missing:
            return []
        return [FakeFrame(f"{token}/{state}")]


class _FakeBoardBuf:
    """A stand-in board image with a cloneable .img, like the real Img. Must be
    constructible with no args (type(x)() in _fresh_board), like the real Img."""
    def __init__(self, tag="clone"):
        self.img = _CloneableTag(tag)


class _CloneableTag:
    def __init__(self, tag):
        self.tag = tag
    def copy(self):
        return _CloneableTag(self.tag)


class FakeBoardImage:
    def __init__(self):
        self.loads = 0

    def __call__(self, path):
        self.loads += 1
        return _FakeBoardBuf(f"board#{self.loads}")


def _snapshot_of(pieces):
    return GameSnapshot(board_width=8, board_height=8, cell_size=100,
                        pieces=tuple(pieces), selected_cell=None, game_over=False)


class TestTokenAndState(unittest.TestCase):
    def setUp(self):
        self.r = Renderer(FakeSprites(), FakeBoardImage(), "board.png")

    def test_token_is_colour_then_type(self):
        piece = PieceView("R", "w", 0, 0, 0, 0, STATE_IDLE)
        self.assertEqual(self.r.token_of(piece), "wR")

    def test_engine_states_map_to_sprite_folders(self):
        self.assertEqual(self.r.sprite_state(STATE_IDLE), "idle")
        self.assertEqual(self.r.sprite_state(STATE_MOVING), "move")
        self.assertEqual(self.r.sprite_state(STATE_JUMPING), "jump")
        self.assertEqual(self.r.sprite_state(STATE_RESTING_LONG), "long_rest")
        self.assertEqual(self.r.sprite_state(STATE_RESTING_SHORT), "short_rest")


class TestPlacements(unittest.TestCase):
    def setUp(self):
        self.sprites = FakeSprites()
        self.r = Renderer(self.sprites, FakeBoardImage(), "board.png")

    def test_each_piece_is_placed_at_its_pixel_position(self):
        pieces = [PieceView("R", "w", 0, 0, 0, 0, STATE_IDLE),
                  PieceView("K", "b", 7, 4, 400, 700, STATE_IDLE)]
        placements = self.r.placements(_snapshot_of(pieces))
        coords = [(x, y) for _frame, x, y in placements]
        self.assertEqual(coords, [(0, 0), (400, 700)])

    def test_a_moving_piece_draws_its_move_sprite(self):
        pieces = [PieceView("R", "w", 0, 0, 150, 0, STATE_MOVING)]
        self.r.placements(_snapshot_of(pieces))
        self.assertIn(("wR", "move"), self.sprites.requested)

    def test_a_piece_with_no_sprites_is_skipped_not_crashed(self):
        sprites = FakeSprites(missing=[("wR", "idle")])
        r = Renderer(sprites, FakeBoardImage(), "board.png")
        pieces = [PieceView("R", "w", 0, 0, 0, 0, STATE_IDLE),
                  PieceView("K", "b", 1, 1, 100, 100, STATE_IDLE)]
        placements = r.placements(_snapshot_of(pieces))
        self.assertEqual(len(placements), 1)              # only the king drawn


class TestRenderDraws(unittest.TestCase):
    def test_render_loads_the_board_once_then_clones_it(self):
        board_image = FakeBoardImage()
        r = Renderer(FakeSprites(), board_image, "board.png")
        snap = _snapshot_of([PieceView("R", "w", 0, 0, 0, 0, STATE_IDLE)])
        r.render(snap)
        r.render(snap)
        r.render(snap)
        self.assertEqual(board_image.loads, 1)   # read from disk once, cloned after

    def test_render_draws_every_piece_onto_the_board(self):
        r = Renderer(FakeSprites(), FakeBoardImage(), "board.png")
        pieces = [PieceView("R", "w", 0, 0, 0, 0, STATE_IDLE),
                  PieceView("K", "b", 7, 4, 400, 700, STATE_IDLE)]
        board = r.render(_snapshot_of(pieces))
        self.assertEqual(board.img.tag, "board#1")   # cloned from the loaded board

    def test_render_skips_a_piece_with_no_sprites(self):
        import numpy as np
        from model.snapshot import STATE_IDLE
        from view.renderer import Renderer

        class TinyBoard:
            def __init__(self): self.img = np.zeros((800, 800, 3), dtype=np.uint8)

        sprites = FakeSprites(missing=[("wR", "idle")])
        r = Renderer(sprites, lambda p: TinyBoard(), "b.png")
        piece = PieceView("R", "w", 0, 0, 0, 0, STATE_IDLE, 0.0)
        out = r.render(GameSnapshot(8, 8, 100, (piece,), None, False))
        self.assertEqual(out.img.sum(), 0)


class TestRendererConsumesRealSnapshot(unittest.TestCase):
    """The renderer must work off a real engine snapshot -- the whole point of
    S19. No live Board or Piece is passed."""

    def test_a_real_snapshot_places_every_piece(self):
        config = Config()
        board = Board([["wR", ".", "bK"]], config)
        engine, _ = make_game(board, config)
        r = Renderer(FakeSprites(), FakeBoardImage(), "board.png")
        placements = r.placements(engine.snapshot())
        self.assertEqual(len(placements), 2)              # wR and bK



class TestSelectionHighlight(unittest.TestCase):
    def setUp(self):
        self.r = Renderer(FakeSprites(), FakeBoardImage(), "board.png")

    def test_no_selection_means_no_highlight(self):
        snap = _snapshot_of([])
        self.assertIsNone(self.r.highlight_rect(snap))

    def test_a_selected_cell_maps_to_its_pixel_rectangle(self):
        # cell (row=2, col=3) at cell_size 100 -> rect at (300, 200), 100x100.
        snap = GameSnapshot(8, 8, 100, (), (2, 3), False)
        self.assertEqual(self.r.highlight_rect(snap), (300, 200, 100, 100))

    def test_the_top_left_cell_highlights_at_the_origin(self):
        snap = GameSnapshot(8, 8, 100, (), (0, 0), False)
        self.assertEqual(self.r.highlight_rect(snap), (0, 0, 100, 100))

    def test_the_highlight_shifts_by_the_board_offset(self):
        # With a framed board (offset 13, 15), cell (2, 3) at size 100 lands at
        # (13 + 300, 15 + 200), so the glow sits on the piece, not beside it.
        snap = GameSnapshot(8, 8, 100, (), (2, 3), False, board_offset=(13, 15))
        self.assertEqual(self.r.highlight_rect(snap), (313, 215, 100, 100))




class TestTintAndRenderHighlight(unittest.TestCase):
    """The tint blends onto a real numpy buffer, so these use a tiny real image
    rather than a fake -- the one place the pixel maths must actually run."""

    def _tiny_board(self):
        import numpy as np
        from view.renderer import _tint

        class TinyImg:
            def __init__(self):
                self.img = np.zeros((200, 200, 3), dtype=np.uint8)  # black

        return TinyImg, _tint

    def test_tint_lightens_the_selected_cell(self):
        TinyImg, _tint = self._tiny_board()
        img = TinyImg()
        _tint(img, (0, 0, 100, 100), (120, 220, 255), 0.35)
        self.assertGreater(img.img[50, 50].sum(), 0)          # was black, now tinted
        self.assertEqual(tuple(img.img[150, 150]), (0, 0, 0))  # outside cell untouched

    def test_tint_clamped_at_the_edge_does_not_overflow(self):
        TinyImg, _tint = self._tiny_board()
        img = TinyImg()
        _tint(img, (150, 150, 100, 100), (120, 220, 255), 0.35)                       # runs past the edge
        self.assertGreater(img.img[175, 175].sum(), 0)         # clamped region tinted

    def test_a_fully_offscreen_rect_tints_nothing(self):
        TinyImg, _tint = self._tiny_board()
        img = TinyImg()
        before = img.img.copy()
        _tint(img, (500, 500, 100, 100), (120, 220, 255), 0.35)                       # entirely off-image
        self.assertTrue((img.img == before).all())

    def test_render_applies_the_highlight_to_the_board(self):
        import numpy as np
        from view.renderer import Renderer

        class TinyBoard:
            def __init__(self): self.img = np.zeros((800, 800, 3), dtype=np.uint8)

        r = Renderer(FakeSprites(), lambda p: TinyBoard(), "b.png")
        snap = GameSnapshot(8, 8, 100, (), (0, 0), False)      # cell (0,0) selected
        out = r.render(snap)
        self.assertGreater(out.img[50, 50].sum(), 0)           # highlight drawn




class TestStateOverlays(unittest.TestCase):
    """Jump and cooldown markers drawn under the sprite, on a real buffer."""

    def _renderer_with_real_board(self):
        import numpy as np
        from view.renderer import Renderer

        class TinyBoard:
            def __init__(self): self.img = np.zeros((800, 800, 3), dtype=np.uint8)

        return Renderer(FakeSprites(), lambda p: TinyBoard(), "b.png")

    def test_a_jumping_piece_gets_a_halo(self):
        from model.snapshot import STATE_JUMPING
        r = self._renderer_with_real_board()
        piece = PieceView("K", "w", 0, 0, 0, 0, STATE_JUMPING, 0.0)
        out = r.render(GameSnapshot(8, 8, 100, (piece,), None, False))
        self.assertGreater(out.img[50, 50].sum(), 0)      # halo tinted the cell

    def test_a_resting_piece_is_dimmed_and_ringed(self):
        from model.snapshot import STATE_RESTING_LONG
        r = self._renderer_with_real_board()
        piece = PieceView("R", "w", 0, 0, 0, 0, STATE_RESTING_LONG, 0.5)
        out = r.render(GameSnapshot(8, 8, 100, (piece,), None, False))
        self.assertGreater(out.img[50, 50].sum(), 0)      # dim wash applied

    def test_the_ring_is_skipped_at_zero_progress(self):
        from view.renderer import _draw_ring
        import numpy as np

        class TinyBoard:
            def __init__(self): self.img = np.zeros((200, 200, 3), dtype=np.uint8)

        board = TinyBoard()
        before = board.img.copy()
        _draw_ring(board, 0, 0, 100, 0.0)                 # nothing to draw
        self.assertTrue((board.img == before).all())

    def test_the_ring_offscreen_draws_nothing(self):
        from view.renderer import _draw_ring
        import numpy as np

        class TinyBoard:
            def __init__(self): self.img = np.zeros((100, 100, 3), dtype=np.uint8)

        board = TinyBoard()
        before = board.img.copy()
        _draw_ring(board, 500, 500, 98, 0.5)             # entirely off-image
        self.assertTrue((board.img == before).all())

    def test_the_ring_draws_at_partial_progress(self):
        from view.renderer import _draw_ring
        import numpy as np

        class TinyBoard:
            def __init__(self): self.img = np.zeros((200, 200, 3), dtype=np.uint8)

        board = TinyBoard()
        _draw_ring(board, 0, 0, 100, 0.5)
        self.assertGreater(board.img.sum(), 0)            # arc drawn




class TestMotion(unittest.TestCase):
    """Breathing (a smooth vertical float) and jumping (a single arc) are pure
    clock -> offset maths, tested here without drawing."""

    def test_an_idle_piece_floats_up_and_back(self):
        from view.renderer import _breathe_offset, _BREATHE_FLOAT
        from model.snapshot import STATE_IDLE
        offs = [_breathe_offset(STATE_IDLE, t, 100) for t in range(0, 3500, 200)]
        limit = _BREATHE_FLOAT * 100 + 1e-6
        self.assertTrue(all(-limit <= o <= limit for o in offs))
        self.assertTrue(max(offs) > 0 and min(offs) < 0)   # actually drifts

    def test_a_non_idle_piece_does_not_float(self):
        from view.renderer import _breathe_offset
        from model.snapshot import STATE_MOVING, STATE_JUMPING
        self.assertEqual(_breathe_offset(STATE_MOVING, 1234, 100), 0.0)
        self.assertEqual(_breathe_offset(STATE_JUMPING, 1234, 100), 0.0)

    def test_a_moving_piece_sways_side_to_side(self):
        from view.renderer import _walk_sway, _WALK_SWAY
        from model.snapshot import STATE_MOVING
        sways = [_walk_sway(STATE_MOVING, t, 100) for t in range(0, 600, 50)]
        limit = _WALK_SWAY * 100 + 1e-6
        self.assertTrue(all(-limit <= sw <= limit for sw in sways))
        self.assertTrue(max(sways) > 0 and min(sways) < 0)   # actually sways

    def test_a_still_piece_does_not_sway(self):
        from view.renderer import _walk_sway
        from model.snapshot import STATE_IDLE, STATE_JUMPING
        self.assertEqual(_walk_sway(STATE_IDLE, 300, 100), 0.0)
        self.assertEqual(_walk_sway(STATE_JUMPING, 300, 100), 0.0)

    def test_a_jumping_piece_lifts_off_the_board_and_returns(self):
        from view.renderer import _jump_lift
        from model.snapshot import STATE_JUMPING
        lifts = [_jump_lift(STATE_JUMPING, t, 100) for t in range(0, 900, 100)]
        self.assertEqual(lifts[0], 0.0)          # starts on the ground
        self.assertTrue(max(lifts) > 0)          # rises during the hop

    def test_a_grounded_piece_has_no_lift(self):
        from view.renderer import _jump_lift
        from model.snapshot import STATE_IDLE, STATE_MOVING
        self.assertEqual(_jump_lift(STATE_IDLE, 250, 100), 0.0)
        self.assertEqual(_jump_lift(STATE_MOVING, 250, 100), 0.0)

    def test_drawing_a_floating_piece_offsets_it_upward(self):
        import numpy as np
        from view.renderer import Renderer
        from model.snapshot import STATE_IDLE

        class RealFrame:
            def __init__(self): self.img = np.ones((100, 100, 3), dtype=np.uint8)
            def draw_on(self, board, x, y):
                self.at = (x, y)
                board.img[max(0, y):y + 100, max(0, x):x + 100] = 255

        frame = RealFrame()
        class RealSprites:
            def frames(self, token, state): return [frame]  # noqa: ARG002

        class TinyBoard:
            def __init__(self): self.img = np.zeros((400, 400, 3), dtype=np.uint8)

        r = Renderer(RealSprites(), lambda p: TinyBoard(), "b.png")
        piece = PieceView("K", "w", 1, 1, 100, 100, STATE_IDLE, 0.0)
        # clock at quarter period -> peak upward float, so y drawn < 100.
        r.render(GameSnapshot(8, 8, 100, (piece,), None, False), clock_ms=875)
        self.assertLess(frame.at[1], 100)        # floated up


if __name__ == "__main__":
    unittest.main()
