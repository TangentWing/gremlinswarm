import unittest

from stats import MovingAverage


class TestMovingAverage(unittest.TestCase):
    def test_partial_window(self):
        ma = MovingAverage(4)
        self.assertEqual(ma.add(2), 2)
        self.assertEqual(ma.add(4), 3)
        self.assertEqual(ma.add(6), 4)

    def test_constant_signal(self):
        ma = MovingAverage(3)
        for _ in range(10):
            avg = ma.add(5)
        self.assertEqual(avg, 5 * 2 / 3)  # documented "warm-up" behaviour? (see BUGREPORT.md)


if __name__ == "__main__":
    unittest.main()
