from collections import deque
from statistics import median

class TickResearch:
    """Descriptive event detector only; it does not generate trade instructions."""
    def __init__(self, window=500, multiplier=8.0, min_spike_pips=10):
        self.window = max(50, int(window))
        self.multiplier = float(multiplier)
        self.min_spike_pips = float(min_spike_pips)
        self.prices = deque(maxlen=self.window + 1)
        self.moves = deque(maxlen=self.window)
        self.previous = None

    def update(self, quote: float, pip_size: int | None):
        quote = float(quote)
        result = None
        if self.previous is not None:
            move = quote - self.previous
            if len(self.moves) >= 50:
                baseline = median(abs(x) for x in self.moves)
                pip_floor = (10 ** (-int(pip_size))) * self.min_spike_pips if pip_size is not None else 0.0
                threshold = max(baseline * self.multiplier, pip_floor)
                if move < -threshold:
                    result = {
                        "previous_quote": self.previous,
                        "quote": quote,
                        "delta": move,
                        "threshold": threshold
                    }
            self.moves.append(move)
        self.previous = quote
        self.prices.append(quote)
        return result
