"""Coordinates position exits: stop-loss, take-profit, and manual overrides
for the trading engine's open positions."""


def check_stop_loss(position, price):
    """Return True if the position's stop-loss threshold has been breached."""
    return price <= position.get("stop_loss", 0)


def check_take_profit(position, price):
    """Return True if the position's take-profit threshold has been reached."""
    return price >= position.get("take_profit", float("inf"))


class ExitManager:
    """Evaluates every open position each tick and issues exit orders."""

    def __init__(self, broker):
        self.broker = broker

    def evaluate(self, positions, price):
        exits = []
        for position in positions:
            if check_stop_loss(position, price) or check_take_profit(position, price):
                exits.append(position)
        return exits

    def force_exit(self, position):
        """Manually exit a position regardless of stop-loss/take-profit state."""
        self.broker.close(position)
