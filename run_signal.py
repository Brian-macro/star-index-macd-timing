# -*- coding: utf-8 -*-
"""
科创综指MACD择时信号 - 自动化采集与信号生成
用于 GitHub Actions 定时运行
输出: docs/signal_data.json + 更新 docs/index.html
"""
import sys
import os
import json
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')
os.environ['NO_PROXY'] = '*'

import pandas as pd
import numpy as np
import requests

# 路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DOCS_DIR = os.path.join(BASE_DIR, 'docs')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)


# ========================================================================
# 1. 数据采集
# ========================================================================
def download_daily_data():
    """从新浪下载科创综指日线数据"""
    print('[1/4] 下载日线数据...')
    session = requests.Session()
    session.trust_env = False
    session.proxies = {'http': None, 'https': None}

    # 新浪指数日线API
    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    all_data = []
    datalen = 5000
    params = {
        'symbol': 'sh000680',
        'scale': '240',  # 240分钟=日线
        'ma': 'no',
        'datalen': str(datalen),
    }

    try:
        r = session.get(url, params=params, timeout=60)
        data = json.loads(r.text)
        for d in data:
            all_data.append(d)
        print(f'  新浪日线: {len(data)} bars')
    except Exception as e:
        print(f'  新浪日线失败: {e}')

    # 也试试 akshare
    if len(all_data) < 100:
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily(symbol="sh000680")
            df = df.rename(columns={'date': 'day', 'open': 'open', 'high': 'high',
                                     'low': 'low', 'close': 'close', 'volume': 'volume'})
            for _, row in df.iterrows():
                all_data.append({
                    'day': str(row['day'])[:10],
                    'open': str(row['open']),
                    'high': str(row['high']),
                    'low': str(row['low']),
                    'close': str(row['close']),
                    'volume': str(row['volume']),
                })
            print(f'  akshare日线: {len(df)} bars')
        except Exception as e:
            print(f'  akshare日线失败: {e}')

    if not all_data:
        # 尝试读取本地缓存
        cache_path = os.path.join(DATA_DIR, 'kcz_daily.csv')
        if os.path.exists(cache_path):
            print('  使用本地缓存')
            df = pd.read_csv(cache_path, encoding='utf-8-sig')
            return df
        raise RuntimeError('无法获取日线数据')

    df = pd.DataFrame(all_data)
    df = df.rename(columns={'day': 'date'})
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    df.to_csv(os.path.join(DATA_DIR, 'kcz_daily.csv'), index=False, encoding='utf-8-sig')
    print(f'  日线数据: {len(df)} bars, {df["date"].iloc[0].strftime("%Y-%m-%d")} ~ {df["date"].iloc[-1].strftime("%Y-%m-%d")}')
    return df


def download_15min_data():
    """从新浪下载科创综指15分钟数据"""
    print('[2/4] 下载15分钟数据...')
    session = requests.Session()
    session.trust_env = False
    session.proxies = {'http': None, 'https': None}

    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    params = {
        'symbol': 'sh000680',
        'scale': '15',
        'ma': 'no',
        'datalen': '5000',
    }

    try:
        r = session.get(url, params=params, timeout=60)
        data = json.loads(r.text)
        rows = []
        for d in data:
            rows.append({
                'datetime': d['day'],
                'open': float(d['open']),
                'high': float(d['high']),
                'low': float(d['low']),
                'close': float(d['close']),
                'volume': float(d['volume']),
            })
        df = pd.DataFrame(rows)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        df['date'] = df['datetime'].dt.date
        df.to_csv(os.path.join(DATA_DIR, 'kcz_15min.csv'), index=False, encoding='utf-8-sig')
        n_days = df['date'].nunique()
        print(f'  15分钟数据: {len(df)} bars, {n_days}天')
        return df
    except Exception as e:
        print(f'  15分钟数据失败: {e}')
        cache_path = os.path.join(DATA_DIR, 'kcz_15min.csv')
        if os.path.exists(cache_path):
            df = pd.read_csv(cache_path, encoding='utf-8-sig')
            print(f'  使用本地缓存: {len(df)} bars')
            return df
        return None


# ========================================================================
# 2. 信号计算
# ========================================================================
def compute_daily_signals(df_daily):
    """计算日线MACD(12/18/13)信号"""
    print('[3/4] 计算日线MACD信号...')
    ema12 = df_daily['close'].ewm(span=12, adjust=False).mean()
    ema18 = df_daily['close'].ewm(span=18, adjust=False).mean()
    dif = ema12 - ema18
    dea = dif.ewm(span=13, adjust=False).mean()
    macd_bar = 2 * (dif - dea)

    # 信号
    gold = (dif > dea) & (dif.shift(1) <= dea.shift(1))
    dead = (dif < dea) & (dif.shift(1) >= dea.shift(1))

    signals = []
    for i in range(len(df_daily)):
        if gold.iloc[i] or dead.iloc[i]:
            signals.append({
                'date': df_daily['date'].iloc[i].strftime('%Y-%m-%d'),
                'type': 'buy' if gold.iloc[i] else 'sell',
                'close': round(float(df_daily['close'].iloc[i]), 2),
                'dif': round(float(dif.iloc[i]), 4),
                'dea': round(float(dea.iloc[i]), 4),
                'macd_bar': round(float(macd_bar.iloc[i]), 4),
            })

    # 当前状态
    last = df_daily.iloc[-1]
    current_state = {
        'date': last['date'].strftime('%Y-%m-%d'),
        'close': round(float(last['close']), 2),
        'dif': round(float(dif.iloc[-1]), 4),
        'dea': round(float(dea.iloc[-1]), 4),
        'macd_bar': round(float(macd_bar.iloc[-1]), 4),
        'position': 'long' if dif.iloc[-1] > dea.iloc[-1] else 'cash',
        'position_cn': '持仓中' if dif.iloc[-1] > dea.iloc[-1] else '空仓中',
    }

    # 最近N笔交易
    trades = []
    pos = 0
    entry_p = 0
    entry_d = None
    for i in range(len(df_daily)):
        if gold.iloc[i] and pos == 0:
            if i + 1 < len(df_daily):
                entry_p = float(df_daily.iloc[i+1]['open']) * 1.001
                entry_d = df_daily.iloc[i+1]['date']
                pos = 1
        elif dead.iloc[i] and pos == 1:
            if i + 1 < len(df_daily):
                exit_p = float(df_daily.iloc[i+1]['open']) * 0.999
                exit_d = df_daily.iloc[i+1]['date']
            else:
                exit_p = float(df_daily.iloc[i]['close']) * 0.999
                exit_d = df_daily.iloc[i]['date']

            ret = (exit_p - entry_p) / entry_p * 100
            days = (exit_d - entry_d).days if entry_d else 0

            # 同期买入持有
            bh_entry = float(df_daily[df_daily['date'] == entry_d]['close'].iloc[0]) if len(df_daily[df_daily['date'] == entry_d]) > 0 else entry_p
            bh_exit = float(df_daily[df_daily['date'] == exit_d]['close'].iloc[0]) if len(df_daily[df_daily['date'] == exit_d]) > 0 else exit_p
            bh_ret = (bh_exit / bh_entry - 1) * 100

            trades.append({
                'entry_date': entry_d.strftime('%Y-%m-%d') if hasattr(entry_d, 'strftime') else str(entry_d)[:10],
                'exit_date': exit_d.strftime('%Y-%m-%d') if hasattr(exit_d, 'strftime') else str(exit_d)[:10],
                'entry_price': round(entry_p, 2),
                'exit_price': round(exit_p, 2),
                'return': round(ret, 2),
                'bh_return': round(bh_ret, 2),
                'excess': round(ret - bh_ret, 2),
                'holding_days': days,
            })
            pos = 0

    # 策略指标
    nav_list = []
    capital = 1e6; cash = 1e6; shares = 0; p = 0; ep = 0
    for i in range(len(df_daily)):
        if gold.iloc[i] and p == 0:
            if i + 1 < len(df_daily):
                bp = float(df_daily.iloc[i+1]['open']) * 1.001
                shares = int(cash * 0.99 / bp)
                if shares > 0:
                    cash -= shares * bp * 1.001
                    p = 1; ep = bp
        elif dead.iloc[i] and p == 1:
            if i + 1 < len(df_daily):
                sp = float(df_daily.iloc[i+1]['open']) * 0.999
                cash += shares * sp * 0.999
                p = 0; shares = 0
        nav_list.append(cash + shares * float(df_daily.iloc[i]['close']))

    nav = np.array(nav_list)
    n_days = len(nav)
    total_ret = (nav[-1] / 1e6 - 1) * 100
    annual_ret = ((nav[-1] / 1e6) ** (252 / max(n_days, 1)) - 1) * 100
    peak = np.maximum.accumulate(nav)
    max_dd = ((nav - peak) / peak).min() * 100
    rets = pd.Series(nav).pct_change().dropna()
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252)) if rets.std() > 0 else 0

    performance = {
        'total_return': round(total_ret, 2),
        'annual_return': round(annual_ret, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe': round(sharpe, 2),
        'total_trades': len(trades),
        'win_rate': round(sum(1 for t in trades if t['return'] > 0) / max(len(trades), 1) * 100, 1),
        'profit_factor': round(
            sum(t['return'] for t in trades if t['return'] > 0) /
            max(abs(sum(t['return'] for t in trades if t['return'] < 0)), 0.01), 2
        ),
    }

    # 买入持有基准
    bh_total = (float(df_daily['close'].iloc[-1]) / float(df_daily['close'].iloc[0]) - 1) * 100
    bh_annual = ((float(df_daily['close'].iloc[-1]) / float(df_daily['close'].iloc[0])) ** (252 / max(n_days, 1)) - 1) * 100
    bh_nav = float(df_daily['close'].iloc[-1]) / float(df_daily['close'].iloc[0]) * 1e6
    bh_peak = np.maximum.accumulate(df_daily['close'].values / df_daily['close'].iloc[0] * 1e6)
    bh_dd = ((df_daily['close'].values / df_daily['close'].iloc[0] * 1e6 - bh_peak) / bh_peak).min() * 100
    benchmark = {
        'total_return': round(bh_total, 2),
        'annual_return': round(bh_annual, 2),
        'max_drawdown': round(bh_dd, 2),
    }

    # 每年收益
    yearly = []
    df_daily_temp = df_daily.copy()
    df_daily_temp['year'] = df_daily_temp['date'].dt.year
    df_daily_temp['nav'] = nav

    for year, grp in df_daily_temp.groupby('year'):
        if len(grp) > 1:
            yr = (grp['nav'].iloc[-1] / grp['nav'].iloc[0] - 1) * 100
            yb = (float(grp['close'].iloc[-1]) / float(grp['close'].iloc[0]) - 1) * 100
            yearly.append({
                'year': int(year),
                'strategy': round(yr, 1),
                'benchmark': round(yb, 1),
                'excess': round(yr - yb, 1),
            })

    print(f'  策略年化: {annual_ret:.1f}%, 夏普: {sharpe:.2f}, 回撤: {max_dd:.1f}%')
    print(f'  当前: {current_state["position_cn"]}, 最新价 {current_state["close"]}')

    # 月度净值曲线
    df_daily_temp['s_nav'] = nav / 1e6
    df_daily_temp['b_nav'] = df_daily_temp['close'].values / float(df_daily_temp['close'].iloc[0])
    df_daily_temp['ym'] = df_daily_temp['date'].dt.to_period('M')
    monthly = df_daily_temp.groupby('ym').last().reset_index()
    nav_monthly = []
    for _, row in monthly.iterrows():
        nav_monthly.append({
            'date': str(row['date'].date()),
            'strategy': round(float(row['s_nav']), 4),
            'benchmark': round(float(row['b_nav']), 4),
        })
    print(f'  月度净值: {len(nav_monthly)} 点')

    return {
        'current': current_state,
        'performance': performance,
        'benchmark': benchmark,
        'all_signals': signals,
        'all_trades': trades,
        'nav_monthly': nav_monthly,
        'yearly': yearly,
    }


# ========================================================================
# 2b. 实时盘中信号监测
# ========================================================================
def compute_realtime_signal(df_daily, df_15min):
    """
    用最新15分钟数据计算"盘中实时MACD"
    核心思路: 用前一天的EMA值递推, 结合当日最新的15分钟价格
    不用等收盘, 盘中就能发现DIF穿越DEA
    """
    if df_15min is None or len(df_15min) < 100:
        return None

    print('  [盘中监测] 计算实时MACD...')

    # 日线MACD历史值 (到昨天为止)
    ema12 = df_daily['close'].ewm(span=12, adjust=False).mean()
    ema18 = df_daily['close'].ewm(span=18, adjust=False).mean()
    dif_daily = ema12 - ema18
    dea_daily = dif_daily.ewm(span=13, adjust=False).mean()

    # 前一交易日的EMA和DIF/DEA值
    last_ema12 = float(ema12.iloc[-2]) if len(ema12) >= 2 else float(ema12.iloc[-1])
    last_ema18 = float(ema18.iloc[-2]) if len(ema18) >= 2 else float(ema18.iloc[-1])
    last_dif = float(dif_daily.iloc[-2]) if len(dif_daily) >= 2 else float(dif_daily.iloc[-1])
    last_dea = float(dea_daily.iloc[-2]) if len(dea_daily) >= 2 else float(dea_daily.iloc[-1])

    alpha12 = 2 / (12 + 1)
    alpha18 = 2 / (18 + 1)
    alpha_dea = 2 / (13 + 1)

    # 取当日最新的15分钟数据
    today = df_15min['date'].iloc[-1]
    today_bars = df_15min[df_15min['date'] == today].copy()

    if len(today_bars) == 0:
        return None

    latest_bar = today_bars.iloc[-1]
    latest_price = float(latest_bar['close'])
    latest_time = str(latest_bar['datetime'])

    # 递推计算实时EMA
    rt_ema12 = alpha12 * latest_price + (1 - alpha12) * last_ema12
    rt_ema18 = alpha18 * latest_price + (1 - alpha18) * last_ema18
    rt_dif = rt_ema12 - rt_ema18
    rt_dea = alpha_dea * rt_dif + (1 - alpha_dea) * last_dea
    rt_macd_bar = 2 * (rt_dif - rt_dea)

    # 判断盘中穿越
    cross_up = rt_dif > rt_dea and last_dif <= last_dea   # 盘中金叉
    cross_down = rt_dif < rt_dea and last_dif >= last_dea  # 盘中死叉

    # 穿越确认: 即使没有精确穿越, 也报告DIF和DEA的距离
    distance = rt_dif - rt_dea
    distance_pct = distance / abs(last_dea) * 100 if last_dea != 0 else 0

    result = {
        'time': latest_time,
        'price': round(latest_price, 2),
        'rt_dif': round(float(rt_dif), 4),
        'rt_dea': round(float(rt_dea), 4),
        'rt_macd_bar': round(float(rt_macd_bar), 4),
        'prev_dif': round(float(last_dif), 4),
        'prev_dea': round(float(last_dea), 4),
        'distance': round(float(distance), 4),
        'distance_pct': round(float(distance_pct), 2),
        'cross_up': bool(cross_up),
        'cross_down': bool(cross_down),
        'approaching_cross': bool(abs(distance_pct) < 10),  # DIF接近DEA
        'alert': '',
    }

    if cross_up:
        result['alert'] = f'盘中金叉! DIF({rt_dif:.2f}) > DEA({rt_dea:.2f}), 建议立即买入'
    elif cross_down:
        result['alert'] = f'盘中死叉! DIF({rt_dif:.2f}) < DEA({rt_dea:.2f}), 建议立即卖出'
    elif rt_dif > rt_dea:
        result['alert'] = f'DIF在DEA上方, 距离{distance:.2f}, 持仓中'
    else:
        result['alert'] = f'DIF在DEA下方, 距离{distance:.2f}, 空仓中'

    print(f'  [盘中监测] {result["alert"]}')
    return result


# ========================================================================
# 3. 输出JSON
# ========================================================================
def save_signal_json(data):
    """保存信号JSON"""
    path = os.path.join(DOCS_DIR, 'signal_data.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[4/4] 信号数据已保存: {path}')


# ========================================================================
# 主流程
# ========================================================================
def main():
    print('=' * 60)
    print('科创综指MACD择时信号 - 自动更新')
    print('=' * 60)
    print(f'时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')

    df_daily = download_daily_data()
    df_15min = download_15min_data()

    signal_data = compute_daily_signals(df_daily)

    # 实时盘中信号
    realtime = compute_realtime_signal(df_daily, df_15min)
    if realtime:
        signal_data['realtime'] = realtime

    save_signal_json(signal_data)

    print('\n完成!')


if __name__ == '__main__':
    main()
