# FlashAlpha options backtester (Python)

A complete options backtester in one file. It replays the FlashAlpha Historical API day by day, decides entries and
exits from the same endpoint outputs you would read live (dealer gamma, the volatility risk premium, implied and
realized vol), fills trades at real historical bid and ask quotes, and writes every trade to CSV.

Guide: [How to Backtest Options Strategies in Python](https://flashalpha.com/articles/how-to-backtest-options-strategies-python-flashalpha-historical-api)

The same backtester exists in [JavaScript](https://github.com/FlashAlpha-lab/flashalpha-historical-js/tree/main/examples/backtester),
[Go](https://github.com/FlashAlpha-lab/flashalpha-historical-go/tree/main/examples/backtester),
[Java](https://github.com/FlashAlpha-lab/flashalpha-historical-java/tree/main/examples/backtester) and
[C#](https://github.com/FlashAlpha-lab/flashalpha-historical-dotnet/tree/main/examples/backtester). Every version
produces the same trades and equity curve.

## Run it

Needs Python 3.10+, `requests`, and a FlashAlpha API key on the Alpha plan or higher.

```bash
pip install requests
export FLASHALPHA_API_KEY=your_key      # PowerShell: $env:FLASHALPHA_API_KEY="your_key"
python flashalpha_backtest.py --symbol SPY --start 2024-01-02 --end 2024-06-28
```

Results go to `results/trades.csv` (one row per closed trade) and `results/equity.csv` (one row per session).
Every API response is cached in `.fa_cache/`, so rerunning with changed rules uses no API calls for days already
fetched. Every setting in `Config` is also a flag, for example `--short-delta 0.16 --width 10 --max-positions 3`.

## Where to put your rules

Edit the three functions in the STRATEGY section:

| Function | What it decides | What it reads |
|---|---|---|
| `entry_rules(snap, history, cfg)` | Open a position today? | Today's FlashAlpha snapshot and earlier sessions' |
| `select_legs(chain, snap, cfg)` | Which contracts to trade | The option chain for the chosen expiry, with bid, ask and delta |
| `exit_rules(pos, snap, history, cfg)` | Close an open position? | The position's profit at mid and the snapshots |

The snapshot (`build_snapshot`) holds `spot`, `gamma_regime`, `net_gex`, `gamma_flip` (from `/v1/exposure/summary`)
and `atm_iv`, `rv_20d`, `vrp_20d`, `vrp_percentile`, `vrp_z`, `harvest_score` (from `/v1/vrp`). Add any other
historical endpoint there.

Defaults: a 5-point put credit spread at 0.20 delta, about 35 days out, opened when VRP is above 0 and dealer gamma
has been positive for 2 sessions; closed at 50% of the credit, a loss of 2x the credit, 21 days left, or 2 sessions of
negative gamma. Fills are halfway between mid and the bid or ask, plus $0.65 per contract per leg per side.

## Tested

`test_flashalpha_backtest.py` checks the fill math, leg selection and the trade accounting offline, with a stub in
place of the API:

```bash
pip install pytest requests
pytest test_flashalpha_backtest.py
```

Against the live API, these two windows are the reference every language version reproduces exactly:

| Command | Sessions | Trades | Total P&L | Max drawdown | Sharpe |
|---|---|---|---|---|---|
| `--start 2024-01-02 --end 2024-06-28` | 124 | 2 | 58.30 | 35.50 | 1.52 |
| `--start 2024-07-01 --end 2024-12-31 --max-positions 2` | 128 | 5 | -12.25 | 69.45 | -0.24 |

The default rules are a starting point, not a recommendation: they roughly broke even on SPY from 2022 to 2026.
