"""Unit tests — mocked HTTP only. No live API hits."""

from __future__ import annotations

from datetime import date, datetime

import pytest
import responses

from flashalpha_historical import (
    BASE_URL,
    AuthenticationError,
    FlashAlphaHistorical,
    InsufficientDataError,
    InvalidAtError,
    NoCoverageError,
    NoDataError,
    SymbolNotFoundError,
    TierRestrictedError,
)
from flashalpha_historical.client import _format_at


def test_format_at_string_passthrough():
    assert _format_at("2026-03-05T15:30:00") == "2026-03-05T15:30:00"
    assert _format_at("2026-03-05") == "2026-03-05"


def test_format_at_datetime():
    assert _format_at(datetime(2026, 3, 5, 15, 30)) == "2026-03-05T15:30:00"


def test_format_at_date():
    assert _format_at(date(2026, 3, 5)) == "2026-03-05"


def test_format_at_rejects_other_types():
    with pytest.raises(TypeError):
        _format_at(12345)  # type: ignore[arg-type]


def test_constructor_requires_api_key():
    with pytest.raises(ValueError):
        FlashAlphaHistorical("")


def test_x_api_key_header_set():
    client = FlashAlphaHistorical("KEY")
    assert client._session.headers["X-Api-Key"] == "KEY"


@responses.activate
def test_exposure_summary_round_trip():
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={"symbol": "SPY", "regime": "positive_gamma"},
        status=200,
    )
    client = FlashAlphaHistorical("KEY")
    out = client.exposure_summary("SPY", at="2026-03-05T15:30:00")
    assert out["regime"] == "positive_gamma"
    # ``at`` must have been forwarded as a query string
    assert "at=2026-03-05T15%3A30%3A00" in responses.calls[0].request.url


@responses.activate
def test_invalid_at_maps_to_typed_exception():
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={"error": "invalid_at", "message": "bad format"},
        status=400,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(InvalidAtError):
        client.exposure_summary("SPY", at="garbage")


@responses.activate
def test_403_tier_restricted_carries_plan():
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={
            "error": "tier_restricted",
            "current_plan": "Growth",
            "required_plan": "Alpha",
            "message": "needs Alpha",
        },
        status=403,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(TierRestrictedError) as exc_info:
        client.exposure_summary("SPY", at="2026-03-05")
    assert exc_info.value.current_plan == "Growth"
    assert exc_info.value.required_plan == "Alpha"


@responses.activate
def test_404_typed_no_data_vs_no_coverage():
    responses.get(
        f"{BASE_URL}/v1/tickers",
        json={"error": "no_coverage"},
        status=404,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(NoCoverageError):
        client.tickers(symbol="UNKNOWN")


@responses.activate
def test_404_no_data():
    responses.get(
        f"{BASE_URL}/v1/exposure/summary/SPY",
        json={"error": "no_data", "message": "outside coverage"},
        status=404,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(NoDataError):
        client.exposure_summary("SPY", at="2017-01-01")


@responses.activate
def test_404_insufficient_data_for_surface():
    responses.get(
        f"{BASE_URL}/v1/surface/SPY",
        json={"error": "insufficient_data"},
        status=404,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(InsufficientDataError):
        client.surface("SPY", at="2018-04-16")


@responses.activate
def test_404_symbol_not_found():
    responses.get(
        f"{BASE_URL}/v1/stockquote/UNKNOWN",
        json={"error": "symbol_not_found"},
        status=404,
    )
    client = FlashAlphaHistorical("KEY")
    with pytest.raises(SymbolNotFoundError):
        client.stock_quote("UNKNOWN", at="2024-01-02")


@responses.activate
def test_401_authentication_error():
    responses.get(
        f"{BASE_URL}/v1/tickers",
        body="",
        status=401,
    )
    client = FlashAlphaHistorical("BAD_KEY")
    with pytest.raises(AuthenticationError):
        client.tickers()


@responses.activate
def test_optionquote_passes_all_filters():
    responses.get(
        f"{BASE_URL}/v1/optionquote/SPY",
        json={"strike": 680, "type": "C"},
        status=200,
    )
    client = FlashAlphaHistorical("KEY")
    client.option_quote(
        "SPY",
        at="2026-03-05T15:30:00",
        expiry="2026-03-06",
        strike=680,
        type="C",
    )
    url = responses.calls[0].request.url
    assert "strike=680" in url
    assert "type=C" in url
    assert "expiry=2026-03-06" in url


@responses.activate
def test_at_accepts_datetime_object():
    responses.get(
        f"{BASE_URL}/v1/vrp/SPY",
        json={"symbol": "SPY"},
        status=200,
    )
    client = FlashAlphaHistorical("KEY")
    client.vrp("SPY", at=datetime(2025, 6, 18, 12, 0, 0))
    assert "at=2025-06-18T12%3A00%3A00" in responses.calls[0].request.url
