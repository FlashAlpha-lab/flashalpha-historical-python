"""Replay / backtester tests — fully mocked."""

from __future__ import annotations

from datetime import date, datetime

import pytest
import responses

from flashalpha_historical import (
    BASE_URL,
    Backtester,
    FlashAlphaHistorical,
    is_trading_day,
    iter_days,
    iter_minutes,
    replay,
)


def test_is_trading_day_weekday_vs_weekend():
    assert is_trading_day(date(2024, 1, 2)) is True   # Tuesday
    assert is_trading_day(date(2024, 1, 6)) is False  # Saturday
    assert is_trading_day(date(2024, 1, 7)) is False  # Sunday


def test_is_trading_day_known_holidays():
    assert is_trading_day(date(2024, 1, 1)) is False     # New Year
    assert is_trading_day(date(2024, 12, 25)) is False   # Christmas
    assert is_trading_day(date(2024, 7, 4)) is False     # July 4


def test_iter_days_skips_weekends_and_holidays():
    days = list(iter_days("2024-01-01", "2024-01-08"))
    # Jan 1 is a holiday, Jan 6/7 weekend
    assert [d.date() for d in days] == [
        date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5),
        date(2024, 1, 8),
    ]
    # Default close stamp is 16:00
    assert all(d.hour == 16 and d.minute == 0 for d in days)


def test_iter_minutes_default_390_per_day():
    minutes = list(iter_minutes("2024-01-02", "2024-01-02"))
    assert len(minutes) == 391  # 9:30 → 16:00 inclusive at 1m
    assert minutes[0] == datetime(2024, 1, 2, 9, 30)
    assert minutes[-1] == datetime(2024, 1, 2, 16, 0)


def test_iter_minutes_step():
    minutes = list(iter_minutes("2024-01-02", "2024-01-02", step_minutes=30))
    # 9:30, 10:00, 10:30 ... 16:00 = 14 stamps
    assert len(minutes) == 14


def test_iter_minutes_rejects_bad_step():
    with pytest.raises(ValueError):
        list(iter_minutes("2024-01-02", "2024-01-02", step_minutes=0))


def test_iter_days_custom_calendar():
    custom = [date(2024, 1, 1), date(2024, 1, 8)]  # ignore default holidays
    days = list(iter_days("2024-01-01", "2024-01-08", trade_days=custom))
    assert [d.date() for d in days] == custom


@responses.activate
def test_replay_yields_at_string_and_response():
    for d in ("2024-01-02", "2024-01-03"):
        responses.get(
            f"{BASE_URL}/v1/exposure/summary/SPY",
            json={"as_of": f"{d}T16:00:00", "regime": "positive_gamma"},
            status=200,
        )

    client = FlashAlphaHistorical("KEY")
    out = list(replay(client, "exposure_summary", "SPY",
                      iter_days("2024-01-02", "2024-01-03")))
    assert len(out) == 2
    assert out[0][0] == "2024-01-02T16:00:00"
    assert out[1][1]["regime"] == "positive_gamma"


@responses.activate
def test_replay_skips_no_data_when_skip_missing_true():
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={"regime": "positive_gamma"},
        status=200,
    )
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={"error": "no_data"},
        status=404,
    )
    client = FlashAlphaHistorical("KEY")
    errors: list = []
    out = list(
        replay(
            client, "exposure_summary", "SPY",
            ["2024-01-02", "2024-01-03"],
            on_error=lambda at, exc: errors.append((at, exc)),
        )
    )
    assert len(out) == 1
    assert len(errors) == 1
    assert errors[0][0] == "2024-01-03"


@responses.activate
def test_replay_propagates_when_skip_missing_false():
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={"error": "no_data"},
        status=404,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(Exception):
        list(replay(client, "exposure_summary", "SPY",
                    ["2024-01-02"], skip_missing=False))


def test_replay_rejects_unknown_method():
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(ValueError):
        list(replay(client, "tickers", "SPY", ["2024-01-02"]))


@responses.activate
def test_backtester_collects_strategy_outputs():
    responses.get(
        f"{BASE_URL}/v1/stock/SPY/summary",
        json={
            "as_of": "2024-01-02T16:00:00",
            "price": {"mid": 470.5},
            "exposure": {"regime": "positive_gamma"},
            "volatility": {"vrp": 6.7, "atm_iv": 14.0},
        },
        status=200,
    )

    client = FlashAlphaHistorical("KEY")

    def strat(at, snap):
        return {"signal": "go" if snap["volatility"]["vrp"] > 5 else None}

    bt = Backtester(client, method="stock_summary", symbol="SPY")
    results = bt.run(["2024-01-02"], strat)
    assert len(results) == 1
    assert results[0].output == {"signal": "go"}
    rec = bt.to_records(results)[0]
    assert rec["at"] == "2024-01-02"
    assert rec["signal"] == "go"
    assert rec["underlying_price"] == 470.5
