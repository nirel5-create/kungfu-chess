from collections import namedtuple

# A validated move in flight. Pure data: no timing math, no board access.
# RealTimeArbiter owns when it resolves; Board never sees it.
Motion = namedtuple("Motion", ["piece", "source", "destination", "arrival_time"])
