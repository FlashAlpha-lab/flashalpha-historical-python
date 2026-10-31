"""Offline tests for flashalpha_backtest.py: a stub replaces the API, so no key or network is needed.

    pip install pytest requests
    pytest test_flashalpha_backtest.py
"""
import csv

import pytest

import flashalpha_backtest as bt


class StubData:
    """Three sessions of canned API responses. The put spread opens on day 2 and hits the profit target on day 3."""

    def __init__(self):
        self.calls = 0
        self.days = {"2024-03-04": ("positive_gamma", 2.0), "2024-03-05": ("positive_gamma", 2.0),
                     "2024-03-06": ("positive_gamma", 2.0)}
        # Marks per date for the two legs: (bid, ask)
        self.marks = {"2024-03-06": {("P", 490.0): (0.30, 0.34), ("P", 485.0): (0.10, 0.12)}}

    def stock_quote(self, symbol, at):
        day = at[:10]
        if day not in self.days:
            return {"mid": 500.0, "lastUpdate": "2024-02-29T16:00:00"}  # holiday: an earlier session's quote
        return {"mid": 500.0, "lastUpdate": at}

    def exposure_summary(self, symbol, at):
        return {"regime": self.days[at[:10]][0], "gamma_flip": 495.0, "exposures": {"net_gex": 1e9}}

    def vrp(self, symbol, at):
        return {"vrp": {"vrp_20d": self.days[at[:10]][1], "atm_iv": 14.0, "rv_20d": 12.0, "percentile": 60, "z_score": 0.5},
                "gex_conditioned": {"harvest_score": 70}}

    def chain(self, symbol, at, expiry):
        if expiry != "2024-04-05":
            return []
        return [
            {"type": "P", "strike": 490.0, "expiry": expiry, "bid": 1.00, "ask": 1.10, "mid": 1.05, "delta": -0.21},
            {"type": "P", "strike": 485.0, "expiry": expiry, "bid": 0.40, "ask": 0.46, "mid": 0.43, "delta": -0.12},
            {"type": "P", "strike": 480.0, "expiry": expiry, "bid": 0.20, "ask": 0.24, "mid": 0.22, "delta": -0.07},
            {"type": "C", "strike": 510.0, "expiry": expiry, "bid": 1.00, "ask": 1.10, "mid": 1.05, "delta": 0.20},
        ]

    def option(self, symbol, at, expiry, strike, opt_type):
        bid, ask = self.marks.get(at[:10], {}).get((opt_type, float(strike)), (None, None))
        if bid is None:
            return None
        return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2}


def test_fill_price_moves_from_mid_toward_the_far_side():
    q = {"bid": 1.00, "ask": 1.20}
    assert bt.fill_price(q, -1, 0.0) == pytest.approx(1.10)
    assert bt.fill_price(q, -1, 1.0) == pytest.approx(1.00)
    assert bt.fill_price(q, +1, 0.5) == pytest.approx(1.15)


def test_select_legs_builds_a_put_credit_spread():
    cfg = bt.Config()
    legs = bt.select_legs(StubData().chain("SPY", "2024-03-05T15:45:00", "2024-04-05"), {}, cfg)
    assert [(l["strike"], l["side"]) for l in legs] == [(490.0, -1), (485.0, +1)]


def test_run_opens_and_closes_one_trade_with_exact_accounting(tmp_path):
    cfg = bt.Config(start="2024-03-04", end="2024-03-06", min_dte=25, max_dte=40, target_dte=31)
    summary = bt.run(cfg, StubData(), tmp_path)
    trades = list(csv.DictReader((tmp_path / "trades.csv").open()))
    assert summary["trades"] == 1 and len(trades) == 1
    t = trades[0]
    # Entry on 03-05 (2 positive-gamma sessions, VRP > 0), halfway fills: sell 490 at 1.025, buy 485 at 0.445.
    # Credit = (1.025 - 0.445) * 100 - 2 legs * 0.65 = 56.70
    assert t["entry_date"] == "2024-03-05" and float(t["credit"]) == pytest.approx(56.70)
    # Day 3 mid value of the spread: 0.32 - 0.11 = 0.21 -> open profit 56.70 - 21 = 35.70 >= 50% of credit.
    # Close halfway: buy 490 at 0.33, sell 485 at 0.105 -> -22.50, less 1.30 commission: 56.70 - 22.50 - 1.30 = 32.90
    assert t["exit_reason"] == "profit_target" and float(t["pnl"]) == pytest.approx(32.90)
    assert t["legs"] == "-P490 +P485" and t["expiry"] == "2024-04-05"


def test_strike_text_keeps_every_digit():
    assert [bt.strike_text(x) for x in (512.0, 517.5, 21012.25)] == ["512", "517.5", "21012.25"]


def test_holidays_are_skipped(tmp_path):
    cfg = bt.Config(start="2024-03-01", end="2024-03-04")  # 03-01 returns an earlier quote, 03-02/03 are a weekend
    summary = bt.run(cfg, StubData(), tmp_path)
    assert summary["sessions"] == 1
