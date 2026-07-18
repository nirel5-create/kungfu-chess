class GameState:
    """The state of a game in progress: the board, plus whether it has ended.

    Deliberately thin. It holds state, not behaviour -- the rules live in
    RuleEngine, the timing in RealTimeArbiter, and the coordination in
    GameEngine. It exists so that "the state of the game" is one object that
    can be handed to a printer or a snapshot builder, rather than a handful of
    loose fields.
    """

    def __init__(self, board, game_over=False):
        self.board = board
        self.game_over = game_over
