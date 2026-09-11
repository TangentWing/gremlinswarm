# Dashboard moving average drifts low

Reported by the ops team:

> The 5-sample moving average on the temperature panel is correct for the first few
> readings after a restart, then reads noticeably low — roughly 20% under the real value
> for a steady signal. Restarting the dashboard fixes it for a moment.

Someone added `test_constant_signal` with an expected value copied from the current
output, assuming it was intended warm-up behaviour. Nobody is sure whether the test or the
code is right.

Log excerpt (window = 5, constant input 20.0):

```
t=1 avg=20.0
t=2 avg=20.0
t=3 avg=20.0
t=4 avg=20.0
t=5 avg=16.0
t=6 avg=16.0
t=7 avg=16.0
```
