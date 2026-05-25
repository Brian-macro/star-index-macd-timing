# 科创综指 MACD 择时信号系统

**STAR Market Composite Index (000680.SH) — MACD Timing Strategy Dashboard**

> 实时信号 | 自动回测 | GitHub Actions 驱动 | 在线展示

---

## 在线页面

**[点击访问 GitHub Pages](https://2479550027-sudo.github.io/kcz-macd-signal/)**

页面展示当前持仓状态、盘中实时 MACD 监测、策略净值曲线、回测指标、年度收益对比、全部交易明细与信号历史。

## 策略说明

### MACD(12/18/13) 在科创综指上的应用

本策略使用优化后的 MACD 参数 `(Fast=12, Slow=18, Signal=13)` 对科创综指进行日线级别择时：

- **金叉买入**：DIF 上穿 DEA，次日开盘价执行（含 0.1% 滑点）
- **死叉卖出**：DIF 下穿 DEA，次日开盘价执行（含 0.1% 滑点）
- **交易成本**：单边 0.1% 佣金 + 0.1% 滑点

### 回测表现（2020-01 至今）

| 指标 | 策略 | 基准（买入持有） |
|:---|:---:|:---:|
| 年化收益 | +25.45% | +12.62% |
| 最大回撤 | -27.32% | -57.93% |
| 夏普比率 | 1.04 | — |
| 总交易次数 | 42 | — |
| 胜率 | 47.6% | — |
| 盈亏比 | 3.16 | — |

### 过拟合检测结果

通过两种独立方法验证参数 MACD(12/18/13) 不存在过拟合：

**1. DSR 检验（Deflated Sharpe Ratio）**

基于 Bailey & López de Prado (2014) 多重检验修正方法，在 15,660 个参数组合中：

| 检验项 | 结果 |
|:---|:---|
| 有效参数组合数 | 15,660 |
| 最优参数 | (12/18/13) |
| DSR p-value | **1.36e-07** |
| 结论 | 策略捕获的是真实动量效应，非过拟合 |

**2. 参数高原分析（Parameter Plateau）**

| 参数 | 高原比率 (≥90%) | 高原比率 (≥80%) | 判定 |
|:---|:---:|:---:|:---|
| MACD(12/26/9) 标准 | 96.3% | 100% | 非常鲁棒 |
| **MACD(12/18/13) 选用** | **89.3%** | **100%** | **非常鲁棒** |
| MACD(6/10/5) 扫描最优 | 3.7% | 35.6% | 过拟合风险 |

MACD(12/18/13) 的 80% 高原比率达 100%，说明周围大量参数都有同等表现，不是参数孤岛。

## 项目结构

```
├── .github/workflows/
│   └── update_signal.yml     # GitHub Actions 定时任务
├── docs/
│   ├── index.html            # GitHub Pages 展示页面
│   ├── signal_data.json      # 信号数据（由 Actions 自动更新）
│   └── avatar.jpg            # 头像
├── run_signal.py             # 主自动化脚本（数据采集 + 信号计算）
├── requirements.txt          # Python 依赖
├── .gitignore
└── README.md
```

## 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行信号生成（自动下载数据、计算信号、输出 JSON）
python run_signal.py

# 3. 用浏览器打开展示页面
open docs/index.html
```

`run_signal.py` 会自动从新浪财经下载最新的日线和 15 分钟数据，计算 MACD 信号并生成 `docs/signal_data.json`。页面内嵌了备份数据，本地双击 `index.html` 也能正常显示。

## 数据更新机制

### 自动更新（GitHub Actions）

项目配置了 GitHub Actions 定时工作流：

| 触发条件 | 时间 | 用途 |
|:---|:---|:---|
| 盘中实时 | 每个交易日 9:30-15:00，每 15 分钟 | 更新盘中 MACD 实时监测数据 |
| 收盘确认 | 每个交易日 15:30 (UTC 7:30) | 生成当日最终信号 |

### 工作流步骤

```
1. Checkout 代码
2. 安装 Python 3.11 + 依赖 (pandas, numpy, requests)
3. 运行 run_signal.py
   ├── 从新浪财经下载最新日线 + 15 分钟数据
   ├── 计算 MACD(12/18/13) 全部信号和交易
   ├── 计算月度净值曲线
   ├── 计算盘中实时 MACD（15 分钟级别）
   └── 输出 docs/signal_data.json
4. 检测数据变化 → 自动 commit & push
```

### 手动触发

在 GitHub 仓库页面 → Actions → "Update MACD Signal" → Run workflow 即可手动触发。

## GitHub Pages 部署

1. 进入仓库 **Settings → Pages**
2. Source 选择 **Deploy from a branch**
3. Branch 选择 **main**，目录选择 **/docs**
4. 保存后页面将在 `https://<username>.github.io/<repo>/` 生效

## 免责声明

本策略仅供研究学习参考，不构成任何投资建议。MACD 策略基于历史数据回测，过往表现不代表未来收益。投资有风险，入市需谨慎。

## License

MIT
