// app.js · v1.2 · 2026-06-14
// 应用入口 —— 初始化 store + SSE + 侧栏，挂 4 态切换 JS
//
// 加载顺序（在 index-v2.html 里）：
//   <script type="module" src="/static/js/app.js"></script>

import { store } from './store.js';
import { sse }   from './sse.js';
import { logger } from './logger.js';
import { toast } from './toast.js';
import { initSidebar } from './sidebar.js?v=20260617-route-sync';
import { chart }  from './chart.js?v=20260630-kline-color';
import { initAIPanel, ai } from './ai-panel.js?v=20260629-dedup';
import { signals } from './signals.js?v=20260628-speed';
import { table }  from './table.js?v=20260617-finance-empty';
import { market } from './market.js?v=20260628-sentiment';
import { cmdk }   from './cmdk.js';
import { perf }   from './perf.js';
import { initSplitter } from './splitter.js';
import { initTheme }    from './theme.js';
import { initRouter, navigate } from './router.js';
// v1.1 场景模块（按需 import）
import { scan }        from './scan.js?v=20260617-route-sync';
import { patrolPage }  from './patrol-page.js?v=20260701-pnl-flash';
import { signalsPage } from './signals-page.js';
import { reviewPage }  from './review-page.js';
import { init as initBottleneckPage } from './bottleneck-page.js';

// ── 4 态切换（业务事件驱动，v1.1 由 chart/signals/table 模块自动 setCardState） ──
//    demo 按钮已删除（v1 完成态）

// ── 新闻通知处理 ──────────────────────────

/**
 * 更新后端要监控的股票列表（持仓 + 自选）
 */
async function updateMonitoredStocks() {
  const positions = store.get('positions') || [];
  const watchlist = store.get('watchlist') || [];

  try {
    const resp = await fetch('/api/news/update_monitored_stocks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions, watchlist }),
    });
    if (!resp.ok) {
      logger.warn(`更新监控股票失败: HTTP ${resp.status}`);
      return;
    }
    const data = await resp.json();
    if (data.success) {
      logger.info(data.message);
    }
  } catch (e) {
    if (e.name !== 'AbortError') {
      logger.warn(`更新监控股票失败: ${e.message}`);
    }
  }
}

function initNewsAlerts() {
  // 监听新闻提醒事件
  sse.on('news_alert', (data) => {
    if (!data) return;

    // 映射 impact_type 到 toast 类型
    const typeMap = {
      'positive': 'success',  // 利好 -> 成功（红色）
      'negative': 'error',    // 利空 -> 错误（绿色）
      'neutral': 'info',
    };

    const type = typeMap[data.impact_type] || 'info';
    const stocks = data.related_stocks || [];

    // 显示 toast
    toast[type](
      data.title || '新闻提醒',
      data.content || '',
      {
        url: data.url,
        stocks: stocks,
        duration: data.importance >= 4 ? 10000 : 6000,
      }
    );

    // 记录到事件日志
    const events = store.get('events') || [];
    events.unshift({
      ts: Date.now(),
      type: `news_${data.impact_type}`,
      message: data.title,
      data: data,
    });
    if (events.length > 100) events.length = 100;
    store.set('events', events);
  });

  // SSE 连接成功后，更新要监控的股票列表
  sse.on('connected', () => {
    setTimeout(updateMonitoredStocks, 1000);
  });

  // 监听持仓/自选变化，更新监控股票列表
  store.on('positions', updateMonitoredStocks);
  store.on('watchlist', updateMonitoredStocks);

  logger.info('新闻通知模块已初始化');
}

// ── 事件日志面板 ──────────────────────────
function initEventsPanel() {
  const btn = document.getElementById('btn-events');
  const headerAlertsBtn = document.getElementById('btn-header-alerts');
  const panel = document.getElementById('events-panel');
  const closeBtn = document.getElementById('btn-close-events');
  const body = document.getElementById('events-body');

  if (!btn || !panel || !closeBtn || !body) return;

  // 切换面板显示
  function togglePanel(show) {
    const isHidden = panel.hasAttribute('hidden');
    const shouldShow = show !== undefined ? show : isHidden;

    if (shouldShow) {
      document.getElementById('settings-panel')?.setAttribute('hidden', '');
      panel.removeAttribute('hidden');
      renderEvents();
    } else {
      panel.setAttribute('hidden', '');
    }
  }

  // 渲染事件列表
  function renderEvents() {
    const events = store.get('events') || [];

    if (events.length === 0) {
      body.innerHTML = '<div style="padding: 16px; color: var(--color-text-3); text-align: center;">暂无事件</div>';
      return;
    }

    const typeIcons = {
      log: '📝',
      news_positive: '📈',
      news_negative: '📉',
      news_neutral: '📰',
      error: '⚠️',
      progress: '⏳',
    };

    body.innerHTML = events.map((event, index) => {
      const type = event.type || 'log';
      const icon = typeIcons[type] || '📝';
      const time = new Date(event.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const hasUrl = event.data?.url;
      const url = hasUrl ? event.data.url : '';

      return `
        <div class="event-item ${type} ${hasUrl ? 'has-url' : ''}" data-url="${url}" data-index="${index}">
          <span class="event-time">${time}</span>
          <span class="event-type">${icon}</span>
          <span class="event-content">${esc(event.message || '')}</span>
        </div>
      `;
    }).join('');

    // 绑定点击事件
    body.querySelectorAll('.event-item.has-url').forEach(item => {
      item.addEventListener('click', () => {
        const url = item.dataset.url;
        if (url) window.open(url, '_blank', 'noopener');
      });
    });
  }

  // 更新事件计数显示
  function updateEventCount() {
    const events = store.get('events') || [];
    const countEl = document.querySelector('[data-event-count]');
    const headerCountEl = document.querySelector('[data-header-event-count]');
    if (countEl) countEl.textContent = events.length;
    if (headerCountEl) {
      headerCountEl.textContent = events.length;
      headerCountEl.hidden = events.length === 0;
    }
  }

  // 按钮点击切换
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePanel();
  });

  if (headerAlertsBtn) {
    headerAlertsBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      togglePanel();
    });
  }

  // 关闭按钮
  closeBtn.addEventListener('click', () => {
    togglePanel(false);
  });

  // 点击面板外部关闭
  document.addEventListener('click', (e) => {
    const clickedTrigger = btn.contains(e.target) || headerAlertsBtn?.contains(e.target);
    if (!panel.hasAttribute('hidden') && !panel.contains(e.target) && !clickedTrigger) {
      togglePanel(false);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') togglePanel(false);
  });

  // 监听事件变化
  store.on('events', () => {
    updateEventCount();
    if (!panel.hasAttribute('hidden')) {
      renderEvents();
    }
  });

  // 初始化计数
  updateEventCount();

  logger.info('事件日志面板已初始化');
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ── 设置面板 ──────────────────────────────
function initSettingsPanel() {
  const btn = document.getElementById('btn-header-settings');
  const panel = document.getElementById('settings-panel');
  const closeBtn = document.getElementById('btn-close-settings');
  const clearEventsBtn = document.getElementById('btn-clear-events');
  const refreshNewsBtn = document.getElementById('btn-refresh-news-status');
  const newsStatusEl = document.getElementById('settings-news-status');

  if (!btn || !panel || !closeBtn) return;

  function togglePanel(show) {
    const isHidden = panel.hasAttribute('hidden');
    const shouldShow = show !== undefined ? show : isHidden;
    if (shouldShow) {
      document.getElementById('events-panel')?.setAttribute('hidden', '');
      panel.removeAttribute('hidden');
      refreshNewsStatus();
    } else {
      panel.setAttribute('hidden', '');
    }
  }

  async function refreshNewsStatus() {
    if (!newsStatusEl) return;
    newsStatusEl.textContent = '状态读取中…';
    try {
      const resp = await fetch('/api/news/monitor_status');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      if (!json.success) throw new Error(json.error || 'API error');
      const data = json.data || {};
      newsStatusEl.textContent = `${data.running ? '运行中' : '未运行'} · ${data.interval || '-'}s轮询 · 监控${(data.monitored_stocks || []).length}只股票`;
    } catch (e) {
      newsStatusEl.textContent = `读取失败：${e.message}`;
    }
  }

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    togglePanel();
  });

  closeBtn.addEventListener('click', () => togglePanel(false));
  refreshNewsBtn?.addEventListener('click', refreshNewsStatus);
  clearEventsBtn?.addEventListener('click', () => {
    store.set('events', []);
    logger.info('事件日志已清空');
  });

  document.addEventListener('click', (e) => {
    if (!panel.hasAttribute('hidden') && !panel.contains(e.target) && !btn.contains(e.target)) {
      togglePanel(false);
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') togglePanel(false);
  });

  logger.info('设置面板已初始化');
}

// ── 启动顺序 ──────────────────────────────
function boot() {
  logger.info(`clientId: ${store.get('clientId')?.slice(0, 8)}…`);

  // 0. 主题（必须在第一帧前应用，避免闪白）
  initTheme();

  // 1. SSE 连接（带重连）
  sse.connect();

  // 2. 初始化新闻通知监听
  initNewsAlerts();

  // 3. 初始化事件日志面板
  initEventsPanel();

  // 4. 初始化设置面板
  initSettingsPanel();

  // 5. 侧边栏
  initSidebar();

  // 3. 设置 hash 路由
  initRouter({
    '#/v2': initV2View,
    '#/scan': initScanView,
    '#/patrol': initPatrolView,
    '#/signals': initSignalsView,
    '#/review': initReviewView,
    '#/bottleneck': () => { setV2OnlyUI(false); initBottleneckPage(); },
  });

  // 4. 监听 currentStock 变化（工具栏 + 快速解读）
  store.on('currentStock', (code) => {
    ai.reset();
    updateToolbarStock();
    if (code) fetchQuickAnalysis(code);
  });

  // 5. 不设置默认股票；等待用户从持仓/自选/搜索中选择
  if (!store.get('currentStock')) {
    updateToolbarStock();
    showNoStockState();
  }

  // 获取并显示实际使用的模型
  fetch('/api/status').then(r => r.json()).then(d => {
    if (d.model) {
      const el = document.querySelector('[data-model-label]');
      if (el) el.textContent = '模型 ' + d.model;
    }
  }).catch(() => {});

  logger.info('app ready');
}

// ── 单股深度专属 UI：仅该页显示侧栏 + 工具栏 + 周期 tab + 分析按钮 + stale-bar
function setV2OnlyUI(show) {
  const main = document.querySelector('.main');
  const sidebar = document.getElementById('sidebar');
  const toolbar = document.querySelector('.toolbar');
  const periodTabs = document.getElementById('period-tabs');
  const staleBar = document.getElementById('stale-bar');
  if (!main) return;
  if (show) {
    main.style.gridTemplateColumns = '';
    if (sidebar) sidebar.style.display = '';
    if (toolbar) toolbar.style.display = '';
    if (periodTabs) periodTabs.style.display = '';
    if (staleBar) staleBar.style.display = '';
  } else {
    main.style.gridTemplateColumns = '1fr';
    if (sidebar) sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (staleBar) staleBar.style.display = 'none';
  }
}

// ── 视图初始化函数 ─────────────────────────────────────
function initV2View() {
  setV2OnlyUI(true);
  // v2 单股深度视图：支持 #/v2?code=603000 直接带入股票
  const routeCode = getRouteStockCode();
  if (routeCode && routeCode !== store.get('currentStock')) {
    store.set('currentStock', routeCode);
  }

  // 无论 currentStock 是何时设置的，进入单股页都强制同步一次工具栏/按钮
  updateToolbarStock();

  chart.init();
  initAIPanel();
  signals.init();
  market.init();
  table.init();

  const cur = store.get('currentStock');
  if (cur) fetchQuickAnalysis(cur);

  const splitter = document.getElementById('main-split');
  if (splitter) {
    initSplitter(splitter, { storageKey: 'v2-split-ratio', ratio: 0.55 });
  }

  const analyzeBtn = document.getElementById('btn-analyze');
  if (analyzeBtn) {
    analyzeBtn.addEventListener('click', () => triggerAnalysis());
  }

  // K线 / 成交量 切换 tab：合并到同一 canvas，tab 切换数据源
  const toggleBtns = document.querySelectorAll('.kv-toggle-btn');
  if (toggleBtns.length) {
    // kv-stack 是 card-b 的子元素，与 card-h（按钮所在）是兄弟，
    // 不能用 closest('.kv-stack') 找，必须从按钮所在 card 出发
    toggleBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.kvView;
        const type = btn.dataset.kvType;  // 'kline' | 'volume'
        const card = btn.closest('[data-card]');
        const stack = card?.querySelector('.kv-stack');
        if (!stack || !view) return;
        stack.dataset.kvView = view;
        toggleBtns.forEach((b) => b.classList.toggle('on', b === btn));
        // tab 切换：调 renderChart 让 #kline-canvas 渲染对应数据
        if (type && window.__chart?.renderChart) {
          window.__chart.renderChart(null, null, type);
        }
      });
    });
  }

}

function initScanView() {
  setV2OnlyUI(false);
  // 扫盘视图
  const filterBar = document.getElementById('scan-filters');
  if (filterBar) filterBar.removeAttribute('hidden');
  scan.init();
}

function initPatrolView() {
  setV2OnlyUI(false);
  // 持仓视图
  patrolPage.init();
}

function initSignalsView() {
  setV2OnlyUI(false);
  // 市场信号视图
  signalsPage.init();
}

function initReviewView() {
  setV2OnlyUI(false);
  // 盘前 / 盘后复盘视图
  reviewPage.init();
}

function getRouteStockCode() {
  const hash = window.location.hash || '';
  const q = hash.split('?')[1] || '';
  if (!q) return '';
  const params = new URLSearchParams(q);
  return (params.get('code') || params.get('stock') || '').trim().toUpperCase();
}

function showNoStockState() {
  ['kline', 'indicators', 'signals', 'financials'].forEach(cardName => {
    const card = document.querySelector(`[data-card="${cardName}"]`);
    const slot = card?.querySelector('[data-slot="body"]');
    if (!slot) return;
    slot.setAttribute('data-active-state', 'empty');
    slot.querySelectorAll('[data-state]').forEach(el => {
      el.hidden = el.dataset.state !== 'empty';
    });
  });
  ai.reset();
}

// ── 快速解读（真实行情 + 板块 + 市场情绪） ──
async function fetchQuickAnalysis(code) {
  if (!code) return;
  try {
    const resp = await fetch(`/api/analyze/quick/${encodeURIComponent(code)}`, {
      signal: store.getRequestSignal(),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');
    if (store.get('currentStock') !== code) return;
    ai.showQuickAnalysis(data.data);
    logger.info(`快速解读已加载: ${code}`);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.warn(`快速解读失败: ${e.message}`);
  }
}

// ── 触发 AI 分析（点按钮 / 切股票后自动） ──
async function triggerAnalysis() {
  const code = store.get('currentStock');
  if (!code) {
    logger.warn('triggerAnalysis: 无 currentStock');
    return;
  }
  const btn = document.getElementById('btn-analyze');
  if (btn) { btn.disabled = true; btn.textContent = '分析中…'; }

  if (store.get('sseStatus') !== 'connected') {
    logger.warn('SSE 未连接，正在重连后再分析');
    sse.reconnect();
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  if (store.get('sseStatus') !== 'connected') {
    if (btn) { btn.disabled = false; btn.textContent = '分析'; }
    ai.showError('SSE实时连接未建立，请等待左下角显示“SSE 实时”后重试', 'E_SSE_NOT_CONNECTED');
    return;
  }

  // ai-panel 切到 loading 态
  ai.startAnalysis();

  try {
    // 老 /api/analyze_stream 端点触发后端流式分析
    // （SSE 已经在 sse.js 里连接好，事件会通过 ai_stream / final_result 推过来）
    const resp = await fetch('/api/analyze_stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stock_code: code, client_id: store.get('clientId') }),
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status}`);
    }
    logger.info(`分析已启动: ${code}`);
  } catch (e) {
    logger.error(`分析触发失败: ${e.message}`);
    ai.showError(e.message, 'E_ANALYZE_TRIGGER');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '分析'; }
  }
}

// ── 工具栏股票名称更新 ──
function updateToolbarStock() {
  const code = store.get('currentStock');
  const titleEl = document.querySelector('.toolbar .title');
  const subEl = document.querySelector('.toolbar .sub');
  if (!titleEl) return;

  const analyzeBtn = document.getElementById('btn-analyze');
  if (!code) {
    titleEl.textContent = '未选择股票';
    if (subEl) subEl.textContent = '请从左侧持仓/自选中选择股票';
    if (analyzeBtn) analyzeBtn.disabled = true;
    document.title = 'Stock Scanner 3.1 v2 · 未选择股票';
    return;
  }

  if (analyzeBtn) analyzeBtn.disabled = false;
  titleEl.textContent = code;

  // 从持仓/自选列表中查找名称（notes 字段可能包含中文名）
  const positions = store.get('positions') || [];
  const watchlist = store.get('watchlist') || [];
  const all = [...positions, ...watchlist];
  const found = all.find(item => item.code === code);
  // notes 有时是中文名称（如 "中国传媒"）
  const name = found?.name || found?.notes || '名称获取中';

  if (subEl) subEl.textContent = `${name} · A 股`;
  document.title = `Stock Scanner 3.1 v2 · ${code} ${name}`;
}

// DOMContentLoaded 之后启动
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
