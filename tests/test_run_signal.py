import numpy as np
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

from run_signal import (
    build_live_frame,
    build_intraday_snapshot,
    calculate_holding_days,
    compute_signals,
    parse_sina_quote,
    prepare_confirmed_data,
    resolve_run_phase,
    select_confirmed_history,
)


def test_holding_days_uses_calendar_day_difference():
    assert calculate_holding_days(pd.Timestamp("2026-06-18"), pd.Timestamp("2026-07-08")) == 20


def test_holding_days_handles_year_boundary():
    assert calculate_holding_days("2025-12-31", "2026-01-02") == 2


def test_holding_days_allows_same_day_trade():
    assert calculate_holding_days("2026-07-20", "2026-07-20") == 0


def make_daily_frame(closes):
    dates = pd.bdate_range("2026-05-18", periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": np.arange(len(closes)) + 1,
        }
    )


def make_quote(price, date="2026-07-20", time="10:00:01"):
    return {
        "name": "科创综指",
        "open": 100.0,
        "previous_close": 100.0,
        "price": float(price),
        "high": max(100.0, float(price)),
        "low": min(100.0, float(price)),
        "volume": 123456,
        "date": date,
        "time": time,
        "source": "sina_realtime",
    }


def test_parse_sina_quote_extracts_realtime_fields():
    payload = (
        'var hq_str_sh000680="科创综指,1988.4950,1938.7662,1997.1692,'
        '1998.9734,1960.8488,0,0,8612030,62676531772,0,0,0,0,0,0,0,'
        '0,0,0,0,0,0,0,0,0,0,0,0,0,2026-07-20,09:38:39,00,";'
    )

    quote = parse_sina_quote(payload)

    assert quote["name"] == "科创综指"
    assert quote["open"] == 1988.495
    assert quote["previous_close"] == 1938.7662
    assert quote["price"] == 1997.1692
    assert quote["high"] == 1998.9734
    assert quote["low"] == 1960.8488
    assert quote["date"] == "2026-07-20"
    assert quote["time"] == "09:38:39"


def test_intraday_snapshot_marks_estimated_buy_without_mutating_history():
    frame = make_daily_frame([100.0] * 40)
    original = frame.copy(deep=True)

    snapshot = build_intraday_snapshot(
        frame,
        make_quote(110),
        {"cash": 1_000_000.0, "shares": 0, "first_close": 100.0},
    )

    pd.testing.assert_frame_equal(frame, original)
    assert snapshot["is_estimated"] is True
    assert snapshot["signal_type"] == "buy"
    assert snapshot["signal_label"] == "预估买入信号"
    assert snapshot["strategy_nav"] == 1.0
    assert snapshot["benchmark_nav"] == 1.1


def test_intraday_snapshot_marks_estimated_sell_and_values_long_position():
    frame = make_daily_frame(list(np.linspace(100, 140, 40)))

    snapshot = build_intraday_snapshot(
        frame,
        make_quote(50),
        {"cash": 100_000.0, "shares": 10_000, "first_close": 100.0},
    )

    assert snapshot["signal_type"] == "sell"
    assert snapshot["signal_label"] == "预估卖出信号"
    assert snapshot["position"] == "long"
    assert snapshot["strategy_nav"] == 0.6
    assert snapshot["benchmark_nav"] == 0.5


def test_explicit_run_phases_are_stable():
    assert resolve_run_phase("intraday") == "intraday"
    assert resolve_run_phase("close") == "close"


def test_intraday_phase_does_not_merge_quote_into_confirmed_history():
    frame = make_daily_frame([100.0] * 40)

    confirmed = prepare_confirmed_data(frame, make_quote(110), "intraday")

    pd.testing.assert_frame_equal(confirmed, frame)


def test_close_phase_merges_new_quote_into_confirmed_history():
    frame = make_daily_frame([100.0] * 40)
    quote = make_quote(110, date="2026-07-20", time="15:30:00")

    confirmed = prepare_confirmed_data(frame, quote, "close")

    assert len(confirmed) == len(frame) + 1
    assert confirmed.iloc[-1]["date"] == pd.Timestamp("2026-07-20")
    assert confirmed.iloc[-1]["close"] == 110


def test_last_row_confirmed_cross_waits_for_next_open():
    frame = make_daily_frame([100.0] * 40 + [110.0])

    result = compute_signals(frame)

    assert result["all_signals"][-1]["type"] == "buy"
    assert result["all_trades"] == []
    assert result["_valuation"]["shares"] == 0


def test_intraday_history_excludes_same_day_unfinished_daily_bar():
    frame = make_daily_frame([100.0] * 40)
    partial = build_live_frame(frame, make_quote(110))

    confirmed = select_confirmed_history(partial, make_quote(110), "intraday")

    assert confirmed["date"].max() < pd.Timestamp("2026-07-20")
    assert len(confirmed) == len(frame)


def test_stale_quote_cannot_rewrite_confirmed_history():
    frame = make_daily_frame([100.0] * 40)
    stale_date = frame.iloc[-2]["date"].strftime("%Y-%m-%d")

    merged = build_live_frame(frame, make_quote(999, date=stale_date))

    pd.testing.assert_frame_equal(merged, frame)


def test_close_phase_replaces_same_day_partial_bar_with_final_quote():
    frame = make_daily_frame([100.0] * 40)
    same_date = frame.iloc[-1]["date"].strftime("%Y-%m-%d")

    confirmed = prepare_confirmed_data(frame, make_quote(123, date=same_date, time="15:30:00"), "close")

    assert confirmed.iloc[-1]["close"] == 123


def test_stale_quote_does_not_truncate_newer_confirmed_history():
    frame = make_daily_frame([100.0] * 40)
    now = datetime(2026, 7, 20, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    stale = make_quote(99, date="2026-07-09")

    confirmed = select_confirmed_history(frame, stale, "intraday", now=now)

    pd.testing.assert_frame_equal(confirmed, frame)


def test_auto_phase_waits_until_1530_for_close_confirmation():
    timezone = ZoneInfo("Asia/Shanghai")
    assert resolve_run_phase("auto", datetime(2026, 7, 20, 15, 20, tzinfo=timezone)) == "intraday"
    assert resolve_run_phase("auto", datetime(2026, 7, 20, 15, 30, tzinfo=timezone)) == "close"
