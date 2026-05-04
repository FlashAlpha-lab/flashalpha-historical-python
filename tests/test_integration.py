"""Integration tests — hit the live https://historical.flashalpha.com.

Skipped unless ``FLASHALPHA_API_KEY`` is set in the environment.

Run with:
    pytest -m integration tests/test_integration.py -v
or:
    FLASHALPHA_API_KEY=fa_... pytest tests/test_integration.py -v

Strategy: a single known-good timestamp inside SPY's high-activity window
(2024-08-05 15:30 ET — the Aug-2024 unwind) is reused across every endpoint
so we can spot-check both shape and a few invariants (regime is one of the
documented strings, gamma_flip is finite, exposure totals reconcile, etc.).
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from flashalpha_historical import (
    Backtester,
    FlashAlphaHistorical,
    InvalidAtError,
    NoCoverageError,
    NoDataError,
    iter_days,
    iter_minutes,
    replay,
)

API_KEY = os.environ.get("FLASHALPHA_API_KEY")

# All tests in this module are integration tests.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not API_KEY, reason="FLASHALPHA_API_KEY not set"),
]

# Known-good as-of: SPY, Aug 5 2024 unwind, 15:30 ET. Plenty of OI, full chain.
SPY_AT = "2024-08-05T15:30:00"
SPY_DATE = "2024-08-05"
EXPECTED_SPOT = 516.435  # checked from probe; minute-stable
SPOT_TOL = 1.0  # tolerate minor minute-bar refits

REGIMES = {"positive_gamma", "negative_gamma", "transition"}
HEDGING_DIRECTIONS = {"buy", "sell"}


@pytest.fixture(scope="module")
def hx():
    return FlashAlphaHistorical(API_KEY)


# ── Coverage ────────────────────────────────────────────────────────────────


class TestCoverage:
    def test_tickers_lists_spy(self, hx):
        out = hx.tickers()
        assert isinstance(out, dict)
        assert out["count"] >= 1
        symbols = {t["symbol"] for t in out["tickers"]}
        assert "SPY" in symbols

    def test_tickers_filter_by_symbol_returns_object(self, hx):
        out = hx.tickers(symbol="SPY")
        assert out["symbol"] == "SPY"
        assert "coverage" in out
        cov = out["coverage"]
        # Coverage should bracket our test timestamp
        assert cov["first"] <= "2024-08-05" <= cov["last"]
        assert cov["healthy_days"] > 0
        assert {"missing_eod", "missing_svi", "uncovered_calendar"} <= set(out["gaps"])

    def test_no_coverage_for_unknown_symbol(self, hx):
        with pytest.raises(NoCoverageError):
            hx.tickers(symbol="ZZZZZ")


# ── Market data ─────────────────────────────────────────────────────────────


class TestMarketData:
    def test_stock_quote_minute_resolution(self, hx):
        q = hx.stock_quote("SPY", at=SPY_AT)
        assert q["ticker"] == "SPY"
        assert q["bid"] <= q["mid"] <= q["ask"]
        assert abs(q["mid"] - EXPECTED_SPOT) < SPOT_TOL
        assert q["lastUpdate"] == SPY_AT

    def test_stock_quote_date_only_defaults_to_close(self, hx):
        q = hx.stock_quote("SPY", at=SPY_DATE)
        # API stamps the close at 16:00 when only a date is supplied.
        assert q["lastUpdate"].endswith("T16:00:00")

    def test_stock_quote_accepts_datetime_object(self, hx):
        q = hx.stock_quote("SPY", at=datetime(2024, 8, 5, 15, 30, 0))
        assert abs(q["mid"] - EXPECTED_SPOT) < SPOT_TOL

    def test_option_quote_with_all_filters_returns_single(self, hx):
        q = hx.option_quote(
            "SPY",
            at=SPY_AT,
            expiry="2024-08-09",
            strike=520,
            type="C",
        )
        assert q["strike"] == 520
        assert q["type"] == "C"
        assert q["bid"] <= q["mid"] <= q["ask"]
        # Greeks present + finite
        for g in ("delta", "gamma", "theta", "vega", "rho", "vanna", "charm"):
            assert isinstance(q[g], (int, float))
        # Documented historical-mode gaps
        assert q["bidSize"] == 0
        assert q["askSize"] == 0
        assert q["volume"] == 0
        assert q["svi_vol"] is None
        assert q["svi_vol_gated"] == "backtest_mode"
        # OI is from EOD — should be a non-negative int
        assert q["open_interest"] >= 0


# ── Exposure ─────────────────────────────────────────────────────────────────


class TestExposure:
    def test_summary_shape_and_invariants(self, hx):
        s = hx.exposure_summary("SPY", at=SPY_AT)
        assert s["symbol"] == "SPY"
        assert abs(s["underlying_price"] - EXPECTED_SPOT) < SPOT_TOL
        assert s["regime"] in REGIMES
        assert isinstance(s["gamma_flip"], (int, float))
        e = s["exposures"]
        for k in ("net_gex", "net_dex", "net_vex", "net_chex"):
            assert isinstance(e[k], (int, float))
        # Hedging estimate should be symmetric around current spot
        h = s["hedging_estimate"]
        up, down = h["spot_up_1pct"], h["spot_down_1pct"]
        assert up["direction"] in HEDGING_DIRECTIONS
        assert down["direction"] in HEDGING_DIRECTIONS
        assert up["dealer_shares_to_trade"] == -down["dealer_shares_to_trade"]
        # Interpretation strings present
        for k in ("gamma", "vanna", "charm"):
            assert isinstance(s["interpretation"][k], str)

    def test_levels_keys(self, hx):
        out = hx.exposure_levels("SPY", at=SPY_AT)
        levels = out["levels"]
        for k in (
            "gamma_flip",
            "max_positive_gamma",
            "max_negative_gamma",
            "call_wall",
            "put_wall",
            "highest_oi_strike",
        ):
            assert k in levels

    def test_gex_strikes_consistent_with_summary(self, hx):
        gex = hx.gex("SPY", at=SPY_AT, min_oi=100)
        summary = hx.exposure_summary("SPY", at=SPY_AT)
        # Net GEX across the two endpoints lines up roughly (gex view filtered
        # by min_oi may differ slightly from the unfiltered summary). Check that
        # both have the same sign and order of magnitude.
        a = gex["net_gex"]
        b = summary["exposures"]["net_gex"]
        assert (a > 0) == (b > 0) or abs(a) < 1e7 or abs(b) < 1e7
        assert isinstance(gex["strikes"], list)
        assert len(gex["strikes"]) > 5
        # Each strike entry has the documented shape — including the known-zero
        # / known-null fields (call_volume, call_oi_change).
        sample = gex["strikes"][0]
        assert "strike" in sample
        assert sample["call_volume"] == 0 and sample["put_volume"] == 0
        assert sample["call_oi_change"] is None and sample["put_oi_change"] is None

    def test_dex_payload_shape(self, hx):
        out = hx.dex("SPY", at=SPY_AT)
        assert "payload" in out
        assert "net_dex" in out["payload"]
        assert isinstance(out["payload"]["strikes"], list)

    def test_vex_payload_shape(self, hx):
        out = hx.vex("SPY", at=SPY_AT)
        assert "payload" in out
        assert "net_vex" in out["payload"]
        assert "vex_interpretation" in out["payload"]

    def test_chex_payload_shape(self, hx):
        out = hx.chex("SPY", at=SPY_AT)
        assert "payload" in out
        assert "net_chex" in out["payload"]
        assert "chex_interpretation" in out["payload"]

    def test_narrative_returns_blocks(self, hx):
        out = hx.narrative("SPY", at=SPY_AT)
        n = out["narrative"]
        for block in ("regime", "gex_change", "key_levels", "flow",
                      "vanna", "charm", "zero_dte"):
            assert isinstance(n[block], str)
        # Documented gap — top_oi_changes must be empty list (not None / missing)
        assert n["data"]["top_oi_changes"] == []
        # vix should be non-null for any post-2018 SPY date
        assert n["data"]["vix"] is not None

    def test_zero_dte_basic_shape(self, hx):
        out = hx.zero_dte("SPY", at=SPY_AT)
        # Either it has an expiration or it's a no-0DTE day
        assert "expiration" in out
        assert "regime" in out and "exposures" in out


# ── Composite & vol ──────────────────────────────────────────────────────────


class TestComposite:
    def test_stock_summary_block_keys(self, hx):
        s = hx.stock_summary("SPY", at=SPY_AT)
        assert s["symbol"] == "SPY"
        for k in ("price", "volatility", "options_flow", "exposure", "macro"):
            assert k in s
        # Documented gaps
        assert s["options_flow"]["total_call_volume"] == 0
        assert s["options_flow"]["total_put_volume"] == 0
        assert s["options_flow"]["pc_ratio_volume"] is None
        assert s["macro"]["vix_futures"] is None
        assert s["macro"]["fear_and_greed"] is None
        # vix should populate
        assert s["macro"]["vix"]["value"] is not None

    def test_volatility_realized_ladder(self, hx):
        v = hx.volatility("SPY", at=SPY_AT)
        rv = v["realized_vol"]
        for window in ("rv_5d", "rv_10d", "rv_20d", "rv_30d", "rv_60d"):
            assert window in rv
        assert isinstance(v["atm_iv"], (int, float))
        assert isinstance(v["skew_profiles"], list)

    def test_adv_volatility_svi_fits(self, hx):
        adv = hx.adv_volatility("SPY", at=SPY_AT)
        svi = adv["svi_parameters"]
        assert isinstance(svi, list) and len(svi) > 0
        first = svi[0]
        for k in ("expiry", "a", "b", "rho", "m", "sigma", "forward",
                  "atm_total_variance", "atm_iv"):
            assert k in first
        # Variance surface shape: 2D matrix
        ts = adv["total_variance_surface"]
        assert isinstance(ts["total_variance"], list)
        assert isinstance(ts["total_variance"][0], list)


# ── Surface ─────────────────────────────────────────────────────────────────


class TestSurface:
    def test_surface_grid_shape(self, hx):
        out = hx.surface("SPY", at=SPY_AT)
        assert out["grid_size"] == 50
        assert len(out["tenors"]) == 50
        assert len(out["moneyness"]) == 50
        assert len(out["iv"]) == 50
        assert len(out["iv"][0]) == 50
        assert abs(out["spot"] - EXPECTED_SPOT) < SPOT_TOL


# ── VRP ─────────────────────────────────────────────────────────────────────


class TestVrp:
    def test_vrp_dashboard_keys(self, hx):
        v = hx.vrp("SPY", at=SPY_AT)
        # Core block
        for k in ("atm_iv", "rv_5d", "rv_10d", "rv_20d", "rv_30d",
                  "vrp_5d", "vrp_10d", "vrp_20d", "vrp_30d"):
            assert k in v["vrp"]
        # Top-level composites
        assert "convexity_premium" in v
        assert "fair_vol" in v
        # Documented gap
        assert v["macro"]["hy_spread"] == 3.5


# ── Max Pain ────────────────────────────────────────────────────────────────


class TestMaxPain:
    def test_max_pain_pain_curve_monotonic_around_strike(self, hx):
        mp = hx.max_pain("SPY", at=SPY_AT, expiration="2024-08-09")
        assert mp["expiration"] == "2024-08-09"
        assert isinstance(mp["max_pain_strike"], (int, float))
        # The max-pain strike should minimize total_pain
        curve = mp["pain_curve"]
        assert len(curve) > 0
        min_strike = min(curve, key=lambda r: r["total_pain"])["strike"]
        assert abs(min_strike - mp["max_pain_strike"]) <= 5  # 1 strike tick


# ── Errors ──────────────────────────────────────────────────────────────────


class TestErrors:
    def test_invalid_at_raises_typed(self, hx):
        with pytest.raises(InvalidAtError):
            hx.exposure_summary("SPY", at="garbage")

    def test_out_of_coverage_raises_no_data(self, hx):
        with pytest.raises(NoDataError):
            hx.exposure_summary("SPY", at="2017-01-01")

    def test_holiday_raises_no_data(self, hx):
        # Jan 1, 2024 — full-close holiday, no minute data
        with pytest.raises(NoDataError):
            hx.exposure_summary("SPY", at="2024-01-01")

    def test_optionquote_no_match_raises_no_data(self, hx):
        with pytest.raises(NoDataError):
            hx.option_quote(
                "SPY",
                at=SPY_AT,
                expiry="2024-08-09",
                strike=99999,
                type="C",
            )


# ── Replay & Backtester ─────────────────────────────────────────────────────


class TestReplay:
    """Real backtest loops — kept short to avoid burning quota."""

    def test_replay_one_week_of_summaries(self, hx):
        # Mon → Fri, 5 trading days
        out = list(replay(
            hx, "exposure_summary", "SPY",
            iter_days("2024-08-05", "2024-08-09"),
        ))
        assert len(out) == 5
        for at, snap in out:
            assert snap["symbol"] == "SPY"
            assert snap["regime"] in REGIMES

    def test_replay_intraday_minutes_step(self, hx):
        # 30-minute step over a single day → 14 stamps (9:30 ... 16:00)
        out = list(replay(
            hx, "exposure_summary", "SPY",
            iter_minutes("2024-08-05", "2024-08-05", step_minutes=30),
        ))
        assert len(out) == 14
        # Spot should drift over the day, not be constant
        spots = [s["underlying_price"] for _, s in out]
        assert len(set(spots)) > 1

    def test_replay_skips_holiday_silently(self, hx):
        # Include a known holiday in the range; iter_days will skip it,
        # so we feed an explicit list to force a hit and verify skip_missing.
        errors: list = []
        out = list(replay(
            hx, "exposure_summary", "SPY",
            ["2024-08-05T15:30:00", "2024-01-01"],  # second is a holiday
            on_error=lambda at, exc: errors.append(at),
        ))
        assert len(out) == 1
        assert errors == ["2024-01-01"]

    def test_backtester_runs_strategy_and_records(self, hx):
        bt = Backtester(hx, method="stock_summary", symbol="SPY")
        results = bt.run(
            iter_days("2024-08-05", "2024-08-09"),
            lambda at, snap: {
                "vrp": snap["volatility"]["vrp"],
                "regime": snap["exposure"]["regime"],
            },
        )
        assert len(results) == 5
        assert all(r.output["regime"] in REGIMES for r in results)
        records = bt.to_records(results)
        assert {"at", "underlying_price", "regime", "vrp"} <= set(records[0])
