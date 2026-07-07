# 优化策略：AI 深度分析 — 操盘有效性提升

## 一、审核结论

经过 CEO 策略审核 + 工程审核双视角分析，发现 **13 个问题**（5 Critical, 4 High, 3 Medium, 1 Low）。

**核心矛盾**：当前 AI 深度分析管线的根因不是 prompt 写不好，而是：

1. **假数据喂给 AI** → 分析基于虚构基本面，不可信
2. **假数据推高评分** → 数据缺失的股票反而获得最高基本面分
3. **管线和产品脱节** → Patrol 深度分析返回硬编码 stub
4. **16 节报告在 2000 token 下无法有实质内容**

---

## 二、决策审计

| # | 阶段 | 决策 | 分类 | 原则 | 理由 |
|---|------|------|------|------|------|
| 1 | CEO | 先修数据，再优化 prompt | 前提确认(用户决策) | — | 假数据使任何 prompt 优化无效 |
| 2 | CEO | 压缩 16 节报告为 3-5 结构化字段 | 自动决策 | P1 完整性 | 数学上不可能在 2000 token 内有实质内容 |
| 3 | CEO | 注入四步定量信号到 AI 上下文 | 自动决策 | P2 煮沸湖泊 | L0/L1/L2/L3 已计算但未使用，0 成本接入 |
| 4 | CEO | 提升 GPT-4o-mini max_tokens 到 4000 | 自动决策 | P1 完整性 | 当前 2000 严重不足 |
| 5 | CEO | Wire patrol 深度分析到真实 LLM 管线 | 自动决策 | P1 完整性 | 硬编码 stub 对用户毫无价值 |
| 6 | CEO | 情绪分析用 AI 替代关键词计数 | 自动决策 | P1 完整性 | 关键词计数的置信度是编造的 |
| 7 | CEO | 增加 LLM API 调用重试 | 自动决策 | P3 务实 | 开盘时段限流是常态 |
| 8 | CEO | 将 API key 移至环境变量 | 自动决策 | P5 明确 > 聪明 | config.json 明文存 key 是安全风险 |
| 9 | Eng | 修复 `_f()` → `ext.get()` | 自动决策 | P4 DRY | copy-paste 遗留 bug，ext 已有数据 |
| 10 | Eng | 添加 PLACEHOLDER 哨兵 | 自动决策 | P1 完整性 | 防假数据泄漏到评分和 AI |
| 11 | Eng | 减少报告验证条件（从 16 降到 5） | 自动决策 | P5 明确 > 聪明 | 验证太严格导致修复循环频繁触发 |
| 12 | Eng | 增加新闻截断（100 字/条） | 自动决策 | P3 务实 | 防 prompt injection |
| 13 | Eng | 共享线程池替代每次请求创建 | 自动决策 | P4 DRY | per-request 线程池浪费资源 |

---

## 三、Cross-Phase Themes — 高置信度信号

**主题 1: 数据质量是首要问题** — CEO 和 Eng 双视角审计一致认为是 Critical。PLACEHOLDER 不仅泄漏假数据到 AI，还系统性推高基本面评分。这使整个 AI 分析不可信。

**主题 2: 16 节格式不可持续** — CEO（策略层面）和 Eng（实现层面）都认为格式过于冗长且 token 预算不允许实质内容。需要从"生成完整报告"转变为"给出可操建议"。

**主题 3: Latency 被忽略** — CEO 指出竞品（TradingView, 雪球, 同花顺 AI）秒级响应，60-120s 的单股分析在交易场景下不可接受。Eng 指出 collect-then-replay 模式消除了 streaming 的 UX 优势。

---

## 四、实施路线图

### Phase 1: 数据质量修复（最高优先级, ~2天）

| 任务 | 文件 | 改动 | 理由 |
|------|------|------|------|
| P1.1 修复 `_f()` bug | `analyzer.py:1393-1397` | `_f(N)` → `ext.get('key')` | 5 分钟改动，恢复 PE/PB/市值数据 |
| P1.2 添加 PLACEHOLDER 哨兵 | `fundamental.py:91-92` | 返回 `data_unavailable=True` | 阻止假数据泄漏 |
| P1.3 基本面评分修 | `analyzer.py:557-586` | 检查 `data_unavailable`，不加 indicator-count bonus | 防止数据缺失时评分虚高 |
| P1.4 AI prompt 假数据门 | `analyzer.py:1339-1343` | data_unavailable 时显示"财务数据暂不可用" | AI 不再基于假数据编造 |
| P1.5 新闻截断 | `analyzer.py:1424-1426` | 每条新闻标题截断 100 字 | prompt injection 防护 |

### Phase 2: 报告格式重构（高优先级, ~1天）

| 任务 | 文件 | 改动 | 理由 |
|------|------|------|------|
| P2.1 重新设计输出格式 | `analyzer.py` | 从 16 节 Markdown → 3-5 结构化 JSON | 确保每部分有实质内容 |
| P2.2 注入四步定量信号 | `analyzer.py:_build_ai_prompt` | 加入 L0/L1/L2/L3 结果 | 最有价值的结构化数据 |
| P2.3 降低验证门槛 | `analyzer.py:_validate_ai_report` | 从 16 个检查降到 5 个关键检查 | 减少修复循环触发 |
| P2.4 提升 max_tokens 到 4000 | `config/defaults.py` | 2000 → 4000 | 给实质性分析留空间 |
| P2.5 实现渐进式 streaming | `analyzer.py:generate_ai_analysis` | 先快速出结论卡，再流式完整报告 | 用户 5 秒内看到核心结论 |

### Phase 3: 产品一致性（高优先级, ~1天）

| 任务 | 文件 | 改动 | 理由 |
|------|------|------|------|
| P3.1 Wire patrol 深度分析 | `patrol_routes.py:354-402` | 调用真实 LLM 管线 | 消除 #1 用户面问题 |
| P3.2 非流式端点加 AI 报告 | `analyze_routes.py:532` | 添加 `generate_ai_analysis` 调用 | API 行为一致 |
| P3.3 共享线程池 | `analyze_routes.py:522-523` | 模块级 `ThreadPoolExecutor(max_workers=4)` | 资源效率 |

### Phase 4: 弹性与可靠性（中等优先级, ~1天）

| 任务 | 文件 | 改动 | 理由 |
|------|------|------|------|
| P4.1 LLM API 重试 | `analyzer.py:_call_llm` | 3 次指数退避重试(1s,4s,15s) | 开盘限流容错 |
| P4.2 API key 环境变量 | `analyzer.py:_call_llm` | `os.environ.get()` 优先 | 安全 |
| P4.3 创建测试 | `tests/` | `test_ai_pipeline.py`, `test_fundamental.py` | 防回归 |

---

## 五、实施建议

### 推荐执行顺序

```
Phase 1 (数据质量) → Phase 2 (格式重构) → Phase 3 (产品一致性) → Phase 4 (弹性)
```

Phase 1 必须先做，否则后面的优化都基于假数据。P1.1 (修复 `_f()`) 只需 5 分钟，立竿见影。

### 不做的事项（明确排除）
- 不修改量化评分模型权重（但修 PLACEHOLDER 后基本面分自动变真实）
- 不增加新数据源（但修 `_f()` 后现有扩展行情数据恢复正常）
- 不修改缠论/信号生成逻辑
- 不重构非 AI 后端架构

### 预期的效果
一旦实施完毕：
- **可信度提升**：AI 不再基于虚构财务数据做分析
- **速度提升**：渐进式 streaming 让用户 5 秒内看到结论
- **操作导向**：从 16 节研究报告 → 3 块可操建议（买卖/风险/机会）
- **数据利用**：四步定量信号被 AI 纳入分析，提升建议质量
- **错误恢复**：API 限流自动重试，数据缺失时诚实标注而非编造
- **产品一致**：Patrol 深度分析不再返回硬编码 stub

---

## 六、遗留问题

- 情绪分析仍是关键词计数——若用户反馈正面，后续可升级为 AI 驱动情绪
- 延时平均 ~30s——后续可考虑 Patrol 位置背景预计算
- 无端到端测试——Phase 4 补基础测试，端到端 SSE 测试需后续投入
