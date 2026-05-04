"""Example 3 — intraday gamma-flip tracking.

Replay one trading day at 15-minute resolution and watch SPY's gamma flip
move relative to spot. When spot crosses the flip, the dealer hedging
regime changes (positive_gamma → negative_gamma is a known volatility
catalyst).
"""

import os

from flashalpha_historical import FlashAlphaHistorical, iter_minutes, replay

hx = FlashAlphaHistorical(os.environ["FLASHALPHA_API_KEY"])

print(f"{'time':<20} {'spot':>8} {'flip':>8} {'gap':>7} {'regime':>17}")
print("-" * 65)

last_regime = None
for at, snap in replay(
    hx,
    "exposure_summary",
    "SPY",
    iter_minutes("2024-08-05", "2024-08-05", step_minutes=15),
):
    spot = snap["underlying_price"]
    flip = snap["gamma_flip"]
    gap = spot - flip if (spot is not None and flip is not None) else None
    regime = snap["regime"]
    flag = " ⚑" if last_regime is not None and regime != last_regime else ""
    print(f"{at:<20} {spot:>8.2f} {flip:>8.2f} {gap:>7.2f} {regime:>17}{flag}")
    last_regime = regime
