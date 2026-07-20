# -*- coding: utf-8 -*-
"""
科创综指 MACD(12/18/13) 择时信号系统
用于 GitHub Actions 定时运行 (每个交易日收盘后更新)
输出: docs/signal_data.json

执行规则: 日线金叉/死叉 → 次日开盘价执行, 千一单边手续费
"""
import sys
import os
import json
from datetime import datetime
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding='utf-8')
os.environ['NO_PROXY'] = '*'

import pandas as pd
import numpy as np
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DOCS_DIR = os.path.join(BASE_DIR, 'docs')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

FEE = 0.001  # 千一单边手续费


def calculate_holding_days(entry_date, exit_date):
    """Return the calendar-day distance between two trade dates."""
    return int((pd.Timestamp(exit_date) - pd.Timestamp(entry_date)).days)


def calculate_macd(close):
    """Calculate MACD(12/18/13) arrays from a close-price sequence."""
    series = pd.Series(close, dtype=float)
    ema12 = series.ewm(span=12, adjust=False).mean().to_numpy()
    ema18 = series.ewm(span=18, adjust=False).mean().to_numpy()
    dif = ema12 - ema18
    dea = pd.Series(dif).ewm(span=13, adjust=False).mean().to_numpy()
    return dif, dea, 2 * (dif - dea)


def parse_sina_quote(payload):
    """Parse the comma-delimited Sina real-time index quote response."""
    if '="' not in payload:
        raise ValueError('新浪实时行情格式无效')
    body = payload.split('="', 1)[1].rsplit('"', 1)[0]
    fields = body.split(',')
    if len(fields) < 33 or not fields[0]:
        raise ValueError('新浪实时行情字段不完整')
    return {
        'name': fields[0],
        'open': float(fields[1]),
        'previous_close': float(fields[2]),
        'price': float(fields[3]),
        'high': float(fields[4]),
        'low': float(fields[5]),
        'volume': float(fields[8]),
        'date': fields[30],
        'time': fields[31],
        'source': 'sina_realtime',
    }


def download_realtime_quote():
    """Download the latest STAR Composite quote from Sina."""
    url = 'https://hq.sinajs.cn/list=sh000680'
    response = requests.get(
        url,
        timeout=30,
        headers={'Referer': 'https://finance.sina.com.cn/'},
        proxies={'http': None, 'https': None},
    )
    response.raise_for_status()
    response.encoding = 'gbk'
    return parse_sina_quote(response.text)


def build_live_frame(df, quote, allow_same_date=False):
    """Return a copy of daily data with the current real-time quote upserted."""
    live = df.copy(deep=True)
    quote_date = pd.Timestamp(quote['date']).normalize()
    row = {
        'date': quote_date,
        'open': quote['open'],
        'high': quote['high'],
        'low': quote['low'],
        'close': quote['price'],
        'volume': quote['volume'],
    }
    if not live.empty:
        last_date = live['date'].dt.normalize().max()
        if quote_date < last_date or (quote_date == last_date and not allow_same_date):
            return live
    matches = live['date'].dt.normalize() == quote_date
    if matches.any():
        for key, value in row.items():
            live.loc[matches, key] = value
    else:
        live = pd.concat([live, pd.DataFrame([row])], ignore_index=True)
    return live.sort_values('date').reset_index(drop=True)


def build_intraday_snapshot(df, quote, valuation):
    """Build an estimated current-day signal and NAV without mutating history."""
    live = build_live_frame(df, quote)
    confirmed_dif, confirmed_dea, _ = calculate_macd(df['close'].to_numpy())
    dif, dea, macd_bar = calculate_macd(live['close'].to_numpy())
    previous_relation = float(confirmed_dif[-1] - confirmed_dea[-1])
    live_relation = float(dif[-1] - dea[-1])
    if previous_relation <= 0 < live_relation:
        signal_type, signal_label = 'buy', '预估买入信号'
    elif previous_relation >= 0 > live_relation:
        signal_type, signal_label = 'sell', '预估卖出信号'
    else:
        signal_type, signal_label = 'none', '暂无预估穿越信号'

    price = float(quote['price'])
    strategy_nav = (float(valuation['cash']) + int(valuation['shares']) * price) / 1_000_000
    benchmark_nav = price / float(valuation['first_close'])
    generated = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    return {
        'market_time': f"{quote['date']} {quote['time']}",
        'generated_time': generated,
        'price': round(price, 4),
        'dif': round(float(dif[-1]), 4),
        'dea': round(float(dea[-1]), 4),
        'macd_bar': round(float(macd_bar[-1]), 4),
        'position': 'long' if int(valuation['shares']) > 0 else 'cash',
        'signal_type': signal_type,
        'signal_label': signal_label,
        'is_estimated': True,
        'strategy_nav': round(strategy_nav, 4),
        'benchmark_nav': round(benchmark_nav, 4),
    }


def resolve_run_phase(requested='auto', now=None):
    """Resolve whether this invocation is intraday estimation or close confirmation."""
    requested = (requested or 'auto').lower()
    if requested in {'intraday', 'close'}:
        return requested
    if requested != 'auto':
        raise ValueError(f'不支持的 SIGNAL_PHASE: {requested}')
    current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    return 'close' if (current.hour, current.minute) >= (15, 30) else 'intraday'


def prepare_confirmed_data(df, quote, phase):
    """Merge the live bar only for a close-confirmation run."""
    if phase == 'close' and quote:
        return build_live_frame(df, quote, allow_same_date=True)
    return df.copy(deep=True)


def select_confirmed_history(df, quote, phase, now=None):
    """Exclude an unfinished current-day bar from intraday backtest history."""
    if phase == 'close':
        return prepare_confirmed_data(df, quote, phase)
    current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    cutoff = pd.Timestamp(current.date())
    confirmed = df[df['date'].dt.normalize() < cutoff].copy()
    return confirmed.reset_index(drop=True)


# ========================================================================
# 1. 数据采集
# ========================================================================
def download_daily_data():
    """从新浪下载科创综指(000680.SH)日线数据"""
    print('[1/3] 下载日线数据...')
    session = requests.Session()
    session.trust_env = False
    session.proxies = {'http': None, 'https': None}

    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    all_data = []
    params = {'symbol': 'sh000680', 'scale': '240', 'ma': 'no', 'datalen': '5000'}

    try:
        r = session.get(url, params=params, timeout=60)
        data = json.loads(r.text)
        for d in data:
            all_data.append(d)
        print(f'  新浪日线: {len(data)} bars')
    except Exception as e:
        print(f'  新浪日线失败: {e}')

    if len(all_data) < 100:
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily(symbol="sh000680")
            df = df.rename(columns={'date': 'day', 'open': 'open', 'high': 'high',
                                     'low': 'low', 'close': 'close', 'volume': 'volume'})
            for _, row in df.iterrows():
                all_data.append({
                    'day': str(row['day'])[:10], 'open': str(row['open']),
                    'high': str(row['high']), 'low': str(row['low']),
                    'close': str(row['close']), 'volume': str(row['volume']),
                })
            print(f'  akshare日线: {len(df)} bars')
        except Exception as e:
            print(f'  akshare日线失败: {e}')

    if not all_data:
        cache_path = os.path.join(DATA_DIR, 'kcz_daily.csv')
        if os.path.exists(cache_path):
            print('  使用本地缓存')
            return pd.read_csv(cache_path, encoding='utf-8-sig')
        raise RuntimeError('无法获取日线数据')

    df = pd.DataFrame(all_data)
    df = df.rename(columns={'day': 'date'})
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df.to_csv(os.path.join(DATA_DIR, 'kcz_daily.csv'), index=False, encoding='utf-8-sig')
    d0, d1 = df['date'].iloc[0].strftime('%Y-%m-%d'), df['date'].iloc[-1].strftime('%Y-%m-%d')
    print(f'  日线: {len(df)} bars, {d0} ~ {d1}')
    return df


# ========================================================================
# 2. 日线 MACD(12/18/13) 回测 + 信号生成
# ========================================================================
def compute_signals(df):
    """
    日线 MACD(12/18/13) 金叉买入/死叉卖出
    执行: 信号日次日开盘价, 含千一手续费
    """
    print('[2/3] 计算日线MACD信号...')

    close = df['close'].values
    open_p = df['open'].values
    dates = df['date']

    # MACD(12/18/13)
    dif, dea, macd_bar = calculate_macd(close)

    # --- 信号列表 ---
    gold = (dif > dea) & (np.roll(dif, 1) <= np.roll(dea, 1))
    dead = (dif < dea) & (np.roll(dif, 1) >= np.roll(dea, 1))
    gold[0] = dead[0] = False

    all_signals = []
    for i in range(len(df)):
        if gold[i] or dead[i]:
            all_signals.append({
                'date': dates.iloc[i].strftime('%Y-%m-%d'),
                'type': 'buy' if gold[i] else 'sell',
                'close': round(float(close[i]), 2),
                'dif': round(float(dif[i]), 4),
                'dea': round(float(dea[i]), 4),
                'macd_bar': round(float(macd_bar[i]), 4),
            })

    # --- 回测: 次日开盘执行, 千一手续费 ---
    cash = 1_000_000.0; shares = 0; pos = 0
    nav = np.zeros(len(df))
    trades = []
    entry_price = 0; entry_date = None

    for i in range(len(df)):
        price = float(close[i])

        if pos == 0 and gold[i] and i + 1 < len(df):
            cost = float(open_p[i + 1]) * (1 + FEE)
            shares = int(cash * 0.9999 / cost)
            if shares > 0:
                cash -= shares * cost
                pos = 1
                entry_price = cost
                entry_date = dates.iloc[i + 1]

        elif pos == 1 and dead[i] and i + 1 < len(df):
            proceeds = float(open_p[i + 1]) * (1 - FEE)
            exit_date = dates.iloc[i + 1]

            cash += shares * proceeds
            ret_pct = (proceeds / entry_price - 1) * 100

            # 同期买入持有
            bh_en = float(df[df['date'] == entry_date]['close'].iloc[0]) if len(df[df['date'] == entry_date]) > 0 else entry_price
            bh_ex = float(df[df['date'] == exit_date]['close'].iloc[0]) if len(df[df['date'] == exit_date]) > 0 else proceeds
            bh_ret = (bh_ex / bh_en - 1) * 100

            hold_days = calculate_holding_days(entry_date, exit_date)

            trades.append({
                'entry_date': entry_date.strftime('%Y-%m-%d') if hasattr(entry_date, 'strftime') else str(entry_date)[:10],
                'exit_date': exit_date.strftime('%Y-%m-%d') if hasattr(exit_date, 'strftime') else str(exit_date)[:10],
                'entry_price': round(entry_price, 2),
                'exit_price': round(proceeds, 2),
                'return': round(ret_pct, 2),
                'bh_return': round(bh_ret, 2),
                'excess': round(ret_pct - bh_ret, 2),
                'holding_days': hold_days,
            })
            pos = 0; shares = 0

        nav[i] = cash + shares * price

    if pos == 1:
        nav[-1] = cash + shares * float(close[-1])

    # --- 策略指标 ---
    n = len(nav)
    total_ret = (nav[-1] / 1_000_000 - 1) * 100
    annual_ret = ((nav[-1] / 1_000_000) ** (252 / max(n, 1)) - 1) * 100
    peak = np.maximum.accumulate(nav)
    max_dd = float(((nav - peak) / peak).min() * 100)
    daily_rets = pd.Series(nav).pct_change().dropna()
    sharpe = float(daily_rets.mean() / daily_rets.std() * np.sqrt(252)) if daily_rets.std() > 0 else 0
    calmar = annual_ret / abs(max_dd) if max_dd != 0 else 0

    wins = [t for t in trades if t['return'] > 0]
    losses = [t for t in trades if t['return'] <= 0]
    win_rate = len(wins) / max(len(trades), 1) * 100
    avg_win = sum(t['return'] for t in wins) / max(len(wins), 1) if wins else 0
    avg_loss = sum(abs(t['return']) for t in losses) / max(len(losses), 1) if losses else 0
    profit_factor = avg_win / avg_loss if avg_loss > 0 else 999

    performance = {
        'total_return': round(total_ret, 2),
        'annual_return': round(annual_ret, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'calmar': round(calmar, 2),
        'total_trades': len(trades),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
    }

    # --- 买入持有基准 ---
    bh_total = (float(close[-1]) / float(close[0]) - 1) * 100
    bh_annual = ((float(close[-1]) / float(close[0])) ** (252 / max(n, 1)) - 1) * 100
    bh_nav = close / close[0] * 1_000_000
    bh_dd = float(((bh_nav - np.maximum.accumulate(bh_nav)) / np.maximum.accumulate(bh_nav)).min() * 100)
    benchmark = {
        'total_return': round(bh_total, 2),
        'annual_return': round(bh_annual, 2),
        'max_drawdown': round(bh_dd, 2),
    }

    # --- 当前状态 ---
    last_i = len(df) - 1
    current_state = {
        'date': dates.iloc[last_i].strftime('%Y-%m-%d'),
        'close': round(float(close[last_i]), 2),
        'dif': round(float(dif[last_i]), 4),
        'dea': round(float(dea[last_i]), 4),
        'macd_bar': round(float(macd_bar[last_i]), 4),
        'position': 'long' if dif[last_i] > dea[last_i] else 'cash',
        'position_cn': '持仓中' if dif[last_i] > dea[last_i] else '空仓中',
    }

    # --- 逼近穿越检测 ---
    dif_last = float(dif[last_i])
    dea_last = float(dea[last_i])
    dist = dif_last - dea_last
    dist_pct = abs(dist / dea_last * 100) if dea_last != 0 else 999
    approaching = {
        'distance': round(float(dist), 2),
        'distance_pct': round(float(dist_pct), 2),
        'direction': 'DIF在DEA上方' if dist > 0 else 'DIF在DEA下方',
        'approaching_dead': dist > 0 and dist_pct < 8,
        'approaching_gold': dist < 0 and dist_pct < 8,
        'alert': '',
    }
    if approaching['approaching_dead']:
        approaching['alert'] = f'⚠️ DIF 逼近 DEA，仅差 {dist_pct:.1f}%，即将死叉！注意风险'
    elif approaching['approaching_gold']:
        approaching['alert'] = f'🔔 DIF 逼近 DEA，仅差 {dist_pct:.1f}%，即将金叉！准备买入'
    elif dist_pct < 20:
        dir_cn = '上方' if dist > 0 else '下方'
        approaching['alert'] = f'DIF 在 DEA {dir_cn} {dist_pct:.1f}%，可关注'
    else:
        dir_cn = '上方' if dist > 0 else '下方'
        approaching['alert'] = f'DIF 在 DEA {dir_cn} {dist_pct:.1f}%，距离较远'

    # --- 年度收益 ---
    yearly = []
    df_tmp = df.copy()
    df_tmp['nav'] = nav; df_tmp['year'] = df_tmp['date'].dt.year
    for year, grp in df_tmp.groupby('year'):
        if len(grp) > 1:
            yr = (grp['nav'].iloc[-1] / grp['nav'].iloc[0] - 1) * 100
            yb = (float(grp['close'].iloc[-1]) / float(grp['close'].iloc[0]) - 1) * 100
            yearly.append({
                'year': int(year),
                'strategy': round(yr, 1),
                'benchmark': round(yb, 1),
                'excess': round(yr - yb, 1),
            })

    # --- 月度净值曲线 ---
    df_tmp['s_nav'] = nav / 1_000_000
    df_tmp['b_nav'] = close / close[0]
    df_tmp['ym'] = df_tmp['date'].dt.to_period('M')
    monthly = df_tmp.groupby('ym').last().reset_index()
    nav_monthly = []
    for _, row in monthly.iterrows():
        nav_monthly.append({
            'date': str(row['date'].date()),
            'strategy': round(float(row['s_nav']), 4),
            'benchmark': round(float(row['b_nav']), 4),
        })

    print(f'  年化: {annual_ret:.1f}%  夏普: {sharpe:.2f}  回撤: {max_dd:.1f}%  交易: {len(trades)}笔')
    print(f'  当前: {current_state["position_cn"]}, 净值: {nav[-1]/1_000_000:.4f}')

    return {
        'current': current_state,
        'approaching': approaching,
        'performance': performance,
        'benchmark': benchmark,
        'all_signals': all_signals,
        'all_trades': trades,
        'nav_monthly': nav_monthly,
        'yearly': yearly,
        '_valuation': {
            'cash': cash,
            'shares': shares,
            'first_close': float(close[0]),
        },
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }


# ========================================================================
# 3. 输出
# ========================================================================
def save_signal_json(data):
    path = os.path.join(DOCS_DIR, 'signal_data.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[3/3] 已保存: {path}')


# ========================================================================
# 主流程
# ========================================================================
def main():
    print('=' * 55)
    print('科创综指 MACD(12/18/13) 择时信号')
    print(f'手续费: 千一单边 | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print('=' * 55)
    print()

    phase = resolve_run_phase(os.environ.get('SIGNAL_PHASE', 'auto'))
    df = download_daily_data()
    quote = None
    quote_error = ''
    try:
        quote = download_realtime_quote()
        print(f"  实时行情: {quote['date']} {quote['time']}  {quote['price']:.2f}")
    except Exception as exc:
        quote_error = str(exc)
        print(f'  实时行情失败: {exc}')

    confirmed_df = select_confirmed_history(df, quote, phase)
    result = compute_signals(confirmed_df)
    valuation = result.pop('_valuation')
    generated_time = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S')
    if phase == 'intraday' and quote:
        result['intraday'] = build_intraday_snapshot(confirmed_df, quote, valuation)

    market_time = (
        f"{quote['date']} {quote['time']}"
        if quote
        else f"{result['current']['date']} 收盘"
    )
    result['signal_status'] = {
        'phase': phase,
        'is_estimated': phase == 'intraday',
        'label': (
            result.get('intraday', {}).get('signal_label', '盘中估算')
            if phase == 'intraday'
            else '收盘确认'
        ),
    }
    result['data_source'] = quote['source'] if quote else 'sina_daily_cache'
    result['market_time'] = market_time
    result['generated_time'] = generated_time
    if quote_error:
        result['data_warning'] = f'实时行情不可用：{quote_error}'
    result['update_time'] = generated_time
    save_signal_json(result)

    print('\n完成!')


if __name__ == '__main__':
    main()
