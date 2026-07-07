# Stock Portfolio Manager — Design Doc

**Date:** 2026-06-15
**Author:** office-hours session
**Status:** Draft

---

## 1. Concept & Vision

A local-first AI-augmented stock portfolio management tool for retail investors. Not a broker — a decision-support system. It watches your holdings, runs your analysis strategies through historical backtests, and tells you what to do and why. Built for learning-by-doing: every strategy parameter is tunable, every backtest result is readable.

**Core feeling:** "I have a second brain that watches my portfolio 24/7 and tells me what moves to make."

**Target user:** Individual investor who currently manages positions via broker app and wants a unified tool combining portfolio health overview, AI-driven action guidance, backtest-validated strategy tuning, and real-time news impact analysis.

---

## 2. Design Language

### Color Palette (Dark Theme — investor terminal aesthetic)

```
Background:       #0D1117   (deep charcoal)
Surface:           #161B22   (card background)
Surface Elevated: #21262D   (modal / dropdown)
Border:            #30363D   (subtle dividers)
Text Primary:      #E6EDF3   (high contrast)
Text Secondary:   #8B949E   (labels, hints)
Accent Blue:      #58A6FF   (primary actions, links)
Accent Green:     #3FB950   (profit, buy signal, bullish)
Accent Red:       #F85149   (loss, sell signal, bearish)
Accent Yellow:    #D29922   (hold, warning, caution)
Accent Purple:    #BC8CFF   (news, sentiment)
```

### Typography

- **Headings:** Inter, weight 600
- **Body:** Inter, weight 400
- **Monospace (prices, codes):** JetBrains Mono
- Font scale: 12 / 14 / 16 / 20 / 24 / 32px

### Spacing System

Base unit: 4px. Components use multiples: 4, 8, 12, 16, 24, 32, 48px.

### Motion

- Transitions: 150ms ease-out (micro), 300ms ease-out (page)
- Loading: skeleton shimmer, not spinners
- Charts: animated draw-in on data load
- Modals: fade + scale-in from 95% → 100%

---

## 3. Layout & Structure

### App Shell

```
┌─────────────────────────────────────────────────────┐
│  Sidebar (240px)  │  Main Content Area              │
│  ───────────────  │  ─────────────────────────────  │
│  [Logo]           │  [Header: Page Title + Actions] │
│                   │                                  │
│  Navigation       │  [Page Content]                  │
│  - 持仓总览        │                                  │
│  - 操作指南        │                                  │
│  - 分仓策略        │                                  │
│  - 对冲止损        │                                  │
│  - 回测系统        │                                  │
│  - 实时新闻        │                                  │
│                   │                                  │
│  [Settings]       │                                  │
└─────────────────────────────────────────────────────┘
```

### Page Summary

| Page | Purpose |
|---|---|
| **持仓总览** | All-holdings health dashboard, portfolio score, per-stock status cards |
| **操作指南** | Per-holding action list: buy/sell/hold/T+0 tips per stock |
| **分仓策略** | Capital allocation planner: how much to put in each position |
| **对冲止损** | Hedging recommendations + stop-loss lines per holding |
| **回测系统** | Backtest runner: configure strategy params, run, compare equity curves |
| **实时新闻** | News feed filtered to portfolio holdings, sentiment scores |

### Responsive Strategy

- Desktop-first (1200px+), tablet-friendly (768px+)
- Sidebar collapses to icon rail on <1024px
- Mobile: single-column, bottom navigation bar

---

## 4. Data Architecture

### SQLite Schema

```sql
-- 持仓表
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,           -- 股票代码 600519
    name TEXT,                    -- 股票名称
    market TEXT NOT NULL,         -- SH / SZ / HK / US
    shares REAL NOT NULL,         -- 持仓数量
    cost_price REAL NOT NULL,     -- 成本价
    current_price REAL,           -- 当前价（实时更新）
    project TEXT,                 -- 项目/组合标签
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 回测配置表
CREATE TABLE backtest_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,           -- 配置名称，如 "RSI超卖策略"
    description TEXT,
    params TEXT NOT NULL,          -- JSON: {rsi_buy_threshold: 30, rsi_sell_threshold: 70, ...}
    created_at TEXT DEFAULT (datetime('now'))
);

-- 回测结果表
CREATE TABLE backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    config_id INTEGER REFERENCES backtest_configs(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    final_value REAL NOT NULL,
    total_return_pct REAL,
    sharpe_ratio REAL,
    max_drawdown_pct REAL,
    win_rate REAL,
    metrics TEXT,                 -- JSON: full metrics object
    run_card TEXT,                 -- JSON: full run card
    created_at TEXT DEFAULT (datetime('now'))
);

-- 新闻缓存表
CREATE TABLE news_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    sentiment TEXT,               -- bullish / bearish / neutral
    sentiment_score REAL,          -- -1.0 to 1.0
    published_at TEXT,
    cached_at TEXT DEFAULT (datetime('now'))
);

-- 系统配置表
CREATE TABLE system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```

### Key Design Decisions

1. **params/metrics/run_card stored as JSON** — avoids rigid schema for strategy parameters and backtest metrics; enables schema evolution without migrations.
2. **news_cache is append-only** — refresh per stock on demand, no TTL cleanup unless manually triggered.
3. **No user auth** — local-only, no multi-user.

---

## 5. Module Specifications

### 5.1 持仓总览 (Portfolio Health Dashboard)

**Purpose:** Single-pane view of entire portfolio health.

**UI Components:**
- Portfolio Score Card: large number (0-100), color-coded (green ≥70, yellow 40-69, red <40)
- Score breakdown: technical weight (40%) + fundamental weight (40%) + sentiment weight (20%) — same weighting as existing analyzer
- Holdings Table: per-row status icon (🟢 healthy / 🟡 warning / 🔴 action needed)
- Sector Concentration Bar: horizontal stacked bar showing % allocation per sector
- Mini sparklines: 5-day price trend per holding
- "Last updated" timestamp + refresh button

**Portfolio Score Algorithm:**
```
score = weighted_avg(
    technical_score=avg(technical indicators for all holdings),
    fundamental_score=avg(fundamental scores),
    sentiment_score=avg(news sentiment)
) - concentration_penalty

concentration_penalty: +0 if no single sector > 30%, +10 if one sector 30-50%, +20 if > 50%
```

**Data Flow:**
- React → GET /api/portfolio/summary → Flask → aggregate positions + quotes + scores → JSON response
- Real-time price: AkShare → Flask cache (90s TTL)

**Edge Cases:**
- Empty portfolio: show empty state with "Add your first holding" CTA
- All prices stale (>5min): show warning badge, use last known price with "as of X" label
- API rate limited: graceful degradation to last cached price + error toast

---

### 5.2 操作指南 (Action Guide)

**Purpose:** Per-holding action recommendations.

**UI Components:**
- Action Cards: one card per holding
  - Stock name + code
  - Current price vs cost price
  - Signal: BUY / SELL / HOLD / 做T
  - Confidence: High / Medium / Low
  - AI-generated reasoning paragraph (2-3 sentences)
- Batch actions toolbar: "Apply selected actions" (generates a summary plan)

**Signal Logic (AI-driven, rule-based fallback):**

| Condition | Signal |
|---|---|
| technical_score > 70 AND sentiment_score > 60 | BUY |
| technical_score < 30 OR profit_loss_pct < -10% | SELL |
| technical_score 40-70 AND profit_loss_pct -5% to 10% | HOLD |
| RSI < 30 AND price recovering | 做T (buy the dip) |
| RSI > 70 AND price at peak | 做T (sell partial) |

**做T Sub-types:**
- **买入抄底:** RSI < 30, price within 2% of day's low → "可少量买入"
- **卖出止盈:** RSI > 70, price within 2% of day's high → "可分批卖出"

**AI Integration:**
- Primary: OpenAI/Claude API for natural language reasoning
- Fallback: rule-based signal generator when AI unavailable
- Streaming: SSE for gradual AI response display

**Data Flow:**
- React → GET /api/guides → Flask → StockAnalyzer.analyze_stock (per holding) + signal generator → JSON
- Parallel fetch, max 4 concurrent (thread pool)

---

### 5.3 分仓策略 (Position Sizing)

**Purpose:** Help decide how much capital to allocate across positions.

**UI Components:**
- Capital Allocator: input total capital (RMB) → output allocation table
- Allocation Methods selector:
  - Equal Weight: 1/N per position
  - Risk Parity: equal risk contribution (std dev-based)
  - RSI Inverse: more weight to oversold stocks
  - Custom: manual slider per position
- Allocation Table: Stock | Target % | Amount (RMB) | Shares
- Rebalance Alert: "Current allocation deviates X% from target" when deviation > 5%

**Algorithm — Risk Parity (default):**
```
1. Fetch 20-day volatility (std dev of returns) per holding
2. risk_weight[i] = 1 / volatility[i]
3. normalize: target_pct[i] = risk_weight[i] / sum(risk_weight)
4. allocate: amount[i] = total_cash * target_pct[i]
```

**Algorithm — RSI Inverse:**
```
1. For each holding: score = 100 - RSI (so oversold gets higher score)
2. normalize scores to percentages
3. allocate proportionally
```

**Data Flow:**
- React → POST /api/allocations/calculate → Flask → fetch volatility + RSI per holding → compute allocation → JSON

**Edge Cases:**
- Stock with zero volatility (flat price): exclude from risk parity, distribute to others
- New holding (no 20-day data): use default weight, show "insufficient data" badge
- Total allocation ≠ 100%: normalize to 100%, show adjustment note

---

### 5.4 对冲止损 (Hedging & Stop-Loss)

**Purpose:** Recommend hedging instruments and stop-loss levels.

**UI Components:**
- Stop-Loss Table: per holding — Current Price | Stop-Loss Price | Trailing Stop | Risk/Reward Ratio
- Stop-Loss Method selector:
  - Fixed %: user-configurable % below cost (default 7%)
  - ATR-based: current price - 2×ATR(14)
  - Support-based: nearest support level (from data)
- Hedging Recommendations:
  - Card per holding: "If you hold 1000 shares of 600519, consider:"
    - Buy 沪深300 put (OTM -5%) as hedge
    - Estimated cost: ¥X
    - Break-even hedge: if 600519 drops 10%, hedge gains ~Y%
  - Hedge instrument: 沪深300 ETF options (simplified — actual options API not available locally)
- Overall Portfolio Hedge Summary: total hedge cost vs potential protection

**Stop-Loss Calculation:**
```
Fixed:     stop_price = cost_price * (1 - stop_loss_pct)
ATR-based: stop_price = current_price - 2 * ATR(14)
Support:  stop_price = nearest_support_level_below_current
```

**Data Flow:**
- React → GET /api/hedges → Flask → fetch ATR, support levels, option prices → compute hedges
- ATR from existing technical indicators module
- Support level: scan 20/50/200-day moving averages for nearest below price

**Edge Cases:**
- HK/US stocks: ATR-based stop-loss only (no Chinese support level data)
- Hedge cost > 5% of position value: flag as "expensive hedge" warning
- No options data available: show "hedge not available" with explanation

---

### 5.5 回测系统 (Backtest System)

**Purpose:** Validate analysis strategy on historical data, tune parameters, compare results.

**UI Components:**
- Strategy Configurator:
  - Select from saved configs or create new
  - Parameters form: RSI thresholds, moving average periods, weight presets
  - Date range picker: start date, end date
  - Initial capital input
- Run Control: "Run Backtest" button + progress indicator
- Results Dashboard (post-run):
  - Equity Curve (line chart: strategy vs buy-and-hold)
  - Key Metrics Cards: Total Return %, Sharpe Ratio, Max Drawdown %, Win Rate, # Trades
  - Trade Log Table: Date | Action | Price | Shares | P&L
  - Run Card (markdown): reproducibility info, config hash
- Compare Mode: select 2+ past runs → overlay equity curves
- Parameter Optimization: run batch backtests across parameter ranges → heatmap of Sharpe by params

**Backtest Engine:**
- Reuse Vibe-Trading's `ChinaAEngine` (A股T+1, ±10% price limit, commission ¥5 min, 0.025% bilateral, 0.05% stamp tax sell-only, transfer fee 0.001%)
- Data loader: AkShare (already used in stock-scanner) via `backtest/loaders/akshare_loader.py` from Vibe-Trading
- Integration: copy Vibe-Trading backtest engine files as a submodule or vendored library

**Signal Generation for Backtest:**
- Same signal logic as 5.2 (BUY/SELL/HOLD) fed into backtest engine
- Engine executes simulated trades on historical data
- Metrics computed via `backtest/metrics.py` from Vibe-Trading

**Data Flow:**
- React → POST /api/backtest/run → Flask → load historical data via AkShare → run ChinaAEngine → compute metrics → store results → SSE progress stream → final JSON with metrics + equity curve data points
- Equity curve: array of `{date, portfolio_value, benchmark_value}` for charting

**Edge Cases:**
- Missing historical data for a stock: skip stock, log warning, continue
- Date range too short (<30 days): warn that results may be unreliable
- No trades generated: show "no signals triggered" message, not an error

---

### 5.6 实时新闻 (Real-Time News)

**Purpose:** Filtered news feed for portfolio holdings with sentiment scoring.

**UI Components:**
- News Feed: infinite scroll list
  - Each item: headline + source + time + sentiment badge (🟢 bullish / 🔴 bearish / ⚪ neutral) + affected holdings tags
  - Sentiment score bar: visual -1.0 → +1.0 scale
- Filter Toolbar: by holding / by sentiment / by date range
- Alert Settings: per-holding toggle "Alert on news"
- Impact Panel (sidebar on desktop): when news item selected → shows which holdings it affects + AI-generated impact summary

**News Sources (in priority order):**
1. EastMoney (免费, already in stock-scanner)
2. Sina Finance
3. If above fail: cached news from news_cache table

**Sentiment Scoring:**
- Rule-based keyword scoring (简单baseline): positive words (利好, 增长, 突破) → +1, negative (利空, 下跌, 风险) → -1
- AI scoring when API available: prompt "Is this news bullish or bearish for {stock_code}? Score -1 to +1"
- Cached for 1 hour per stock

**Data Flow:**
- React → GET /api/news?codes=600519,000001 → Flask → fetch from EastMoney/Sina → score sentiment → return sorted list
- React polls every 5 minutes OR uses SSE push on new significant news

**Edge Cases:**
- No news for a holding: show "No recent news" with last cached date
- API failure: fall back to cached news, show "using cached data" badge
- Rate limited: queue requests, spread over time, show loading skeleton

---

## 6. Technical Architecture

### Frontend (React + Vite + TypeScript)

```
src/
├── components/          # Reusable UI components
│   ├── ui/              # Primitives: Button, Card, Badge, Modal, Skeleton
│   ├── charts/          # EquityCurve, Sparkline, SentimentBar
│   └── layout/          # AppShell, Sidebar, Header
├── pages/               # Route-level page components
│   ├── Portfolio.tsx    # 持仓总览
│   ├── ActionGuide.tsx  # 操作指南
│   ├── Allocation.tsx   # 分仓策略
│   ├── Hedge.tsx        # 对冲止损
│   ├── Backtest.tsx     # 回测系统
│   └── News.tsx         # 实时新闻
├── hooks/               # Custom hooks: useApi, useSSE, usePortfolio
├── stores/             # Zustand stores: portfolioStore, backtestStore
├── lib/                 # API client, SSE client, formatters
├── locales/            # i18n (zh-CN default)
└── types/              # TypeScript interfaces
```

**State Management:** Zustand (lightweight, good for this scale)

**Charting:** Recharts (React-native, composable)

**Build:** Vite, output to `dist/`

### Backend (Flask)

```
src/
├── api/                  # Flask route modules
│   ├── routes.py         # Health, status
│   ├── portfolio_routes.py
│   ├── guide_routes.py
│   ├── allocation_routes.py
│   ├── hedge_routes.py
│   ├── backtest_routes.py
│   └── news_routes.py
├── core/                 # Business logic
│   ├── analyzer.py       # StockAnalyzer (from stock-scanner)
│   ├── signals.py        # SignalsGenerator (from stock-scanner)
│   ├── portfolio.py     # Portfolio health scoring
│   ├── guide_generator.py # Action guide generation
│   ├── allocation.py    # Position sizing algorithms
│   ├── hedge.py         # Stop-loss + hedge calculation
│   └── chan_theory.py   # 缠论 (from stock-scanner)
├── backtest/             # Vendored from Vibe-Trading
│   ├── engines/
│   │   └── china_a.py   # ChinaAEngine
│   ├── loaders/
│   │   └── akshare_loader.py
│   ├── metrics.py
│   ├── runner.py
│   └── run_card.py
├── data/                 # Data sources
│   ├── registry.py      # DataSourceRegistry (from stock-scanner)
│   ├── akshare_*.py     # AkShare integrations
│   └── news_*.py       # News fetchers
├── storage/              # SQLite persistence
│   ├── sqlite_db.py
│   ├── patrol_repo.py   # Position CRUD
│   ├── backtest_repo.py # Backtest config + result CRUD
│   └── news_cache.py
└── run.py               # Flask app entry point
```

### API Design

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | Health check |
| GET | `/api/portfolio/summary` | Portfolio health summary |
| GET | `/api/portfolio/positions` | All positions with current quotes |
| POST | `/api/portfolio/positions` | Add position |
| PUT | `/api/portfolio/positions/:id` | Update position |
| DELETE | `/api/portfolio/positions/:id` | Delete position |
| GET | `/api/guides` | Action guide for all holdings |
| POST | `/api/allocations/calculate` | Calculate allocation |
| GET | `/api/hedges` | Stop-loss + hedge recommendations |
| POST | `/api/backtest/run` | Start backtest run |
| GET | `/api/backtest/runs` | List past backtest runs |
| GET | `/api/backtest/runs/:id` | Get run details + equity curve |
| GET | `/api/backtest/configs` | List saved configs |
| POST | `/api/backtest/configs` | Save new config |
| GET | `/api/news` | News feed |
| GET | `/api/sse` | SSE stream for real-time updates |

### SSE Events

```
event: portfolio_update     # periodic price refresh (30s)
event: news_alert          # significant news for a holding
event: backtest_progress   # backtest run progress
event: ai_stream           # AI analysis chunks
```

---

## 7. Build & Deployment

### Local Development

```bash
# Backend
cd backend
uv venv
uv sync
uv run python src/run.py  # http://localhost:5000

# Frontend
cd frontend
npm install
npm run dev               # http://localhost:5173

# Proxy: Vite dev server proxies /api/* to :5000
```

### Production Build

```bash
# Backend
cd backend
uv build  # or: pip install -e .

# Frontend
cd frontend
npm run build   # outputs to frontend/dist/

# Single-command startup (local)
cd stock-portfolio-manager
uv run python backend/src/run.py   # serves static files from frontend/dist/
```

### Docker (Optional, for future cloud deployment)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY backend/ /app/backend/
COPY frontend/dist/ /app/frontend/dist/
RUN pip install -r backend/requirements.txt
EXPOSE 5000
CMD ["python", "backend/src/run.py"]
```

---

## 8. Implementation Phases

### Phase 1: Foundation (weeks 1-2)
- Project scaffolding: React + Vite + Flask
- SQLite schema + basic CRUD for positions
- Portfolio summary page with static data
- App shell with sidebar navigation

### Phase 2: Real Data (weeks 3-4)
- Connect AkShare data feeds
- Price refresh + sparklines
- Portfolio health score (technical + fundamental + sentiment)
- Holdings table with status indicators

### Phase 3: Action Guide (weeks 5-6)
- Signal generation (BUY/SELL/HOLD/做T)
- AI integration with rule-based fallback
- Action guide page with confidence scores
- SSE for streaming AI responses

### Phase 4: Position Sizing (week 7)
- Allocation calculator (Equal Weight + Risk Parity + RSI Inverse)
- Rebalance alerts
-分仓策略 page

### Phase 5: Stop-Loss + Hedge (week 8)
- Stop-loss calculation (Fixed + ATR + Support)
- Hedge recommendation engine
- 对冲止损 page

### Phase 6: Backtest System (weeks 9-11)
- Vendored Vibe-Trading backtest engine integration
- Backtest configurator + runner
- Results dashboard with equity curve charts
- Parameter optimization batch runs
- 回测系统 page

### Phase 7: News (weeks 12-13)
- News fetcher (EastMoney + Sina)
- Sentiment scoring (rule-based + AI)
- News feed page with filters + alerts
- 实时新闻 page

### Phase 8: Polish & Learn (week 14+)
- Error handling + edge case UX
- Performance: caching, async loading states
- Documentation for learning

---

## 9. Key Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| AkShare rate limits break live prices | High | High | 90s cache TTL, graceful degradation to last price |
| AI API costs accumulate | Medium | Medium | Rule-based fallback when AI unavailable |
| Backtest overfitting (curve-fit to history) | Medium | High | Warn user: "past performance ≠ future results", show benchmark |
| News sentiment mis-scoring | Medium | Medium | Show confidence level, allow user to correct feedback |
| Complex integration with Vibe-Trading engine | Medium | Medium | Vendor engine as-is, minimal modifications, add tests |
| T+1 rule complexity in backtest | Low | High | ChinaAEngine already handles this; reuse directly |

---

## 10. Open Questions

1. **News source cost:** 财联社 API is paid. Use EastMoney (free) as primary. Confirm this is acceptable.
2. **Hedge instruments:** Actual options data requires broker API or paid service. Recommend 沪深300 ETF as proxy. User confirmation needed on approach.
3. **Backtest data scope:** A-share historical data via AkShare goes back ~5 years. Sufficient for most strategies?
4. **AI model choice:** OpenAI GPT / Claude / SiliconFlow — which do you have API keys for?
5. **Initial capital for backtest:** Default to ¥100,000 or user-configurable per run?

---

## The Assignment

Before our next session:

1. **Decide AI model** to use (OpenAI / Claude / SiliconFlow) — this affects API client setup
2. **Confirm news source** — EastMoney free API as primary (vs paid 财联社)
3. **Clone Vibe-Trading backtest engine** — copy `agent/backtest/` to new project as vendored library
4. **Start Phase 1 scaffolding** — set up React + Vite project and Flask project structure

---

## Appendix: Reference Designs

- Vibe-Trading frontend: `/Users/apple/Downloads/vscode_space/Vibe-Trading/frontend/src/pages/` — React TSX patterns, component structure
- Vibe-Trading backtest: `/Users/apple/Downloads/vscode_space/Vibe-Trading/agent/backtest/` — engine, metrics, loaders
- stock-scanner analyzer: `/Users/apple/Downloads/vscode_space/stock-scanner/src/core/analyzer.py` — StockAnalyzer patterns
- stock-scanner patrol: `/Users/apple/Downloads/vscode_space/stock-scanner/src/storage/patrol_repo.py` — SQLite CRUD patterns