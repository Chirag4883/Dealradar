from .shopping import Shopping
from .games import Games
from .flights import Flights


def build(http):
    return {"shopping": Shopping(http), "games": Games(http), "flights": Flights(http)}
