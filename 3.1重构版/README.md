# Stock Scanner v3.1 重构版

A 股股票分析系统，模块化重构版本。

---

## 目录

- [概述](#概述)
- [目录结构](#目录结构)
- [安装运行](#安装运行)
- [API 接口](#api-接口)
- [核心模块](#核心模块)
- [配置说明](#配置说明)

---

## 概述

v3.1 是对 v3.0 的**模块化重构**版本，主要改进：

- **DataSource 注册表模式**，统一多数据源（东方财富、同花顺、腾讯、新浪等）
- 路由拆分，职责单一
- 持仓巡检模块独立（SQLite 持久化）
- 四层量化信号系统（L0/L1/L2/L3）
- 策略生成器、瓶颈位策略、缠论分析等独立模块

---

## 目录结构

```
3.1重构版/
├── src/
│   ├── run.py                    # Flask 应用入口
│   ├── api/                      # 路由层
│   │   ├── routes.py             # 路由注册
│   │   ├── analyze_routes.py     # 单股票分析 / SSE
│   │   ├── batch_routes.py       # 批量分析
│   │   ├── patrol_routes.py      # 持仓巡检 CRUD
│   │   ├── signal_routes.py      # 市场信号
│   │   ├── screener_routes.py    # 全市场扫描
│   │   ├── extra_routes.py       # 附加路由
│   │   ├── review_routes.py      # 复盘路由
│   │   ├── auth.py               # 认证
│   │   └── schemas.py            # 数据校验
│   ├── core/                     # 业务逻辑
│   │   ├── analyzer.py           # 股票分析引擎
│   │   ├── batch.py              # 批量分析
│   │   ├── patrol.py             # 持仓管理器
│   │   ├── signals.py            # 信号生成器
│   │   ├── strategy_generator.py # 策略生成
│   │   ├── indicators.py         # 技术指标纯函数
│   │   ├── fundamental.py        # 基本面评分
│   │   ├── chanlun.py            # 缠论分析
│   │   ├── screener.py           # 全市场扫描
│   │   ├── backtest.py           # 回测引擎
│   │   ├── bottleneck_strategy.py# 瓶颈位策略
│   │   ├── bottleneck_kb.py      # 瓶颈位知识库
│   │   ├── news_monitor.py       # 新闻监控
│   │   ├── quant_signals.py      # 量化信号
│   │   ├── signal_explainer.py   # 信号解释
│   │   ├── stock_cache.py        # 股票缓存
│   │   ├── today_prediction.py   # 今日预测
│   │   ├── prepost_review.py     # 盘前盘后复盘
│   │   └── events.py             # 事件系统
│   ├── data/                     # 数据源层
│   │   ├── base.py               # DataSource 基类
│   │   ├── registry.py           # 数据源注册表
│   │   ├── akshare.py            # AkShare 源
│   │   ├── tencent.py            # 腾讯源
│   │   ├── eastmoney.py          # 东方财富源
│   │   ├── eastmoney_http.py     # 东方财富 HTTP
│   │   ├── ths.py                # 同花顺源
│   │   ├── sina_kline.py         # 新浪 K 线
│   │   ├── tencent_kline.py      # 腾讯 K 线
│   │   ├── baidu.py              # 百度源
│   │   ├── news.py               # 新闻获取
│   │   ├── news_sources.py       # 新闻源
│   │   ├── company_info.py       # 公司信息
│   │   ├── industry.py           # 行业数据
│   │   └── market_sentiment.py   # 市场情绪
│   ├── storage/                  # 存储层
│   │   ├── sqlite_db.py          # SQLite 连接
│   │   ├── patrol_repo.py        # 持仓仓储
│   │   ├── stock_basic_repo.py   # 股票基本信息
│   │   ├── stock_kline_repo.py   # K 线数据
│   │   ├── stock_weekly_repo.py  # 周 K 数据
│   │   └── watchlist_repo.py     # 自选股
│   ├── repository/               # 数据仓储
│   │   └── stock_repo.py         # 股票综合仓储
│   ├── config/                   # 配置
│   │   ├── defaults.py           # 默认配置
│   │   └── _settings.py          # 设置加载
│   └── util/                     # 工具
│       ├── retry.py              # 重试机制
│       ├── ttl_cache.py          # TTL 缓存
│       └── trading_calendar.py   # 交易日历
├── templates/                    # 前端页面
│   ├── index.html
│   ├── index-patrol.html
│   ├── index-scan.html
│   └── index-signals.html
├── static/                       # 前端资源
│   ├── css/ (tokens, layout, components)
│   └── js/  (router, sse, chart, store, 20+ modules)
├── config.json                   # 配置文件
├── pyproject.toml                # 项目元数据 + uv
├── requirements.txt              # 依赖
├── uv.lock                       # uv 锁定文件
└── start.sh                      # 启动脚本
```

---

## 安装运行

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 直接运行

```bash
cd "3.1重构版"
uv sync
uv run python src/run.py
# 访问 http://localhost:5000
```

或使用启动脚本：

```bash
bash start.sh           # 前台运行
bash start.sh --bg      # 后台运行 (日志写入 server.log)
bash start.sh --stop    # 停止后台进程
```

### Docker

```bash
cd "3.1重构版"
docker compose up -d --build
```

---

## API 接口

### SSE 流式分析

```javascript
// 1. 先连接 SSE
const es = new EventSource('/api/sse?client_id=your_client_id')

// 2. 监听事件
es.addEventListener('scores_update', e => { /* 更新评分 */ })
es.addEventListener('ai_stream', e => { /* AI 流式输出 */ })
es.addEventListener('final_result', e => { /* 最终结果 */ })

// 3. 发起分析
fetch('/api/analyze_stream', {
  method: 'POST',
  body: JSON.stringify({ stock_code: '600519', client_id: 'your_client_id' })
})
```

### REST 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 健康检查 |
| GET | `/api/sse?client_id=xxx` | SSE 流通道 |
| POST | `/api/analyze_stream` | 单股票流式分析 |
| POST | `/api/analyze` | 单股票同步分析 |
| POST | `/api/batch_analyze_stream` | 批量流式（最多 10 只） |
| POST | `/api/batch_analyze` | 批量同步 |
| GET | `/api/patrol/positions` | 持仓列表 |
| POST | `/api/patrol/positions` | 添加持仓 |
| PUT | `/api/patrol/positions/<id>` | 更新持仓 |
| DELETE | `/api/patrol/positions/<id>` | 删除持仓 |
| GET | `/api/patrol/positions/quotes` | 批量获取报价 |
| POST | `/api/patrol/position/<id>/strategy` | 持仓策略分析 |
| GET | `/api/patrol/position/<id>/analyze` | 持仓 SSE 分析 |
| GET | `/api/signals/market` | 市场信号 |
| GET | `/api/screener/fullscan` | 全市场扫描 |

---

## 核心模块

### StockAnalyzer (`src/core/analyzer.py`)

股票分析引擎：

- 历史 K 线获取（新浪 → yfinance 降级）
- 技术指标计算（RSI、MACD、KDJ、布林带、CCI、OBV 等）
- 基本面评分（AkShare 财报 + 腾讯 PE/PB）
- 三维评分：技术 40% + 基本面 40% + 情绪 20%
- 四层量化信号（L0/L1/L2/L3）
- LLM AI 深度分析（OpenAI 兼容接口）

### 数据源注册表 (`src/data/registry.py`)

多数据源按优先级自动切换，失败时顺次降级：

```python
registry.register(TencentSource())     # 优先级 1
registry.register(AkShareSource())     # 优先级 2
registry.register(EastMoneySource())   # 优先级 3
registry.register(THSSource())         # 优先级 4
```

### 四层量化信号系统

| 层级 | 周期 | 数据源 | 权重 |
|------|------|--------|------|
| L0 超短期 | 5 分钟 K 线 | 新浪 | 20% |
| L1 短期 | 日 K (120 根) | 新浪/yfinance | 30% |
| L2 中期 | 周 K (52 周) | AkShare | 25% |
| L3 长期 | TTM 财报 | AkShare + 腾讯 | 25% |

综合信号范围 `[-2, +2]`，正值看多，负值看空。

### 其他模块

| 模块 | 说明 |
|------|------|
| `chanlun.py` | 缠论分析（分型、均线、背驰、买卖点） |
| `screener.py` | 全市场扫描（条件筛选 A 股） |
| `backtest.py` | 策略回测引擎 |
| `bottleneck_strategy.py` | 瓶颈位突破策略 |
| `news_monitor.py` | 新闻监控与情绪评分 |
| `prepost_review.py` | 盘前计划 / 盘后复盘 |
| `today_prediction.py` | 当日涨跌预测 |
| `signals.py` | 市场信号（热点、龙虎榜、北向资金） |

---

## 配置说明

`config.json` 主要字段：

```json
{
  "api_keys": {
    "openai": "",
    "siliconflow": "",
    "ollama": ""
  },
  "ai": {
    "model_preference": "ollama",
    "models": { "ollama": "minimax-m2.5:cloud" }
  },
  "analysis_weights": {
    "technical": 0.4,
    "fundamental": 0.4,
    "sentiment": 0.2
  },
  "cache": {
    "price_hours": 1,
    "akshare_endpoint_cooldown_seconds": 90
  }
}
```

> ⚠️ **不要提交真实 API Key 到代码仓库。** `config.json` 已在 `.gitignore` 中。

---

## 🏗️ 技术栈

- **后端**：Flask + Python 3.10+
- **数据源**：AkShare、腾讯、新浪、东方财富、同花顺
- **前端**：Vanilla JS + SSE + Plotly
- **缓存**：SQLite + TTL 缓存
- **包管理**：uv
- **AI**：OpenAI / Claude / SiliconFlow / DeepSeek / Ollama / MiniMax

---

## 股票代码格式

| 市场 | 格式 |
|------|------|
| A 股沪市 | `600519` / `sh600519` / `600519.SH` |
| A 股深市 | `000001` / `sz000001` / `000001.SZ` |

> v3.1 仅支持 A 股（沪市/深市），不再支持港股、美股。

---

*最后更新: 2026-07-07*
