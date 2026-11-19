"""Unit tests — mocked HTTP only. No live API hits."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import responses

from flashalpha_historical import (
    BASE_URL,
    AuthenticationError,
    ExpiryImpactResponse,
    FlashAlphaHistorical,
    FlashAlphaHistoricalError,
    InsufficientDataError,
    InvalidAtError,
    NoCoverageError,
    NoDataError,
    StrikeDependencyResponse,
    SymbolNotFoundError,
    TierRestrictedError,
)
from flashalpha_historical.client import _format_at, _format_number


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

# ── sell-window ─────────────────────────────────────────────────────


@responses.activate
def test_sell_window_sends_at_and_returns_the_answer():
    responses.get(
        f"{BASE_URL}/v1/strategies/sell-window/SPY",
        json={
            "symbol": "SPY",
            "session": "2026-10-16",
            "spot": 772.255,
            "quoted_at": "2026-10-16T13:35:00Z",
            "legs_indicative": False,
            "windows": [
                {
                    "expiry": "2026-10-23",
                    "days_to_expiry": 7,
                    "action": "sell",
                    "candidates": [
                        {
                            "structure": "short_put",
                            "exit": "expiry",
                            "legs": [{"side": "sell", "quantity": 1, "type": "put", "strike": 754, "delta": -0.098, "bid": 0.69, "ask": 0.7}],
                            "mid_credit": 0.695,
                        }
                    ],
                },
                {"action": "unavailable"},
            ],
        },
        status=200,
    )
    answer = FlashAlphaHistorical("KEY").sell_window("SPY", at="2026-10-16T09:35:00")
    assert answer["windows"][0]["candidates"][0]["mid_credit"] == 0.695
    assert "at=2026-10-16T09%3A35%3A00" in responses.calls[0].request.url


@responses.activate
def test_sell_window_invalid_at_raises():
    responses.get(
        f"{BASE_URL}/v1/strategies/sell-window/SPY",
        json={"error": "invalid_at", "message": "at is in the future."},
        status=400,
    )
    with pytest.raises(InvalidAtError):
        FlashAlphaHistorical("KEY").sell_window("SPY", at="2099-01-02T09:35:00")


# ── Expiry impact / strike dependency ───────────────────────────────
#
# Fixtures are real production responses captured 2026-11-19 (lists trimmed).

FIXTURES = Path(__file__).parent / "fixtures"
AT = "2026-10-09T15:55:00"
AT_QS = "at=2026-10-09T15%3A55%3A00"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@responses.activate
def test_expiry_impact_sends_at_expiry_and_limit_and_returns_every_level():
    responses.get(f"{BASE_URL}/v1/exposure/expiry-impact/SPY", json=_fixture("expiry_impact_historical.json"))

    result: ExpiryImpactResponse = FlashAlphaHistorical("KEY").expiry_impact(
        "SPY", at=AT, expiry="2026-10-09", limit=3
    )

    assert responses.calls[0].request.url == (
        f"{BASE_URL}/v1/exposure/expiry-impact/SPY?{AT_QS}&expiry=2026-10-09&limit=3"
    )
    assert result["selected_expiry"] == "2026-10-09"
    assert result["excluding_expiry"]["status"] == "available"
    assert result["impact"]["removed_gross_share_pct"] == pytest.approx(27.355976302706107)
    assert result["impact"]["largest_gross_reductions"][0]["strike"] == 778
    assert result["impact"]["strongest_remaining_concentrations"][1]["excluded_share_at_strike_pct"] < 1
    assert result["strikes"][2]["strike"] == 60
    assert result["facts"][0]["supporting_values"]["gross_share_pct"] == pytest.approx(27.355976302706107)
    assert result["reasons"][0]["code"] == "historical_model_reconstruction"
    assert result["pricing_basis"] == "historical_quote_repriced_dated_inputs"
    assert result["data_as_of"]["equity_feed"] is None
    assert result["archive_as_of"]["node"] == "f3"
    assert result["archive_as_of"]["oi_feed"] == "2026-10-08T20:00:00Z"


@responses.activate
def test_expiry_impact_omits_expiry_and_limit_when_not_given():
    responses.get(f"{BASE_URL}/v1/exposure/expiry-impact/SPY", json=_fixture("expiry_impact_historical.json"))
    FlashAlphaHistorical("KEY").expiry_impact("SPY", at=AT)
    assert responses.calls[0].request.url == f"{BASE_URL}/v1/exposure/expiry-impact/SPY?{AT_QS}"


@responses.activate
def test_strike_dependency_sends_at_and_a_fractional_strike_exactly():
    responses.get(f"{BASE_URL}/v1/exposure/strike-dependency/SPY", json=_fixture("strike_dependency_historical.json"))
    FlashAlphaHistorical("KEY").strike_dependency("SPY", at=AT, strike=672.5)
    assert responses.calls[0].request.url == (
        f"{BASE_URL}/v1/exposure/strike-dependency/SPY?{AT_QS}&strike=672.5"
    )


@responses.activate
def test_strike_dependency_returns_every_level():
    responses.get(f"{BASE_URL}/v1/exposure/strike-dependency/SPY", json=_fixture("strike_dependency_historical.json"))

    result: StrikeDependencyResponse = FlashAlphaHistorical("KEY").strike_dependency(
        "SPY", at=datetime(2026, 10, 9, 15, 55), strike=670
    )

    assert responses.calls[0].request.url == (
        f"{BASE_URL}/v1/exposure/strike-dependency/SPY?{AT_QS}&strike=670"
    )
    assert result["strike"] == 670
    assert result["by_expiry"][0]["valuation_cutoff_at"] == "2026-10-13T20:00:00Z"
    assert result["by_expiry"][0]["call_gex_usd"] == 0
    assert result["by_expiry"][2]["calendar_days_to_expiry"] == 6
    assert result["dominant_expiry"] == "2026-12-18"
    assert result["dominant_expiry_share_pct"] == pytest.approx(29.844720445178503)
    assert result["archive_as_of"]["node"] == "f3"


@pytest.mark.parametrize(
    "value,expected",
    [
        (672.5, "672.5"),
        (670, "670"),
        (670.0, "670.0"),
        (0.0000001, "0.0000001"),
        (1e16, "10000000000000000"),
        (Decimal("672.50"), "672.50"),
    ],
)
def test_strike_is_written_as_exact_decimal_text(value, expected):
    assert _format_number(value) == expected


@responses.activate
def test_expiry_impact_below_alpha_raises_tier_restricted():
    responses.get(
        f"{BASE_URL}/v1/exposure/expiry-impact/SPY",
        json={"error": "tier_restricted", "message": "Requires Alpha plan.", "current_plan": "Growth", "required_plan": "Alpha"},
        status=403,
    )
    with pytest.raises(TierRestrictedError) as exc_info:
        FlashAlphaHistorical("KEY").expiry_impact("SPY", at=AT)
    assert exc_info.value.required_plan == "Alpha"


@responses.activate
def test_strike_dependency_below_alpha_raises_tier_restricted():
    responses.get(
        f"{BASE_URL}/v1/exposure/strike-dependency/SPY",
        json={"error": "tier_restricted", "message": "Requires Alpha plan.", "current_plan": "Growth", "required_plan": "Alpha"},
        status=403,
    )
    with pytest.raises(TierRestrictedError):
        FlashAlphaHistorical("KEY").strike_dependency("SPY", at=AT, strike=670)


@responses.activate
def test_strike_dependency_unsupported_symbol_surfaces_the_422():
    responses.get(
        f"{BASE_URL}/v1/exposure/strike-dependency/AAPL", json=_fixture("error_unsupported_symbol.json"), status=422
    )
    with pytest.raises(FlashAlphaHistoricalError) as exc_info:
        FlashAlphaHistorical("KEY").strike_dependency("AAPL", at=AT, strike=200)
    assert exc_info.value.status_code == 422
    assert exc_info.value.response["error"] == "unsupported_symbol"
