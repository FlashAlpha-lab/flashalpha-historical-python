"""Example 4 — historical max-pain pinning study.

For every Friday close in 2024, pull SPY's max-pain strike and ask: did spot
land within 0.5% of it? This is the classic "options market makers pin
expirations" hypothesis.
"""

import os
from datetime import date, timedelta

from flashalpha_historical import FlashAlphaHistorical, replay


def fridays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() == 4:  # Friday
            yield d
        d += timedelta(days=1)


hx = FlashAlphaHistorical(os.environ["FLASHALPHA_API_KEY"])

print(f"{'date':<12} {'spot':>8} {'max_pain':>10} {'gap_pct':>9}  pinned?")
print("-" * 55)

pinned = 0
total = 0
for at, snap in replay(
    hx,
    "max_pain",
    "SPY",
    fridays(date(2024, 1, 5), date(2024, 12, 27)),
):
    spot = snap["underlying_price"]
    mp = snap["max_pain_strike"]
    if spot is None or mp is None:
        continue
    gap_pct = (spot - mp) / spot * 100.0
    is_pinned = abs(gap_pct) <= 0.5
    pinned += int(is_pinned)
    total += 1
    print(
        f"{at:<12} {spot:>8.2f} {mp:>10.2f} {gap_pct:>+8.2f}%  "
        f"{'✓' if is_pinned else ''}"
    )

print()
if total:
    print(f"pinned within ±0.5%: {pinned}/{total} ({100 * pinned / total:.1f}%)")
