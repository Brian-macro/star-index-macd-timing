from pathlib import Path


WORKFLOW = Path(".github/workflows/update_signal.yml").read_text(encoding="utf-8")


def test_workflow_covers_half_hour_trading_session_and_close_confirmation():
    expected_crons = {
        "30 1-3 * * 1-5",  # 09:30, 10:30, 11:30 Beijing
        "0 2-3 * * 1-5",  # 10:00, 11:00 Beijing
        "0,30 5-6 * * 1-5",  # 13:00 through 14:30 Beijing
        "0 7 * * 1-5",  # 15:00 Beijing
        "30 7 * * 1-5",  # 15:30 Beijing close confirmation
    }
    for cron in expected_crons:
        assert f"cron: '{cron}'" in WORKFLOW


def test_workflow_distinguishes_close_confirmation_from_intraday_runs():
    assert "SIGNAL_PHASE" in WORKFLOW
    assert "github.event.schedule == '30 7 * * 1-5'" in WORKFLOW
    assert "'close'" in WORKFLOW
    assert "'intraday'" in WORKFLOW
    assert "'auto'" in WORKFLOW
    assert "github.event_name == 'schedule'" in WORKFLOW
    assert "concurrency:" in WORKFLOW
