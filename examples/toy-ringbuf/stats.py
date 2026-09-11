"""Moving-average helper used by the sensor dashboard."""
from ringbuf import RingBuffer


class MovingAverage:
    def __init__(self, window: int):
        self.buf = RingBuffer(window)

    def add(self, value: float) -> float:
        self.buf.push(value)
        return self.buf.total() / len(self.buf)
