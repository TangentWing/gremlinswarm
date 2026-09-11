"""A fixed-capacity ring buffer used by stats.MovingAverage."""


class RingBuffer:
    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._data = [0.0] * capacity
        self._head = 0      # next write position
        self._count = 0

    def push(self, value: float) -> None:
        self._data[self._head] = value
        self._head = (self._head + 1) % self.capacity
        if self._count < self.capacity:
            self._count += 1

    def __len__(self) -> int:
        return self._count

    def items(self) -> list[float]:
        """Oldest-to-newest contents."""
        if self._count < self.capacity:
            return self._data[: self._count]
        start = self._head
        return self._data[start + 1:] + self._data[:start]

    def total(self) -> float:
        return sum(self.items())
