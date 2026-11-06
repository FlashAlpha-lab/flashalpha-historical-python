"""Replay sell-window: what did it say on every session in a date range?

Run:  FLASHALPHA_API_KEY=... python examples/sell_window_replay.py SPY 2026-10-12 2026-10-16
Docs: https://flashalpha.com/docs/historical-sell-window

The backtests entered at 09:35 ET, so T09:35:00 returns the backtest's entry strikes.
"""

import os
import sys

from flashalpha_historical import FlashAlphaHistorical
from flashalpha_historical.replay import iter_days

symbol, start, end = (sys.argv[1:4] + ["SPY", "2026-10-12", "2026-10-16"][len(sys.argv) - 1 :])[:3]
hx = FlashAlphaHistorical(os.environ["FLASHALPHA_API_KEY"])

for day in iter_days(start, end):
    answer = hx.sell_window(symbol, at=f"{day:%Y-%m-%d}T09:35:00")
    actions = ", ".join(f"{w.get('expiry', 'none')} {w['action']}" for w in answer["windows"])
    print(f"{answer['session']}: {actions}")
