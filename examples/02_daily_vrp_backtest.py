"""Example 2 — daily backtest of a VRP-harvest signal.

Walks SPY day by day, pulls the full stock summary at session close, and
flags days where:
   1. variance risk premium (VRP) > 5 vol points
   2. dealers are long gamma (positive_gamma regime)

Both conditions together = classic short-vol-harvest setup. Outputs the
signal log and a few summary stats. No fill simulation, no portfolio
accounting — just decision-time signals.
"""

import os
from collections import Counter

from flashalpha_historical import Backtester, FlashAlphaHistorical, iter_days

hx = FlashAlphaHistorical(os.environ["FLASHALPHA_API_KEY"])


def vrp_harvest(at, snap):
    vrp = snap["volatility"]["vrp"]
    regime = snap["exposure"]["regime"]
    fire = vrp is not None and vrp > 5 and regime == "positive_gamma"
    return {
        "fire": fire,
        "vrp": vrp,
        "regime": regime,
        "atm_iv": snap["volatility"]["atm_iv"],
    }


bt = Backtester(hx, method="stock_summary", symbol="SPY")
results = bt.run(iter_days("2024-01-02", "2024-03-29"), vrp_harvest)

fires = [r for r in results if r.output["fire"]]
regimes = Counter(r.output["regime"] for r in results)

print(f"days replayed:   {len(results)}")
print(f"signal fires:    {len(fires)}")
print(f"regime breakdown:")
for regime, n in regimes.most_common():
    print(f"  {regime:>20}: {n}")

print()
print("fire dates:")
for r in fires[:10]:
    print(f"  {r.at}  vrp={r.output['vrp']:.2f}  iv={r.output['atm_iv']:.2f}")

# Pandas-friendly export
try:
    import pandas as pd

    df = pd.DataFrame(bt.to_records(results))
    print()
    print("first 5 rows of bt.to_records():")
    print(df.head())
except ImportError:
    pass
