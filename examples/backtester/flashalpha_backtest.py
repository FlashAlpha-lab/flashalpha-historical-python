"""FlashAlpha options backtester: a complete, runnable template.

Replays the FlashAlpha Historical API day by day, decides entries and exits from the same endpoint outputs you
would read live, fills trades on real historical bid/ask quotes, and writes trades.csv and equity.csv.

Edit the three marked functions to change the strategy:
    entry_rules()  - when to open a position (reads FlashAlpha signals)
    select_legs()  - which option contracts to trade (reads the option chain)
    exit_rules()   - when to close (reads the position's marks and FlashAlpha signals)

Requirements: Python 3.10+, `pip install requests`. An Alpha plan or higher (Historical API).

    export FLASHALPHA_API_KEY=your_key
    python flashalpha_backtest.py --symbol SPY --start 2024-01-02 --end 2024-06-28

Every API response is cached in .fa_cache/, so a rerun with changed rules costs no API calls for days already fetched.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

BASE_URL = "https://historical.flashalpha.com"


# ============================================================================================================
# Settings
# ============================================================================================================
@dataclass
class Config:
    symbol: str = "SPY"
    start: str = "2024-01-02"
    end: str = "2024-06-28"
    decision_time: str = "15:45"   # ET; every decision and fill uses quotes at this minute
    # Trade selection (a put credit spread by default)
    target_dte: int = 35           # pick the expiry closest to this many calendar days out...
    min_dte: int = 25              # ...within this window
    max_dte: int = 50
    short_delta: float = 0.20      # sell the put closest to this absolute delta
    width: float = 5.0             # buy the put this many points lower
    contracts: int = 1
    max_positions: int = 1         # open positions allowed at once
    # Exits
    profit_target: float = 0.50    # close when 50% of the entry credit is captured
    stop_loss: float = 2.00        # close when the loss reaches 2x the entry credit
    exit_dte: int = 21             # close with this many calendar days left
    # Costs
    slippage: float = 0.5          # 0 = fill at mid, 1 = fill at the bid or ask, 0.5 = halfway
    commission: float = 0.65       # per contract per leg, each side


# ============================================================================================================
# FlashAlpha data: a small cached client for the Historical API
# ============================================================================================================
class FlashAlphaData:
    def __init__(self, api_key: str, cache_dir: str = ".fa_cache", base_url: str = BASE_URL):
        if not api_key:
            raise SystemExit("Set FLASHALPHA_API_KEY (Alpha plan or higher).")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers["X-Api-Key"] = api_key
        self.cache = Path(cache_dir)
        self.cache.mkdir(exist_ok=True)
        self.calls = 0

    def get(self, path: str, **params):
        """GET with a disk cache. Returns parsed JSON, or None when the API has no data (404)."""
        params = {k: v for k, v in params.items() if v is not None}
        key = hashlib.sha1(json.dumps([path, sorted(params.items())]).encode()).hexdigest()
        hit = self.cache / f"{key}.json"
        if hit.exists():
            return json.loads(hit.read_text())
        for attempt in range(5):
            try:
                r = self.session.get(self.base_url + path, params=params, timeout=60)
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(2 ** attempt)
                continue
            self.calls += 1
            if r.status_code == 200:
                data = r.json()
                break
            if r.status_code == 404:
                data = None
                break
            if r.status_code in (429, 500, 502, 503, 504):
                wait = r.headers.get("Retry-After", "")
                time.sleep(int(wait) if wait.isdigit() else 2 ** attempt)
                continue
            raise SystemExit(f"FlashAlpha API error {r.status_code} on {path}: {r.text[:200]}")
        else:
            raise SystemExit(f"FlashAlpha API kept failing on {path}")
        hit.write_text(json.dumps(data))
        return data

    def stock_quote(self, symbol, at):
        return self.get(f"/v1/stockquote/{symbol}", at=at)

    def exposure_summary(self, symbol, at):
        return self.get(f"/v1/exposure/summary/{symbol}", at=at)

    def vrp(self, symbol, at):
        return self.get(f"/v1/vrp/{symbol}", at=at)

    def chain(self, symbol, at, expiry):
        return self.get(f"/v1/optionquote/{symbol}", at=at, expiry=expiry) or []

    def option(self, symbol, at, expiry, strike, opt_type):
        return self.get(f"/v1/optionquote/{symbol}", at=at, expiry=expiry, strike=strike_text(strike), type=opt_type)


def strike_text(strike: float) -> str:
    """Strike as the API and the trade log write it: 512 -> "512", 517.5 -> "517.5", 21012.25 -> "21012.25"."""
    return format(strike, ".10g")


def build_snapshot(fa: FlashAlphaData, symbol: str, at: str) -> dict | None:
    """Everything the rules can read for one decision time, as one flat dict. Returns None on a non-trading day.

    Add fields from any other FlashAlpha endpoint here (exposure levels, narrative, max pain, 0DTE, surface...).
    """
    quote = fa.stock_quote(symbol, at)
    if not quote or not str(quote.get("lastUpdate", "")).startswith(at[:10]):
        return None  # weekend or market holiday: the archive returned an earlier session's quote
    ex = fa.exposure_summary(symbol, at) or {}
    v = fa.vrp(symbol, at) or {}
    core = v.get("vrp") or {}
    return {
        "date": at[:10],
        "at": at,
        "spot": quote["mid"],
        # /v1/exposure/summary
        "gamma_regime": ex.get("regime"),                 # "positive_gamma" or "negative_gamma"
        "net_gex": (ex.get("exposures") or {}).get("net_gex"),
        "gamma_flip": ex.get("gamma_flip"),
        # /v1/vrp
        "atm_iv": core.get("atm_iv"),                     # vol points
        "rv_20d": core.get("rv_20d"),
        "vrp_20d": core.get("vrp_20d"),                   # implied minus 20-day realized, vol points
        "vrp_percentile": core.get("percentile"),
        "vrp_z": core.get("z_score"),
        "harvest_score": (v.get("gex_conditioned") or {}).get("harvest_score"),
    }


# ============================================================================================================
# STRATEGY: edit these three functions
# ============================================================================================================
def entry_rules(snap: dict, history: list[dict], cfg: Config) -> bool:
    """ENTRY RULES. Return True to open a position at this decision time.

    snap is today's snapshot (see build_snapshot); history holds the earlier sessions' snapshots, oldest first.
    Default: implied vol above 20-day realized (VRP > 0) and dealers long gamma for 2 sessions running.
    """
    gamma_streak = [s["gamma_regime"] for s in (history[-1:] + [snap])]
    return (
        snap["vrp_20d"] is not None and snap["vrp_20d"] > 0
        and len(gamma_streak) == 2 and all(g == "positive_gamma" for g in gamma_streak)
    )


def select_legs(chain: list[dict], snap: dict, cfg: Config) -> list[dict] | None:
    """WHICH CONTRACTS. Return legs as dicts {type, strike, expiry, side}, side -1 = sell, +1 = buy.

    Default: put credit spread - sell the put closest to cfg.short_delta, buy the put cfg.width points lower.
    """
    puts = [o for o in chain if o["type"] == "P" and o.get("delta") is not None and (o.get("bid") or 0) > 0]
    if not puts:
        return None
    short = min(puts, key=lambda o: abs(abs(o["delta"]) - cfg.short_delta))
    lower = [o for o in puts if o["strike"] <= short["strike"] - cfg.width]
    if not lower:
        return None
    long = max(lower, key=lambda o: o["strike"])
    return [
        {"type": "P", "strike": short["strike"], "expiry": short["expiry"], "side": -1},
        {"type": "P", "strike": long["strike"], "expiry": long["expiry"], "side": +1},
    ]


def exit_rules(pos: "Position", snap: dict, history: list[dict], cfg: Config) -> str | None:
    """EXIT RULES. Return a reason string to close the position at this decision time, or None to hold.

    pos.pnl_mid is the open profit of the whole position in dollars at mid. pos.credit is the net premium taken in,
    after commission: positive for a credit, negative for a debit, so the targets below use its size.
    Default: take 50% of the credit, stop at 2x the credit, close at 21 days left, or close after 2 sessions
    of negative dealer gamma.
    """
    if pos.pnl_mid >= cfg.profit_target * abs(pos.credit):
        return "profit_target"
    if pos.pnl_mid <= -cfg.stop_loss * abs(pos.credit):
        return "stop_loss"
    if pos.dte(snap["date"]) <= cfg.exit_dte:
        return "time_exit"
    if history and history[-1]["gamma_regime"] == "negative_gamma" and snap["gamma_regime"] == "negative_gamma":
        return "negative_gamma_2_sessions"
    return None


# ============================================================================================================
# Engine (no changes needed below to run a new strategy)
# ============================================================================================================
@dataclass
class Position:
    legs: list[dict]
    entry_date: str
    credit: float                  # net premium for the whole position in dollars after commission (negative = debit)
    marks: dict = field(default_factory=dict)  # last quote per leg
    pnl_mid: float = 0.0

    @property
    def expiry(self) -> str:
        return min(leg["expiry"] for leg in self.legs)

    def dte(self, date: str) -> int:
        return (dt.date.fromisoformat(self.expiry) - dt.date.fromisoformat(date)).days


def fill_price(quote: dict, side: int, slippage: float) -> float:
    """Price for buying (side +1) or selling (side -1) one contract: mid moved toward the ask or bid."""
    mid = (quote["bid"] + quote["ask"]) / 2
    return mid + slippage * (quote["ask"] - mid) if side > 0 else mid - slippage * (mid - quote["bid"])


def find_expiry(fa: FlashAlphaData, symbol: str, at: str, cfg: Config) -> tuple[str, list] | None:
    """Expiry closest to cfg.target_dte inside [min_dte, max_dte] that has a chain (Friday, else Thursday)."""
    today = dt.date.fromisoformat(at[:10])
    fridays = [today + dt.timedelta(days=d) for d in range(cfg.min_dte, cfg.max_dte + 1)
               if (today + dt.timedelta(days=d)).weekday() == 4]
    for friday in sorted(fridays, key=lambda d: abs((d - today).days - cfg.target_dte)):
        for day in (friday, friday - dt.timedelta(days=1)):  # Thursday when the Friday is a holiday
            chain = fa.chain(symbol, at, day.isoformat())
            if chain:
                return day.isoformat(), chain
    return None


def trading_days(start: str, end: str):
    day, stop = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    while day <= stop:
        if day.weekday() < 5:
            yield day.isoformat()
        day += dt.timedelta(days=1)


def run(cfg: Config, fa: FlashAlphaData, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    open_positions: list[Position] = []
    trades, equity, history = [], [], []
    realized = 0.0
    for date in trading_days(cfg.start, cfg.end):
        at = f"{date}T{cfg.decision_time}:00"
        snap = build_snapshot(fa, cfg.symbol, at)
        if snap is None:
            continue

        # 1. Mark and exit open positions
        for pos in list(open_positions):
            value_mid = 0.0
            on_expiry = pos.dte(date) <= 0  # expiry day, or the first session after it when that day had no data
            for i, leg in enumerate(pos.legs):
                q = None if on_expiry else fa.option(cfg.symbol, at, leg["expiry"], leg["strike"], leg["type"])
                if q and q.get("bid") is not None and q.get("ask") is not None and q["ask"] > 0:
                    pos.marks[i] = q
                mid = (pos.marks[i]["bid"] + pos.marks[i]["ask"]) / 2
                value_mid += leg["side"] * mid * 100 * cfg.contracts
            pos.pnl_mid = pos.credit + value_mid  # credit received plus the (negative) value of what we hold
            reason = "expiry" if on_expiry else exit_rules(pos, snap, history, cfg)
            if reason:
                if on_expiry:  # settle at intrinsic value against the spot at the decision time
                    close_value = sum(leg["side"] * max(0.0, (leg["strike"] - snap["spot"]) if leg["type"] == "P"
                                                        else (snap["spot"] - leg["strike"])) for leg in pos.legs)
                else:
                    close_value = sum(leg["side"] * fill_price(pos.marks[i], -leg["side"], cfg.slippage)
                                      for i, leg in enumerate(pos.legs))
                costs = 0.0 if on_expiry else cfg.commission * len(pos.legs) * cfg.contracts
                pnl = pos.credit + close_value * 100 * cfg.contracts - costs
                realized += pnl
                open_positions.remove(pos)
                trades.append({"entry_date": pos.entry_date, "exit_date": date, "expiry": pos.expiry,
                               "legs": " ".join(f"{'+' if l['side'] > 0 else '-'}{l['type']}{strike_text(l['strike'])}" for l in pos.legs),
                               "credit": round(pos.credit, 2), "pnl": round(pnl, 2), "exit_reason": reason,
                               "days_held": (dt.date.fromisoformat(date) - dt.date.fromisoformat(pos.entry_date)).days})

        # 2. Entries
        if len(open_positions) < cfg.max_positions and entry_rules(snap, history, cfg):
            found = find_expiry(fa, cfg.symbol, at, cfg)
            legs = select_legs(found[1], snap, cfg) if found else None
            if legs:
                by_key = {(o["type"], o["strike"], o["expiry"]): o for o in found[1]}
                missing = [leg for leg in legs if (leg["type"], leg["strike"], leg["expiry"]) not in by_key]
                if missing:
                    raise RuntimeError(f"select_legs must pick contracts from the chain it receives: {missing}")
                quotes = {i: by_key[(leg["type"], leg["strike"], leg["expiry"])] for i, leg in enumerate(legs)}
                open_value = sum(leg["side"] * fill_price(quotes[i], leg["side"], cfg.slippage) for i, leg in enumerate(legs))
                credit = -open_value * 100 * cfg.contracts - cfg.commission * len(legs) * cfg.contracts
                pos = Position(legs=legs, entry_date=date, credit=credit, marks=quotes)
                pos.pnl_mid = credit + sum(leg["side"] * (quotes[i]["bid"] + quotes[i]["ask"]) / 2
                                           for i, leg in enumerate(legs)) * 100 * cfg.contracts
                open_positions.append(pos)

        unrealized = sum((p.pnl_mid for p in open_positions), 0.0)
        equity.append({"date": date, "realized": round(realized, 2), "unrealized": round(unrealized, 2),
                       "equity": round(realized + unrealized, 2), "open_positions": len(open_positions),
                       "gamma_regime": snap["gamma_regime"], "vrp_20d": snap["vrp_20d"]})
        history.append(snap)

    write_csv(out_dir / "trades.csv", trades)
    write_csv(out_dir / "equity.csv", equity)
    return summarize(trades, equity)


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def summarize(trades: list[dict], equity: list[dict]) -> dict:
    pnls = [t["pnl"] for t in trades]
    curve = [e["equity"] for e in equity]
    daily = [b - a for a, b in zip([0.0] + curve[:-1], curve)]
    sd = (sum((x - sum(daily) / len(daily)) ** 2 for x in daily) / (len(daily) - 1)) ** 0.5 if len(daily) > 1 else 0
    peak, max_dd = 0.0, 0.0
    for v in curve:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]  # break-even trades count as losses
    reasons = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    return {
        "sessions": len(equity),
        "trades": len(trades),
        "win_rate": round(len(wins) / len(pnls), 3) if pnls else None,
        "total_pnl": round(sum(pnls, 0.0), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "max_drawdown": round(max_dd, 2),
        "sharpe": round(sum(daily) / len(daily) / sd * math.sqrt(252), 2) if sd > 0 else None,
        "exit_reasons": reasons,
        "open_at_end": equity[-1]["open_positions"] if equity else 0,
    }


def main():
    p = argparse.ArgumentParser(description="FlashAlpha options backtester")
    for name, value in vars(Config()).items():
        p.add_argument(f"--{name.replace('_', '-')}", type=type(value), default=value)
    p.add_argument("--out", default="results")
    p.add_argument("--cache", default=".fa_cache")
    args = vars(p.parse_args())
    out, cache = Path(args.pop("out")), args.pop("cache")
    cfg = Config(**args)
    fa = FlashAlphaData(os.environ.get("FLASHALPHA_API_KEY", ""), cache_dir=cache)
    summary = run(cfg, fa, out)
    print(json.dumps(summary, indent=2))
    print(f"API calls this run: {fa.calls}. Trades: {out / 'trades.csv'}. Equity: {out / 'equity.csv'}")


if __name__ == "__main__":
    main()
