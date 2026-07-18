class Controller:
    """Turns user actions into game commands. Holds the selection, and nothing
    else: it never decides whether a move is legal, never touches the board,
    and never advances time -- it asks the engine.

    Depends on the engine's command surface only, so a fake engine is enough to
    unit-test it (Design Guide S16).
    """

    def __init__(self, engine, mapper, board, config):
        self._engine = engine
        self._mapper = mapper
        self._board = board
        self._config = config
        self._selection = None  # (row, col) or None

    @property
    def selection(self):
        return self._selection

    def click(self, x, y):
        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            # Outside the board. With a piece selected this cancels it and sends
            # no command (guide S11) -- the only way to change your mind. With
            # nothing selected there is nothing to cancel, so it is ignored.
            self._selection = None
            return
        target = self._board.piece_at(*cell)
        if self._selection is None:
            if target is not None:
                self._selection = cell  # first click selects
            return  # empty cell with no selection -> ignored
        selected = self._board.piece_at(*self._selection)
        if target is not None and self._config.same_color(target, selected):
            # Clicking another of your own pieces re-selects it rather than
            # issuing a move that could only be refused. Guide S11 would clear
            # the selection instead, and says why: "so tests remain simple".
            # That costs a third click on every change of mind, which matters
            # more in a real-time game than in a turn-based one. See D-5.
            self._selection = cell
            return
        self._engine.request_move(self._selection, cell)
        self._selection = None

    def jump(self, x, y):
        cell = self._mapper.pixel_to_cell(x, y)
        if cell is None:
            return  # outside the board -> ignored, mirrors click()
        self._engine.request_jump(cell)
