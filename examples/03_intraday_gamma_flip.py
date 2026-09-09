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
    regime = snap["regime"]
    flag = " ⚑" if last_regime is not None and regime != last_regime else ""
    # No flip is published for most chains. ``gamma_flip`` is then null and
    # ``gamma_flip_status`` carries the reason code, so don't format it as a
    # number -- print the reason instead.
    if flip is None:
        flip_s = gap_s = "-"
        flag += f"  ({snap.get('gamma_flip_status') or 'unavailable'})"
    else:
        flip_s, gap_s = f"{flip:.2f}", f"{spot - flip:.2f}"
    print(f"{at:<20} {spot:>8.2f} {flip_s:>8} {gap_s:>7} {regime:>17}{flag}")
    last_regime = regime
