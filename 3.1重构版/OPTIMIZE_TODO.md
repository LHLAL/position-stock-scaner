# 优化 TODO

## P0 · 高优先级

### 1. numba 加速 numpy 计算
安装 `numba` 包，用 `@jit` 装饰热点计算函数（`_compute_mytt_fast` 等），预计加速 3-5x。

```bash
.venv/bin/pip install numba
```

然后在 `src/core/analyzer.py` 的 `_compute_mytt_fast` 函数加 `@jit(nopython=True)`。

### 2. 分钟 K 线 SQLite 缓存
跟周 K 线（`stock_weekly_repo.py`）同样模式：
- `src/storage/sqlite_db.py` 加 `stock_minute_kline` 表
- `src/storage/stock_minute_repo.py` 封装 get/upsert
- `stock_repo.py` 的 `get_minute_kline` 改为 SQLite 优先

## P1 · 中等优先级

### 3. analyze_stock 内部的 data fetch 缓存
`analyze_stock` 内部多次调用 `get_stock_data`/`get_quote`（分别拉日K、周K、分钟K、实时报价）。目前周 K 已缓存，还有分钟 K 未缓存，实时报价已由 StockCache 每 60s 刷新。

### 4. 首个 1D/5D 周期加载优化
当前 `days=5` 时 SQLite 查询 5 条数据约 5s（全表扫描），可选加 SQL 索引优化或使用 `LIMIT` 代替 `date >=` 过滤。

### 5. 市场情绪数据补全
`/api/sentiment/market` 当前只返回 `advance_decline` + `north`，前端预留了板块/资金流/政策情绪占位，需要对接外部数据源：

| 前端显示项 | 所需数据 | 建议数据源 | 工作量 |
|-----------|---------|-----------|--------|
| 领涨/跌板块 | THS 行业板块涨跌幅排行 | `ak.stock_board_industry_summary_ths()` 或 EastMoney HTTP | ~2h |
| 主力流入/出板块 | 板块级资金流向 | `push2.eastmoney.com` 板块资金流接口 | ~3h |
| 时政/政策新闻情绪 | 新闻抓取 + AI 情绪打分 + 板块映射 | `src/data/news.py` 已有新闻源，需增加板块关联逻辑 | ~2天 |
| 指数行情 | 上证/深证/创业板指数 | 腾讯行情 `get_quote('000001', 'SH')` 等 | ~1h |
| 情绪温度/情绪标签 | 涨跌比 + 成交量 + 新闻情绪综合 | 已有 `advance_decline` 可计算基础温度 | ~1h |

**实施建议**：从简单的做起——指数行情和板块排行 3 小时能做完，新闻情绪需要较多开发。

## P2 · 低优先级

### 6. 前端 loading 态优化
- 页面加载时显示骨架屏 + “正在分析（约需 1-2 分钟）”等提示
- 指标逐步更新（基础指标→MyTT→四层信号→回测）

### 7. 预热状态指示器
在状态栏显示”预热中 (3/7)”，”缓存就绪”等提示，让用户知道后台正在算。

## 完成项 ✓
- [x] MyTT 数据量 365→180 天
- [x] K 线优先读 SQLite（92万行）
- [x] K 线图 API +300s 缓存
- [x] 回测 API +300s 缓存
- [x] 四层信号独立懒加载
- [x] 周 K 线 SQLite 缓存
- [x] 启动并行预热（7只）
- [x] 前端异步拉四层信号
