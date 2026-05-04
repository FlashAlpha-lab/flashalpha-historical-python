# flashalpha-historical

Python SDK for the **FlashAlpha Historical API** — point-in-time replay of
every live analytics endpoint. Ask what GEX, gamma flip, VRP, narrative, max
pain, or the full stock summary looked like at any **minute back to
2018-04-16**, in the same response shape as the live API.

Coverage: SPY 2018-04-16 → today, with daily extensions; more symbols
added on demand.

```bash
pip install flashalpha-historical
```

Requires Python 3.10+. Same `X-Api-Key` you use for `api.flashalpha.com`.
**Alpha plan or higher** on every endpoint.

## Quickstart

```python
from flashalpha_historical import FlashAlphaHistorical

hx = FlashAlphaHistorical("YOUR_API_KEY")

# One snapshot — what dealer positioning looked like during the COVID crash
snap = hx.exposure_summary("SPY", at="2020-03-16T15:30:00")
print(snap["regime"], snap["exposures"]["net_gex"])
# → 'negative_gamma' -2633970601
```

The `at=` parameter accepts strings (`"2026-03-05T15:30:00"` or
`"2026-03-05"` → defaults to 16:00 ET), `datetime` objects, or `date` objects.

## Backtesting

The SDK ships with replay utilities that turn any endpoint into an iterator
over a date / minute range. Holiday calendar is built in (NYSE 2018-2026);
gap days are skipped silently by default.

### Daily replay

```python
from flashalpha_historical import FlashAlphaHistorical, Backtester, iter_days

hx = FlashAlphaHistorical("YOUR_API_KEY")

def strategy(at, snap):
    """Short vol when VRP rich AND dealers long gamma."""
    vrp = snap["volatility"]["vrp"]
    regime = snap["exposure"]["regime"]
    return {
        "signal": "short_strangle" if vrp > 5 and regime == "positive_gamma" else None,
        "vrp": vrp,
        "regime": regime,
    }

bt = Backtester(hx, method="stock_summary", symbol="SPY")
results = bt.run(iter_days("2024-01-02", "2024-03-29"), strategy)

# Convert to DataFrame
import pandas as pd
df = pd.DataFrame(bt.to_records(results))
```

### Minute-level replay

```python
from flashalpha_historical import iter_minutes, replay

# Walk every 15 minutes through one trading day
for at, snap in replay(hx, "exposure_summary", "SPY",
                       iter_minutes("2025-01-15", "2025-01-15", step_minutes=15)):
    print(at, snap["regime"], snap["gamma_flip"], snap["exposures"]["net_gex"])
```

> **Quota note:** every call counts against your daily plan quota (shared
> with the live API). 1-minute replay = 390 calls per analytic per day —
> coarsen with `step_minutes=15` or `step_minutes=30` for development loops.

## API

Every analytics method takes a required `at` keyword argument.

### Coverage

| Method | Endpoint |
|---|---|
| `tickers()` | `GET /v1/tickers` |
| `tickers(symbol="SPY")` | `GET /v1/tickers?symbol=SPY` |

### Market data

| Method | Endpoint |
|---|---|
| `stock_quote(ticker, at=...)` | `/v1/stockquote/{ticker}` |
| `option_quote(ticker, at=..., expiry=, strike=, type=)` | `/v1/optionquote/{ticker}` |
| `surface(symbol, at=...)` | `/v1/surface/{symbol}` |

### Exposure analytics

| Method | Endpoint |
|---|---|
| `gex(symbol, at=..., expiration=, min_oi=)` | `/v1/exposure/gex/{symbol}` |
| `dex(symbol, at=..., expiration=)` | `/v1/exposure/dex/{symbol}` |
| `vex(symbol, at=..., expiration=)` | `/v1/exposure/vex/{symbol}` |
| `chex(symbol, at=..., expiration=)` | `/v1/exposure/chex/{symbol}` |
| `exposure_summary(symbol, at=...)` | `/v1/exposure/summary/{symbol}` |
| `exposure_levels(symbol, at=...)` | `/v1/exposure/levels/{symbol}` |
| `narrative(symbol, at=...)` | `/v1/exposure/narrative/{symbol}` |
| `zero_dte(symbol, at=..., strike_range=)` | `/v1/exposure/zero-dte/{symbol}` |

### Composite & vol

| Method | Endpoint |
|---|---|
| `stock_summary(symbol, at=...)` | `/v1/stock/{symbol}/summary` |
| `volatility(symbol, at=...)` | `/v1/volatility/{symbol}` |
| `adv_volatility(symbol, at=...)` | `/v1/adv_volatility/{symbol}` |
| `vrp(symbol, at=...)` | `/v1/vrp/{symbol}` |
| `max_pain(symbol, at=..., expiration=)` | `/v1/maxpain/{symbol}` |

## Errors

```python
from flashalpha_historical import (
    FlashAlphaHistoricalError,    # base
    AuthenticationError,          # 401
    TierRestrictedError,          # 403 — needs Alpha plan
    InvalidAtError,               # 400 — bad `at` format
    NoDataError,                  # 404 — outside coverage / inside gap
    SymbolNotFoundError,          # 404 — symbol not at this `at`
    NoCoverageError,              # 404 — symbol not in historical dataset
    InsufficientDataError,        # 404 — surface grid too sparse
    RateLimitError,               # 429
    ServerError,                  # 5xx
)

try:
    hx.exposure_summary("SPY", at="2017-01-01")  # before coverage starts
except NoDataError as e:
    print("gap:", e)
```

## Known gaps from live (intentional, documented)

- `optionquote.bidSize` / `askSize` — always `0` (minute table has no sizes)
- `optionquote.volume` / `gex.call_volume` / `put_volume` — always `0`
- `optionquote.svi_vol` — `null` with `svi_vol_gated: "backtest_mode"`
- `narrative.data.top_oi_changes` — empty array (no prior-day OI diff yet)
- `gex.call_oi_change` / `put_oi_change` — always `null`
- `stock_summary.macro.vix_futures` / `fear_and_greed` — `null`
- `vrp.macro.hy_spread` — hard-coded `3.5`
- 0DTE intraday greeks (delta/gamma/theta/iv) often `0` / `null` — chain
  still listed for OI analysis

## License

MIT
