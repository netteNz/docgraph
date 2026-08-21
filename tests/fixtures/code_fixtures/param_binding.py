"""Fixture 3/4: parameter-to-binding resolution, positive and negative."""


class ReplayBuffer:
    def __init__(self):
        self.items = []


def train(replay_buffer, data):
    """`replay_buffer` param resolves to the ReplayBuffer class above via
    case-normalized matching; `data` resolves to nothing and must be
    silently dropped, not defaulted to some fallback name."""
    replay_buffer.items.append(data)
    return len(replay_buffer.items)
