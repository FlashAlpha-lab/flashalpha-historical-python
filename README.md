# flashalpha-historical

Python SDK for the **FlashAlpha Historical API** — point-in-time replay of
every live analytics endpoint. Ask what GEX, gamma flip, VRP, narrative, max
pain, or the full stock summary looked like at any **minute back to
2017-01-03**, in the same response shape as the live API.

Coverage: SPY 2017-01-03 → today, with daily extensions; more symbols
added on demand.

> **Point-in-time replay since 2017.** Backtest dealer positioning (GEX, VRP,
> vanna/charm, max pain) at any minute since 2017-01-03, then trade the same
> endpoints live. No look-ahead, no training-serving skew. The Historical API
> is an **Alpha tier** capability.

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

## Data provenance: `data_as_of`

Every successful response carries `data_as_of`, reporting when each upstream feed last
delivered to the node that answered, plus `endpoint_version` identifying the deployment
that produced it.

```python
gex = fa.gex("SPY", at="2024-03-15T14:30:00Z")

gex["archive_as_of"]["equity_options_feed"]  # '2024-03-15T14:29:58.100Z'  the rows replayed
gex["archive_as_of"]["oi_feed"]              # '2024-03-14T20:00:00.000Z'  prior session's close
gex["data_as_of"]["equity_options_feed"]     # None - a replay node consumes no live feed
gex["endpoint_version"]                      # '2026.08.25'
```

`DataAsOf` and `ArchiveAsOf` are exported from the package root, so both objects are
typed rather than untyped passthroughs.

| Field | Feed | Expected cadence |
|---|---|---|
| `node` | Which node answered | Nodes hydrate independently |
| `equity_feed` | Equity and ETF spot quotes | seconds, during market hours |
| `equity_options_feed` | Equity and ETF option quotes | seconds, during market hours |
| `index_feed` | Index spot (SPX, NDX, RUT, VIX) | seconds, during market hours |
| `index_options_feed` | Index option quotes | seconds, during market hours |
| `futures_feed` | Futures prices | seconds, during the futures session |
| `futures_options_feed` | Futures option quotes | seconds, during the futures session |
| `flow_feed` | Classified options and stock trade tape | seconds, during market hours |
| `oi_feed` | Settled open interest | daily, dated to the prior 16:00 ET close |
| `macro_feed` | VIX, VVIX, SKEW, MOVE, SPX, Fear & Greed | minutes; reports its OLDEST component |

Historical responses carry a second object, `archive_as_of`, in the same shape: the
vintage of the archive rows actually replayed for the timestamp you requested. Its
`data_as_of` is all `null`, because a replay node reads the archive and consumes no
live feed.

`archive_as_of` is what makes an archive gap detectable. Request a moment with no row
and the query returns the most recent earlier row; nothing else in the response
distinguishes the two. Point-in-time work should read it and drop or flag observations
whose inputs precede the requested instant by more than the study tolerates.

### How to read it

- **Check the feeds your call depends on.** A GEX call on an equity is answered from
  `equity_feed`, `equity_options_feed` and `oi_feed`. `futures_feed` being `null` in that
  response says nothing about the answer.
- **Compare against the cadence, not the clock.** `oi_feed` at the previous session's
  close is correct: settled open interest is published once per session, so on a Monday
  the newest figure that exists is Friday's. An options feed an hour behind during the
  regular session is not correct.
- **`null` means "not seen on this node", not "broken".** A node that has never been
  asked for a futures symbol has never opened that feed.
- **Spot and options are separate on purpose.** They arrive over different pipes and can
  fail independently.
- **It evidences feed activity, not per-contract freshness.** An illiquid strike may not
  have quoted for hours while its feed is healthy.
- **`data_as_of` is not `as_of`.** `as_of` is response-generation time or the newest
  contract in the payload, depending on the endpoint. `data_as_of` describes the feeds
  behind it.

Endpoints returning a bare JSON array carry the same information in the
`X-Data-As-Of` and `X-Endpoint-Version` response headers.

Full reference: <https://flashalpha.com/docs/lab-api-overview#response-envelope> and the
methodology whitepaper at <https://flashalpha.com/methodology#freshness-reporting>.
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

## Get access

The Historical API requires the **Alpha tier ($1,499/mo)**: the only public source
of aggregate vanna/charm exposure and point-in-time replay since 2017.

Quant teams, prop desks, and vol funds:
**[flashalpha.com/for-quant-teams](https://flashalpha.com/for-quant-teams?utm_source=github&utm_medium=readme&utm_campaign=repo-flashalpha-historical-python)**
