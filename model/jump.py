from collections import namedtuple

# A piece currently airborne. Pure data: no timing math, no board access.
# RealTimeArbiter owns when it resolves; Board never sees it.
Jump = namedtuple("Jump", ["piece", "cell", "end_time"])
