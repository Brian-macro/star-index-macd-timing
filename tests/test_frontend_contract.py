from pathlib import Path


HTML = Path("docs/index.html").read_text(encoding="utf-8")


def test_frontend_labels_intraday_estimates_and_timestamps():
    assert "预估信号" in HTML
    assert "盘中估算" in HTML
    assert "行情时间" in HTML
    assert "生成时间" in HTML


def test_frontend_uses_intraday_snapshot_when_available():
    assert "d.intraday" in HTML
    assert "signal_label" in HTML
    assert "strategy_nav" in HTML
    assert "benchmark_nav" in HTML


def test_frontend_renders_explicit_confirmed_status_and_has_no_stale_fallback():
    assert "d.signal_status" in HTML
    assert "收盘确认" in HTML
    assert "var EMBEDDED = null;" in HTML


def test_holding_days_rendering_is_null_safe():
    assert "Number.isFinite(Number(t.holding_days))" in HTML
    assert "t.holding_days + ' 天'" not in HTML
