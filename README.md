# 红利组合自动监控系统

基于 AKShare 的 A 股红利组合自动监控与推送系统。每日收盘后自动获取行情数据，计算综合评分和买卖信号，通过企业微信群机器人推送日报。

## 组合配置（v7）

| 代码 | 名称 | 类型 | 目标仓位 |
|------|------|------|---------|
| 600036 | 招商银行 | 股票 | 15% |
| 515450 | 红利低波50ETF | ETF | 15% |
| 600900 | 长江电力 | 股票 | 15% |
| 000651 | 格力电器 | 股票 | 11% |
| 601668 | 中国建筑 | 股票 | 11% |
| 600941 | 中国移动A | 股票 | 9% |
| 601006 | 大秦铁路 | 股票 | 9% |
| 000895 | 双汇发展 | 股票 | 10% |

总资金：405,000 元 | 现金目标：约 5%

## 功能特性

- 动态数据获取（AKShare）：实时行情、PE/PB 估值、股息率、RSI、均线
- 综合评分系统（100 分制）：PE 分位 + 股息率 + 均线 + RSI + 基本面 + 行业景气
- 信号驱动 4 层建仓：L1(25%) → L2(50%) → L3(75%) → L4(100%)
- 市场温度计：股债利差(ERP)为核心，动态调整现金比例
- 极端清仓规则：股息率底线 + 基本面恶化检测，最高优先级避险
- 企业微信推送：每日 15:37（北京时间）自动推送日报
- 状态持久化：通过 GitHub Actions artifact + Git commit 跨次保持组合状态

## 快速开始

### 1. Fork 本仓库

点击右上角 Fork 按钮，将仓库复制到你的 GitHub 账号下。

### 2. 配置企业微信 Webhook

在仓库中设置 Secret：
1. 进入 Settings → Secrets and variables → Actions
2. 点击 New repository secret
3. Name: `WECHAT_WEBHOOK_URL`
4. Value: 你的企业微信 Webhook 地址

### 3. 启用 Actions

进入 Actions 标签页，点击 "I understand my workflows, go ahead and enable them"。

## 项目结构

```
dividend-monitor/
├── .github/workflows/
│   └── daily-monitor.yml    # GitHub Actions 定时任务
├── scripts/
│   ├── dividend_monitor.py  # 主监控脚本
│   ├── build_calculator.py  # 建仓速查表
│   ├── backtest_engine.py   # 回测引擎
│   └── requirements.txt     # Python 依赖
├── data/                    # 运行时数据（自动生成）
│   └── portfolio_state.json # 组合状态持久化
└── README.md
```

## 本地运行

```bash
# 安装依赖
pip install -r scripts/requirements.txt

# 设置 Webhook（可选，不设置则只打印报告不推送）
export WECHAT_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key"

# 运行监控
python scripts/dividend_monitor.py

# 回测模式
python scripts/dividend_monitor.py --backtest

# 查看仓位建议
python scripts/dividend_monitor.py --positions
```

## 自动运行

脚本将在每个交易日（周一至周五）北京时间 15:37 自动运行。

也可在 Actions 页面手动点击 "Run workflow" 触发执行。
