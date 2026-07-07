# 🚀 AI 增强股票分析系统

AI 增强的 A 股分析系统，集成多维技术指标、基本面评分、新闻情绪分析与 AI 深度解读。支持多种 AI 模型（OpenAI、Claude、SiliconFlow 等），提供 Web 界面 + SSE 实时流式推送。

## ✨ 核心特性

### 🎯 多维度分析
- **技术面**：RSI、MACD、KDJ、布林带、CCI、OBV 等 20+ 指标
- **基本面**：盈利能力、偿债能力、营运能力、发展能力、市场表现
- **情绪面**：新闻、公告、研报情绪挖掘，支持 100+ 条新闻分析
- **AI 解读**：多模型深度分析，提供专业投资建议

### 🤖 AI 能力
- **多模型**：OpenAI、Claude、智谱、SiliconFlow、DeepSeek、MiniMax
- **主备切换**：API 自动降级，确保服务可用
- **流式推理**：SSE 实时推送 AI 分析过程
- **规则降级**：AI 不可用时自动降级到规则分析

### 📈 量化信号
- **四层信号系统**：L0 超短期 / L1 短期 / L2 中期 / L3 长期
- **综合评分**：技术 40% + 基本面 40% + 情绪 20%
- **策略生成**：基于量化信号的买卖策略建议

### 🔐 工程特性
- **线程池**：`max_workers=4`，Flask `threaded=True` 并发处理
- **数据缓存**：智能缓存减少 API 调用，端点冷却防限频
- **密码鉴权**：Web 端支持密码保护 + 会话管理
- **Docker 部署**：容器化一键启动

## 🚀 快速开始

### 环境要求

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) 包管理器

### 1. 进入目录

```bash
cd "3.1重构版"
```

### 2. 安装依赖

```bash
uv sync
```

### 3. 配置 API Key

```bash
cp config.json config.json.bak  # 备份（如有）
```

编辑 `3.1重构版/config.json`，填入你的 API Key：

| 字段 | 说明 |
|---|---|
| `api_keys.openai` | OpenAI API Key |
| `api_keys.siliconflow` | SiliconFlow API Key（免费可选） |
| `api_keys.ollama` | Ollama（本地，无需 Key） |
| `ai.model_preference` | 主模型：`ollama` / `openai` / `siliconflow` |

> **最低启动**：配置 `api_keys.ollama` 任意值 + `ai.model_preference = "ollama"`，系统会降级到规则分析模式。

### 4. 启动服务

```bash
# 前台运行（开发调试）
uv run python src/run.py

# 或使用启动脚本
bash start.sh           # 前台
bash start.sh --bg      # 后台运行
```

访问 **http://localhost:5000**

### Docker 部署

```bash
cd "3.1重构版"
docker build -t stock-scanner .
docker run -p 5000:5000 stock-scanner
```

## 📁 项目结构

```
stock-scanner/
├── 3.1重构版/                  # 当前活跃版本
│   ├── src/
│   │   ├── run.py              # Flask 入口
│   │   ├── api/                # 路由层
│   │   ├── core/               # 业务逻辑（分析器/信号/策略）
│   │   ├── data/               # 数据源（注册表模式）
│   │   ├── storage/            # SQLite 持久化
│   │   └── repository/         # 数据仓储
│   ├── templates/              # 前端页面
│   ├── static/                 # CSS / JS
│   ├── config.json             # 配置文件
│   └── start.sh                # 启动脚本
├── tests/                      # 测试
├── docs/                       # 文档
├── designs/                    # 设计文档
└── cankao/                     # 参考项目（本地）
```

## 📊 股票代码格式

系统自动识别市场：

| 市场 | 格式 |
|------|------|
| A 股沪市 | `600519` / `sh600519` / `600519.SH` |
| A 股深市 | `000001` / `sz000001` / `000001.SZ` |

## 🔌 API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 健康检查 |
| GET | `/api/sse?client_id=xxx` | 打开 SSE 通道 |
| POST | `/api/analyze_stream` | 单股票流式分析 |
| POST | `/api/analyze` | 单股票同步分析 |
| POST | `/api/batch_analyze_stream` | 批量流式（最多 10 只） |
| GET | `/api/patrol/positions` | 持仓列表 |
| POST | `/api/patrol/positions` | 添加持仓 |
| GET | `/api/patrol/positions/quotes` | 批量获取报价 |

**SSE 流程**：先 `GET /api/sse?client_id=xxx` → 再用相同 `client_id` POST 分析。

## ⚙️ 配置

`3.1重构版/config.json` 主要字段：

```json
{
  "api_keys": { "openai": "", "siliconflow": "" },
  "ai": {
    "model_preference": "ollama",
    "models": { "ollama": "minimax-m2.5:cloud" }
  },
  "analysis_weights": { "technical": 0.4, "fundamental": 0.4, "sentiment": 0.2 },
  "cache": { "akshare_endpoint_cooldown_seconds": 90 }
}
```

> ⚠️ **不要提交真实 API Key 到代码仓库。** `config.json` 已在 `.gitignore` 中。
> 完整配置说明见 `3.1重构版/README.md`。

## 📜 技术栈

- **后端**：Flask + Python 3.10+
- **数据源**：AkShare、腾讯、新浪、东方财富、同花顺（注册表模式）
- **前端**：Vanilla JS + SSE + Plotly 图表
- **缓存**：SQLite + TTL 缓存
- **包管理**：uv
- **AI**：OpenAI / Claude / SiliconFlow / DeepSeek / Ollama

## 🏗️ 架构

```
Frontend (templates/)  ←SSE→  API Routes (src/api/)
                                  ↓
                            Core Logic (src/core/)
                                  ↓
               Data Layer (src/data/) — 注册表模式
               Storage Layer (src/storage/) — SQLite
```

### 四层量化信号

| 层级 | 周期 | 数据源 | 权重 |
|------|------|--------|------|
| L0 超短期 | 5 分钟 K 线 | 新浪 | 20% |
| L1 短期 | 日 K (120 根) | 新浪/yfinance | 30% |
| L2 中期 | 周 K (52 周) | AkShare | 25% |
| L3 长期 | TTM 财报 | AkShare + 腾讯 | 25% |

综合信号范围 `[-2, +2]`，正值看多，负值看空。

## ⚠️ 注意事项

- **SSE 要求 client_id 一致**：先连接 SSE 再用相同 ID 发起分析
- **重复分析限流**：同一股票同时只能有一个进行中的任务
- **NaN 处理**：分析器会在序列化前自动去除 NaN
- **AkShare 限频**：端点冷却默认 90 秒
- **A 股专用**：3.1 重构版仅支持 A 股（沪/深）

## 💰 支持项目

🔗 [请我喝奶茶](https://juanzen.linzefeng.top/)
