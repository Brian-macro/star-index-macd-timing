# Intraday Signal Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh the STAR Composite strategy every 30 minutes during trading sessions, expose clearly labeled estimated intraday signals and NAV, confirm signals after close, and repair holding-day output.

**Architecture:** Keep confirmed daily bars and backtest history as the source of truth. Fetch the Sina real-time quote separately, use it to build a temporary current-day bar for intraday MACD/NAV estimates, and only merge that bar into confirmed computation during the 15:30 close run. Emit explicit JSON metadata so the HTML renders confirmed versus estimated states without inferring them.

**Tech Stack:** Python 3.11, pandas, NumPy, requests, pytest, vanilla HTML/CSS/JavaScript, GitHub Actions cron.

---

### Task 1: Add regression coverage for holding days

**Files:**
- Create: `tests/test_run_signal.py`
- Modify: `run_signal.py`

- [ ] **Step 1: Write the failing test**

Add tests importing `calculate_holding_days` and asserting `2026-06-18` to `2026-07-08` is 20, `2025-12-31` to `2026-01-02` is 2, and same-day input is 0.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_run_signal.py -q`
Expected: collection fails because `calculate_holding_days` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add:

```python
def calculate_holding_days(entry_date, exit_date):
    return int((pd.Timestamp(exit_date) - pd.Timestamp(entry_date)).days)
```

Replace the incorrect `hasattr(exit_date, 'days')` expression with this helper.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_run_signal.py -q`
Expected: holding-day tests pass.

### Task 2: Add real-time quote parsing and estimated snapshot computation

**Files:**
- Modify: `tests/test_run_signal.py`
- Modify: `run_signal.py`

- [ ] **Step 1: Write failing quote and snapshot tests**

Test `parse_sina_quote` with a representative `hq_str_sh000680` response and assert name, open/high/low/price, date, and time. Build deterministic daily frames that produce an estimated gold cross and dead cross, then assert `build_intraday_snapshot` returns `is_estimated=True`, `signal_type` of `buy`/`sell`, labels `预估买入信号`/`预估卖出信号`, and does not mutate the input frame. Test long-position and cash-position estimated NAV behavior.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_signal.py -q`
Expected: imports fail for the new functions.

- [ ] **Step 3: Implement quote and snapshot helpers**

Add `download_realtime_quote`, `parse_sina_quote`, `build_live_bar`, `calculate_macd`, and `build_intraday_snapshot`. Use the real-time quote only in a copied temporary frame. The snapshot must contain `market_time`, `generated_time`, `price`, `dif`, `dea`, `macd_bar`, `position`, `signal_type`, `signal_label`, `is_estimated`, `strategy_nav`, and `benchmark_nav`.

- [ ] **Step 4: Preserve confirmed history**

Have `compute_signals` compute history from confirmed bars only and expose the minimum valuation state needed by `build_intraday_snapshot`. During intraday runs, do not append the temporary bar to `all_signals`, `all_trades`, monthly NAV, yearly returns, or performance metrics.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_run_signal.py -q`
Expected: all backend tests pass.

### Task 3: Add explicit intraday and close phases

**Files:**
- Modify: `tests/test_run_signal.py`
- Modify: `run_signal.py`

- [ ] **Step 1: Write failing phase tests**

Test that `resolve_run_phase('intraday')` and `resolve_run_phase('close')` are stable, and that close mode merges a newer quote bar before confirmed computation while intraday mode leaves confirmed history unchanged.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_run_signal.py -q`
Expected: missing phase/merge helpers.

- [ ] **Step 3: Implement phase handling**

Read `SIGNAL_PHASE` with values `intraday`, `close`, or `auto`; determine `auto` using `Asia/Shanghai`. In close mode, merge the current quote into the daily data before `compute_signals`. In intraday mode, compute confirmed output first, then attach the estimated snapshot. Add top-level `signal_status`, `data_source`, `market_time`, and `generated_time` fields.

- [ ] **Step 4: Run backend tests**

Run: `python -m pytest tests/test_run_signal.py -q`
Expected: all backend tests pass.

### Task 4: Render estimated signals, NAV, timestamps, and safe holding days

**Files:**
- Create: `tests/test_frontend_contract.py`
- Modify: `docs/index.html`

- [ ] **Step 1: Write failing frontend contract tests**

Read `docs/index.html` as text and assert it contains the user-visible phrases `预估信号`, `盘中估算`, `行情时间`, and a null-safe holding-day formatter rather than direct concatenation of `t.holding_days`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_frontend_contract.py -q`
Expected: assertions fail against the current HTML.

- [ ] **Step 3: Implement minimal frontend rendering**

Prefer `d.intraday` when present for current price, DIF/DEA, signal label, and NAV. Add an orange/yellow `预估信号` badge, `盘中估算` labels beside live NAV values, and separate market/generated timestamps. Keep confirmed status visually distinct. Render holding days with `Number.isFinite(Number(t.holding_days)) ? ... : '—'`.

- [ ] **Step 4: Run frontend contract tests**

Run: `python -m pytest tests/test_frontend_contract.py -q`
Expected: all frontend contract tests pass.

### Task 5: Schedule all trading-session refreshes

**Files:**
- Create: `tests/test_workflow_schedule.py`
- Modify: `.github/workflows/update_signal.yml`

- [ ] **Step 1: Write a failing schedule test**

Parse the workflow text and assert cron coverage for Beijing 09:30, 10:00, 10:30, 11:00, 11:30, 13:00, 13:30, 14:00, 14:30, 15:00, and 15:30 on weekdays. Assert the workflow passes `SIGNAL_PHASE=close` only for the 15:30 cron and `intraday` otherwise.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_workflow_schedule.py -q`
Expected: current single cron does not cover the required slots.

- [ ] **Step 3: Update GitHub Actions**

Use UTC cron expressions for all required Beijing times and set `SIGNAL_PHASE` from `github.event.schedule`. Continue committing only `docs/signal_data.json` when its content changes. Add `concurrency` to avoid overlapping updates.

- [ ] **Step 4: Run schedule test**

Run: `python -m pytest tests/test_workflow_schedule.py -q`
Expected: schedule contract passes.

### Task 6: Regenerate data, visually verify, clean artifacts, and publish

**Files:**
- Modify: `docs/signal_data.json`
- Modify only if required by generation workflow: `data/kcz_daily.csv`

- [ ] **Step 1: Run the complete automated suite**

Run: `python -m pytest -q`
Expected: all tests pass with zero failures.

- [ ] **Step 2: Generate intraday and close outputs locally**

Run intraday mode against live data, validate the JSON schema and nonzero holding days, then run a deterministic fixture for close mode so live market timing does not make tests flaky.

- [ ] **Step 3: Serve and inspect the page**

Run a local HTTP server, open `docs/index.html`, and verify the estimated badge, NAV label, timestamps, and holding-day values in the rendered page.

- [ ] **Step 4: Clean only generated junk**

Remove `__pycache__`, `.pytest_cache`, temporary screenshots, and local server artifacts created during this implementation. Preserve `tests/`, source files, generated production JSON, design, and plan documents.

- [ ] **Step 5: Final verification and review**

Run `python -m pytest -q`, `python -m compileall -q run_signal.py tests`, `git diff --check`, and inspect `git status` plus the final diff.

- [ ] **Step 6: Commit and push**

Commit the tested implementation on `codex/intraday-signal-refresh`, push it to `origin`, then merge/push to `main` only as authorized by the user's instruction to submit the completed change to GitHub.
