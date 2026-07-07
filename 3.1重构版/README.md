# Stock Scanner v3.1 重构版

**状态**: 🚧 开发中 (WIP)  
**不建议用于生产环境** — 重构未完成，部分功能待完善。

---

## 目录

- [概述](#概述)
- [目录结构](#目录结构)
- [技术架构](#技术架构)
- [安装运行](#安装运行)
- [API 接口](#api-接口)
- [数据源](#数据源)
- [核心模块](#核心模块)
- [配置说明](#配置说明)
- [与 v3.0 的区别](#与-v30-的区别)

---

## 概述

v3.1 是对 v3.0 的**模块化重构**版本，主要改进：

- 采用 **DataSource 注册表模式**，统一多数据源（东方财富、同花顺、腾讯、新浪等）
- 路由拆分，职责单一
- 持仓巡检模块独立（SQLite 持久化）
- 四层量化信号系统（L0/L1/L2/L3）
- 策略生成器模块化

> ⚠️ 注意：v3.1 仍处于开发阶段，功能完整性不如 v3.0 稳定。当前 demo 运行的是 v2.6 或 v3.0。

---

## 目录结构

```
3.1重构版/
├── src/
│   ├── run.py                    # Flask 应用入口
│   ├── api/                      # 路由层
│   │   ├── __init__.py
│   │   ├── routes.py             # 路由注册
│   │   ├── analyze_routes.py     # 单股票分析 / SSE 流
│   │   ├── batch_routes.py       # 批量分析
│   │   ├── patrol_routes.py      # 持仓巡检
│   │   ├── signal_routes.py      # 市场信号
│   │   ├── auth.py               # 认证
│   │   └── schemas.py            # 数据校验
│   ├── core/                     # 业务逻辑层
│   │   ├── analyzer.py           # 股票分析引擎
│   │   ├── batch.py              # 批量分析
│   │   ├── patrol.py             # 持仓管理器
│   │   ├── signals.py            # 信号生成器
│   │   ├── strategy_generator.py # 策略生成
│   │   └── events.py             # 事件系统
│   ├── data/                     # 数据源层
│   │   ├── base.py               # DataSource 基类
│   │   ├── registry.py           # 数据源注册表
│   │   ├── akshare.py            # AkShare 源
│   │   ├── yahoo.py              # Yahoo Finance 源
│   │   ├── tencent.py            # 腾讯源
│   │   ├── eastmoney.py          # 东方财富源
│   │   ├── ths.py                # 同花顺源
│   │   ├── baidu.py              # 百度源
│   │   └── patrol.db             # SQLite 数据库
│   ├── storage/                   # 存储层
│   │   ├── sqlite_db.py          # SQLite 连接管理
│   │   └── patrol_repo.py        # 持仓仓储
│   ├── config/                   # 配置层
│   │   ├── defaults.py           # 默认配置
│   │   └── _settings.py          # 设置加载
│   └── __init__.py
├── templates/
│   └── index.html                # 前端页面（内联 JS/CSS）
├── data/
│   └── stocks.db                 # 股票数据
├── config.json                   # 配置文件
├── requirements.txt              # 依赖
└── patrol.db                     # 根目录 SQLite（兼容）
```

---

## 技术架构

### 分层设计

```
┌─────────────────────────────────┐
│      Frontend (templates/)      │  纯 HTML + Vanilla JS
├─────────────────────────────────┤
│    API Routes (src/api/)        │  Flask 路由，职责单一
│   ├─ analyze_routes.py          │  单股票分析 + SSE 流
│   ├─ batch_routes.py            │  批量分析
│   ├─ patrol_routes.py           │  持仓巡检 CRUD
│   └─ signal_routes.py           │  市场信号
├─────────────────────────────────┤
│     Core Logic (src/core/)      │  业务核心
│   ├─ analyzer.py                │  股票分析引擎
│   ├─ signals.py                 │  四层量化信号
│   ├─ strategy_generator.py     │  策略生成
│   └─ patrol.py                  │  持仓管理
├─────────────────────────────────┤
│    Data Layer (src/data/)       │  数据获取
│   ├─ registry.py                │  数据源注册表
│   └─ [akshare|yahoo|ths|...]    │  具体数据源适配器
├─────────────────────────────────┤
│   Storage Layer (src/storage/)  │  持久化
│   └─ sqlite_db.py               │  SQLite 连接
└─────────────────────────────────┘
```

### 四层量化信号系统（L0/L1/L2/L3）

| 层级 | 周期 | 数据源 | 权重 |
|------|------|--------|------|
| L0 超短期 | 5 分钟 K 线 | 新浪财经 | 20% |
| L1 短期 | 日 K (120 根) | 新浪/yfinance | 30% |
| L2 中期 | 周 K (52 周) | AkShare | 25% |
| L3 长期 | TTM 财报 | AkShare + 腾讯 | 25% |

综合信号范围 `[-2, +2]`，正值看多，负值看空。

---

## 安装运行

### 方式一：直接运行

```bash
cd "3.1重构版"
pip install -r requirements.txt
python src/run.py
uv run python src/run.py
# 访问 http://localhost:5000
```

### 方式二：Docker

```bash
cd "3.1重构版"
docker build -t stock-scanner-3.1 .
docker run -p 5000:5000 stock-scanner-3.1
```

### 依赖

```
Flask>=2.2,<3.1
Flask-CORS>=4.0
pandas>=2.0,<3.0
numpy>=1.24,<2.0
akshare>=1.13
openai>=0.28
anthropic>=0.20
zhipuai>=2.0
requests>=2.31
curl_cffi>=0.6.0  # 东方财富 TLS 指纹伪装
plotly>=5.18
gunicorn>=21
```

---

## API 接口

### SSE 流式分析

```javascript
// 1. 先连接 SSE
const es = new EventSource('/api/sse?client_id=your_client_id')

// 2. 监听事件
es.addEventListener('scores_update', e => { /* 更新评分卡片 */ })
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
| GET | `/api/patrol/positions` | 获取持仓列表 |
| POST | `/api/patrol/positions` | 添加持仓 |
| PUT | `/api/patrol/positions/<id>` | 更新持仓 |
| DELETE | `/api/patrol/positions/<id>` | 删除持仓 |
| GET | `/api/patrol/positions/quotes` | 批量获取持仓报价 |
| POST | `/api/patrol/position/<id>/strategy` | 持仓策略分析 |
| GET | `/api/patrol/position/<id>/analyze` | 持仓 SSE 分析 |

---

## 数据源

### 多源注册表

数据源按优先级自动切换，失败时顺次降级：

1. **腾讯** — 实时报价（最高优先级）
2. **AkShare** — A 股财务数据、热点概念、板块轮动

```python
# src/run.py 中注册
from src.data.registry import registry
from src.data.akshare import AkShareSource
from src.data.tencent import TencentSource
from src.data.eastmoney import EastMoneySource
from src.data.ths import THSSource

registry.register(TencentSource())
registry.register(YahooSource())
registry.register(AkShareSource())
registry.register(THSSource())
registry.register(EastMoneySource())
```

### 股票代码格式

| 市场 | 格式示例 |
|------|----------|
| A 股沪市 | `600519`, `sh600519`, `600519.SH` |
| A 股深市 | `000001`, `sz000001`, `000001.SZ` |

> v1.3: 不再支持港股、美股。A 股代码必须为 6 位数字。

---

## 核心模块

### StockAnalyzer (`src/core/analyzer.py`)

股票分析引擎，负责：
- 历史 K 线数据获取（新浪 → yfinance 降级）
- 技术指标计算（RSI、MACD、KDJ、布林带、CCI、OBV 等）
- 基本面数据获取（AkShare 财报摘要 + 腾讯 PE/PB）
- 三维评分（技术 40% + 基本面 40% + 情绪 20%）
- 四层量化信号计算（L0/L1/L2/L3）
- LLM AI 深度分析（OpenAI 兼容接口）

### DataSourceRegistry (`src/data/registry.py`)

数据源注册表，核心类：
```python
class DataSourceRegistry:
    def register(self, source: DataSource) -> None
    def get_quote(self, code: str, market: str) -> Optional[Quote]
    def get_batch_quotes(self, codes: List[str], market: str) -> Dict[str, Quote]
    def health_check(self) -> Dict[str, bool]
```

### PatrolManager (`src/core/patrol.py`)

持仓巡检管理器：
- CRUD 持仓
- 批量获取实时报价
- 计算浮盈亏

### SignalsGenerator (`src/core/signals.py`)

市场信号生成器：
- 热点股票（同花顺）
- 概念板块（百度）
- 资金流向（百度）
- 北向资金（东方财富）
- 龙虎榜（东方财富）
- 研报（东方财富）

---

## 配置说明

`config.json` 结构：

```json
{
  "api_keys": {
    "openai": "",
    "anthropic": "",
    "zhipu": "",
    "deepseek": ""
  },
  "ai": {
    "model_preference": "openai",
    "models": {
      "openai": "gpt-4o-mini",
      "anthropic": "claude-3-haiku",
      "zhipu": "glm-4-flash",
      "deepseek": "deepseek-chat"
    },
    "temperature": 0.7,
    "max_tokens": 2000
  },
  "analysis_weights": {
    "technical": 0.4,
    "fundamental": 0.4,
    "sentiment": 0.2
  },
  "cache": {
    "enabled": false,
    "price_hours": 1,
    "fundamental_hours": 6
  },
  "web_auth": {
    "enabled": false,
    "password": "",
    "session_timeout": 3600
  },
  "data_sources": {
    "tencent": {"enabled": true, "priority": 1},
    "yahoo": {"enabled": true, "priority": 2},
    "akshare": {"enabled": true, "priority": 3}
  },
  "server": {
    "host": "0.0.0.0",
    "port": 5000,
    "threaded": true
  }
}
```

> ⚠️ **不要提交真实 API Key 到代码仓库。**

---

## 与 v3.0 的区别

| 对比项 | v3.0 | v3.1 |
|--------|------|------|
| 代码组织 | 单文件为主 | 模块化分层 |
| 数据源 | AkShare 直接调用 | 注册表 + 多源适配器 |
| 路由 | 集中在一个文件 | 按功能拆分 |
| 持仓持久化 | 无 | SQLite |
| 四层量化信号 | 无 | L0/L1/L2/L3 |
| 策略生成器 | 内嵌 | 独立模块 |
| 状态 | 稳定生产 | 开发中 |

---

## 路线图

- [ ] 完成 `signal_routes.py` 市场信号路由
- [ ] 完善 `batch_routes.py` 批量分析路由
- [ ] 补全 `baidu.py` 数据源实现
- [ ] 增加 WebSocket 支持（替代 SSE）
- [ ] Docker compose 配置
- [ ] 单元测试覆盖

---

*最后更新: 2026-05-21*
