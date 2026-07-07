// chart.js · v1.2.2 · 2026-06-14
// K线 / 成交量 / 技术指标渲染
//
// 设计：
// 1. Plotly.js 动态从 CDN 加载（不写入 pyproject，不增加 Python 依赖）
//    加载失败 → 降级到 HTML 内的静态 SVG fallback
// 2. 后端 /api/chart/<code> 返回 Plotly JSON（v1 mock 已就绪）
//    接口未就绪 → 降级到静态 fallback
// 3. 监听 store.currentStock 变化，自动重渲染
// 4. 4 态由 setCardState(name, state) 统一驱动，业务事件触发
//
// v1 范围：场景 1 单股深度的图表组件（K线 + 成交量 + 订阅切股票）
// 4 态 + 指标：v1 由 signals.js 独家负责（避免 race）
// v1.1 已交付：4 维雷达 + L0-L3 历史 sparkline 由 signals.js 用纯 SVG 实现，无 Plotly 依赖
// v1.2 推到：Plotly 多 subplot

import { store } from './store.js';
import { logger } from './logger.js';

// ── Plotly 加载 ─────────────────────────────
const PLOTLY_CDN = 'https://cdn.plot.ly/plotly-2.35.2.min.js';
let _plotlyLoadPromise = null;
let _currentPeriod = '1M';
let _inited = false;
let _chartToken = 0;

/**
 * 动态加载 Plotly.js（多次调用只加载一次）
 * @returns {Promise<object|null>} Plotly 对象，加载失败返回 null
 */
function loadPlotly() {
  if (typeof window.Plotly !== 'undefined') return Promise.resolve(window.Plotly);
  if (_plotlyLoadPromise) return _plotlyLoadPromise;

  _plotlyLoadPromise = new Promise((resolve) => {
    const script = document.createElement('script');
    script.src = PLOTLY_CDN;
    script.async = true;
    script.onload = () => {
      if (typeof window.Plotly !== 'undefined') {
        logger.info(`Plotly ${window.Plotly.version || '?'} loaded`);
        resolve(window.Plotly);
      } else {
        logger.warn('Plotly script loaded but window.Plotly undefined');
        resolve(null);
      }
    };
    script.onerror = () => {
      logger.warn('Plotly CDN failed; chart cards will use SVG fallback');
      resolve(null);
    };
    document.head.appendChild(script);
  });

  return _plotlyLoadPromise;
}

// ── API 端点（v1 设计，Day 3 实现）───────────
const API = {
  kline:      (code, period) => `/api/chart/${encodeURIComponent(code)}?type=kline&period=${period || '1M'}`,
  volume:     (code, period) => `/api/chart/${encodeURIComponent(code)}?type=volume&period=${period || '1M'}`,
  indicators: (code)         => `/api/indicators/${encodeURIComponent(code)}`,
};

/** fetch 并解析 JSON，错误抛出
 * Codex P2 修复：传 store.getRequestSignal() 让切股票时自动取消
 */
async function fetchJSON(url) {
  const myToken = store.getRequestToken();
  const resp = await fetch(url, { signal: store.getRequestSignal() });
  if (myToken !== store.getRequestToken()) {
    const err = new Error('stale request');
    err.name = 'AbortError';
    throw err;
  }
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  const data = await resp.json();
  if (data && data.success === false) {
    throw new Error(data.error || 'API returned success=false');
  }
  return data;
}

// ── K 线 + 成交量 ───────────────────────────

/**
 * 渲染 K 线到 #kline-canvas
 * @param {string} code - 股票代码
 * @param {string} period - 1D/5D/1M/3M/1Y/ALL
 * @returns {Promise<boolean>} true=Plotly 渲染成功，false=降级到 SVG
 */
async function renderKLine(code, period = '1M', chartToken = _chartToken) {
  const canvas = document.getElementById('kline-canvas');
  if (!canvas) return false;

  setCardState('kline', 'loading');

  try {
    const data = await fetchJSON(API.kline(code, period));
    if (chartToken !== _chartToken) return false;
    const fig = data.fig || data;  // 后端可能直接返 fig 或包一层
    updateChartMeta(data.source || 'real');

    // 关键修复：后端的 K线 fig 实际包含 K线 + 成交量子图（xaxis2/yaxis2），
    // 前端如果不剔除，下方 #volume-canvas 就会变成"第二次画成交量"造成重复显示。
    // 这里只保留画在主轴 (x/y) 上的 K线 candlestick，剔除成交量 bar trace 和子图坐标轴。
    const klineData = (fig.data || []).filter(
      (d) => d.xaxis === 'x' || (!d.xaxis && !d.xaxis2)
    );
    const klineLayout = { ...fig.layout };
    delete klineLayout.xaxis2;
    delete klineLayout.yaxis2;

    const Plotly = await loadPlotly();
    if (chartToken !== _chartToken) return false;
    if (!Plotly) {
      renderKLineSVG(fig);
      canvas.style.height = '0';  // 折叠空 canvas，避免与 fallback SVG 重叠
      setCardState('kline', 'normal');
      hideFallback('kline', false);
      return true;
    }

    // 布局：暗色 + 等宽数字 + 中文字体
    const layout = {
      ...klineLayout,
      // 强制让 Plotly 跟随容器尺寸，否则后端 fig.layout 里的 height/width
      // 会让 SVG 渲染成 500x700，溢出 kline-canvas (280px) 与下方"技术指标"卡片重叠
      autosize: true,
      paper_bgcolor: 'transparent',
      plot_bgcolor:  'transparent',
      font: {
        family: '"JetBrains Mono", "SF Mono", "Menlo", ui-monospace, monospace',
        color: '#b8c1cc',
        size: 11,
      },
      // l:50 留出 y 轴价格标签；r:12 右留边；t:24 留出后端默认标题空间（否则 002130 K线标题被遮）；b:36 留出 x 轴日期标签
      margin: { l: 50, r: 12, t: 24, b: 36 },
      title: { text: '' },  // 关闭后端默认 title（"002130 K线"），避免与 card 标题重复
      xaxis: {
        ...klineLayout?.xaxis,
        gridcolor: '#1a2028',
        zerolinecolor: '#1a2028',
        // 后端默认 showticklabels: false，必须强制开启才能看到日期
        showticklabels: true,
        tickformat: '%m/%d',
        rangeslider: { visible: false },  // v1 不开 range slider
      },
      yaxis: {
        ...klineLayout?.yaxis,
        gridcolor: '#1a2028',
        zerolinecolor: '#1a2028',
        side: 'right',  // 金融图表惯例：Y 轴在右
      },
      hoverlabel: {
        bgcolor: '#1a212c',
        bordercolor: '#222a36',
        font: { family: '"PingFang SC", "Inter", sans-serif', color: '#e6edf3' },
      },
    };
    // 移除后端写死的 width/height，让 Plotly 走 autosize 真正贴合容器
    delete layout.width;
    delete layout.height;

    await Plotly.react(canvas, klineData, layout, {
      displayModeBar: false,  // v1 不显示工具栏
      responsive: true,
      autosize: true,
    });
    // 强制让 SVG 重算尺寸以贴合当前容器（防止初次渲染尺寸滞后）
    Plotly.Plots.resize(canvas);
    // 再调一次防 title 动画期间的高度计算（margin.t: 24 关闭默认 title 后）
    requestAnimationFrame(() => Plotly.Plots.resize(canvas));

    setCardState('kline', 'normal');
    hideFallback('kline', true);  // Plotly 成功，藏起 SVG fallback
    return true;
  } catch (e) {
    if (chartToken !== _chartToken) return false;
    logger.warn(`K线渲染失败：${e.message}`);
    updateChartMeta('真实数据获取失败');
    setCardState('kline', 'error');
    hideFallback('kline', true);
    return false;
  }
}

/**
 * 渲染成交量到 #volume-canvas
 */
async function renderVolume(code, period = '1M', chartToken = _chartToken) {
  const canvas = document.getElementById('volume-canvas');
  if (!canvas) return false;

  try {
    const data = await fetchJSON(API.volume(code, period));
    if (chartToken !== _chartToken) return false;
    const fig = data.fig || data;

    const Plotly = await loadPlotly();
    if (chartToken !== _chartToken) return false;
    if (!Plotly) {
      renderVolumeSVG(fig);
      canvas.style.height = '0';  // 折叠空 canvas
      hideFallback('volume', false);
      return true;
    }

    const layout = {
      ...fig.layout,
      // 同样强制贴合 volume-canvas (80px) 容器，否则 SVG 会撑到 500px 与下方卡片重叠
      autosize: true,
      paper_bgcolor: 'transparent',
      plot_bgcolor:  'transparent',
      font: { family: 'monospace', color: '#b8c1cc', size: 10 },
      // l:44 让 y 轴量能数字不被压扁；r:12 右留边；t:20 留出标题空间（避免后端 title 跑到外面）；b:24 给 x 轴日期空间
      margin: { l: 44, r: 12, t: 20, b: 24 },
      title: { text: '' },  // 关闭后端默认 title，避免与 card 标题重复且溢出
      xaxis: {
        gridcolor: '#1a2028',
        showticklabels: true,
        tickformat: '%m/%d',
        tickfont: { size: 9, color: '#8b96a8' },
      },
      yaxis: { gridcolor: '#1a2028', side: 'right', tickfont: { size: 9, color: '#8b96a8' } },
      showlegend: false,
    };
    delete layout.width;
    delete layout.height;

    await Plotly.react(canvas, fig.data || [], layout, {
      displayModeBar: false,
      responsive: true,
      autosize: true,
    });
    Plotly.Plots.resize(canvas);

    hideFallback('volume', true);
    return true;
  } catch (e) {
    if (chartToken !== _chartToken) return false;
    logger.warn(`成交量渲染失败：${e.message}`);
    hideFallback('volume', false);
    return false;
  }
}

/**
 * 统一渲染入口：把 K线 / 成交量 都画到 #kline-canvas 同一个 div 里。
 * 切 tab 时调用 Plotly.purge(canvas) 清空 + 重新 Plotly.react 画新数据。
 * @param {string} code - 股票代码
 * @param {string} period - 1D/5D/1M/3M/1Y/ALL
 * @param {'kline'|'volume'} type - 渲染什么数据
 * @returns {Promise<boolean>}
 */
async function renderChart(code, period = '1M', type = 'kline', chartToken = ++_chartToken) {
  const canvas = document.getElementById('kline-canvas');
  if (!canvas) return false;
  // code/period 为空时从 store + module state 读（tab 切换场景）
  if (!code) code = store.get('currentStock');
  if (!period) period = _currentPeriod;
  if (!code) return false;
  // purge 旧内容（避免 Plotly 在同一 div 多次 react 后报 warning）
  if (canvas.querySelector('svg.main-svg') && window.Plotly) {
    try { window.Plotly.purge(canvas); } catch (e) { /* ignore */ }
  }
  setCardState('kline', 'loading');
  try {
    const apiPath = type === 'volume' ? API.volume : API.kline;
    const data = await fetchJSON(apiPath(code, period));
    if (chartToken !== _chartToken) return false;
    const fig = data.fig || data;
    updateChartMeta(data.source || 'real');

    const Plotly = await loadPlotly();
    if (chartToken !== _chartToken) return false;
    if (!Plotly) {
      // 降级路径：原 SVG fallback 已能展示
      setCardState('kline', 'normal');
      return true;
    }

    // 与 renderKLine 同样的 layout 配置（K线/成交量共用）
    const baseLayout = type === 'volume'
      ? {
          paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
          font: { family: 'monospace', color: '#b8c1cc', size: 10 },
          margin: { l: 44, r: 12, t: 20, b: 24 },
          // 复用主 xaxis，yaxis 重锚定到 xaxis
          xaxis: { gridcolor: '#1a2028', showticklabels: true, tickformat: '%m/%d', tickfont: { size: 9, color: '#8b96a8' }, rangeslider: { visible: false } },
          yaxis: { gridcolor: '#1a2028', side: 'right', tickfont: { size: 9, color: '#8b96a8' } },
          showlegend: false,
        }
      : {
          paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
          font: { family: '"JetBrains Mono", monospace', color: '#b8c1cc', size: 11 },
          margin: { l: 50, r: 12, t: 24, b: 36 },
          title: { text: '' },
          xaxis: { ...fig.layout?.xaxis, gridcolor: '#1a2028', zerolinecolor: '#1a2028', showticklabels: true, tickformat: '%m/%d', rangeslider: { visible: false } },
          yaxis: { ...fig.layout?.yaxis, gridcolor: '#1a2028', zerolinecolor: '#1a2028', side: 'right' },
          hoverlabel: { bgcolor: '#1a212c', bordercolor: '#222a36', font: { family: '"PingFang SC", "Inter", sans-serif', color: '#e6edf3' } },
        };
    const layout = { ...fig.layout, ...baseLayout, autosize: true };
    delete layout.width;
    delete layout.height;
    delete layout.title;  // 关闭后端默认 title（避免与卡片头重复）
    // K线模式要剔除 yaxis2 子图成交量；volume 模式要剔除主 K线（只留 bar trace）
    const cleanData = type === 'kline'
      ? (fig.data || []).filter(d => d.xaxis === 'x' || (!d.xaxis && !d.xaxis2))
      : (fig.data || []).filter(d => d.xaxis === 'x2' || d.type === 'bar');
    // 清理掉子图 axes（避免 Plotly 双 subplot）
    delete layout.xaxis2;
    delete layout.yaxis2;
    await Plotly.react(canvas, cleanData, layout, {
      displayModeBar: false, responsive: true, autosize: true,
    });
    Plotly.Plots.resize(canvas);
    requestAnimationFrame(() => Plotly.Plots.resize(canvas));
    setCardState('kline', 'normal');
    return true;
  } catch (e) {
    if (chartToken !== _chartToken) return false;
    logger.warn(`renderChart 失败：${e.message}`);
    setCardState('kline', 'error');
    return false;
  }
}

function renderKLineSVG(fig) {
  const fallback = document.getElementById('kline-fallback');
  if (!fallback) return;
  const candle = (fig.data || []).find(d => d.type === 'candlestick');
  if (!candle || !Array.isArray(candle.close) || !candle.close.length) return;
  const opens = candle.open || [];
  const highs = candle.high || [];
  const lows = candle.low || [];
  const closes = candle.close || [];
  const values = [...highs, ...lows].map(Number).filter(Number.isFinite);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const W = 800, H = 280, pad = 16;
  const span = max - min || 1;
  const y = v => pad + (max - v) / span * (H - pad * 2);
  const step = (W - pad * 2) / Math.max(1, closes.length);
  const bodyW = Math.max(3, Math.min(14, step * 0.55));
  const candles = closes.map((c, i) => {
    const x = pad + step * i + step / 2;
    const o = Number(opens[i]);
    const h = Number(highs[i]);
    const l = Number(lows[i]);
    const close = Number(c);
    const up = close >= o;
    // 中国行情惯例：涨=红，跌=绿
    const color = up ? '#ef4444' : '#10b981';
    const yOpen = y(o), yClose = y(close);
    const top = Math.min(yOpen, yClose);
    const height = Math.max(1, Math.abs(yOpen - yClose));
    return `<line x1="${x.toFixed(1)}" y1="${y(h).toFixed(1)}" x2="${x.toFixed(1)}" y2="${y(l).toFixed(1)}" stroke="${color}" stroke-width="1"/>
      <rect x="${(x - bodyW / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bodyW.toFixed(1)}" height="${height.toFixed(1)}" fill="${color}"/>`;
  }).join('');
  fallback.innerHTML = `<svg class="kline-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="真实 K 线 SVG 图">
    <g stroke="#1a2028" stroke-width="0.5">
      <line x1="0" y1="${pad}" x2="${W}" y2="${pad}"/>
      <line x1="0" y1="${H / 2}" x2="${W}" y2="${H / 2}"/>
      <line x1="0" y1="${H - pad}" x2="${W}" y2="${H - pad}"/>
    </g>
    ${candles}
  </svg>`;
}

function renderVolumeSVG(fig) {
  const fallback = document.getElementById('volume-fallback');
  if (!fallback) return;
  const bar = (fig.data || []).find(d => d.type === 'bar');
  if (!bar || !Array.isArray(bar.y) || !bar.y.length) return;
  const values = bar.y.map(Number).filter(Number.isFinite);
  const max = Math.max(...values, 1);
  const W = 800, H = 80;
  const step = W / Math.max(1, values.length);
  const bodyW = Math.max(3, Math.min(14, step * 0.55));
  const colors = bar.marker?.color || [];
  const rects = values.map((v, i) => {
    const h = Math.max(1, v / max * H);
    const x = step * i + (step - bodyW) / 2;
    const color = colors[i] || '#60a5fa';
    return `<rect x="${x.toFixed(1)}" y="${(H - h).toFixed(1)}" width="${bodyW.toFixed(1)}" height="${h.toFixed(1)}" fill="${color}" opacity="0.7"/>`;
  }).join('');
  fallback.innerHTML = `<svg class="vol-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">${rects}</svg>`;
}

/** 隐藏/显示 SVG fallback（chart 渲染成功时藏，失败时显） */
function hideFallback(prefix, hide) {
  const el = document.getElementById(`${prefix}-fallback`);
  if (el) el.hidden = !!hide;
}

function updateChartMeta(source) {
  const meta = document.getElementById('chart-meta');
  if (meta) meta.textContent = source === 'real:tencent' ? '真实数据 · 腾讯行情' : source;
}

// ── 技术指标 ───────────────────────────────

/** 渲染技术指标到 #indicators-grid
 * Codex P2 修复：技术指标由 signals.js 独家负责
 * （chart.js 之前也写同一个 #indicators-grid → race condition）
 * 此函数保留为 stub，返回 false，让 signals.js 接管。
 */
async function renderIndicators(code, type = 'RSI') {
  // chart.js 不再写 #indicators-grid（signals.js 独家负责，避免 race）
  // 这个函数保留为 no-op，让 store.on('currentStock') 单一来源驱动。
  return false;
}

// ── 4 态驱动（业务事件触发，由 chart/signals/table 模块自己调 setCardState） ──

/**
 * 设置某张卡片的 data-active-state 属性
 * @param {string} cardName - data-card 属性值
 * @param {'normal'|'loading'|'empty'|'error'|'stale'} state
 */
function setCardState(cardName, state) {
  const card = document.querySelector(`[data-card="${cardName}"]`);
  const slot = card?.querySelector('[data-slot="body"]');
  if (!slot) return;
  slot.setAttribute('data-active-state', state);
  // 三段垂直布局下，k线/指标各自有独立 [data-state] 元素；
  // 必须按段隔离，否则 k线 loading 会把指标的 loading 也显示出来
  const klineSection = slot.querySelector('.kv-kline');
  if (klineSection) {
    klineSection.querySelectorAll('[data-state]').forEach(el => {
      el.hidden = el.dataset.state !== state;
    });
  }
  // 成交量 / 降级 SVG 跟 k线共享同一状态
  const volFallback = slot.querySelector('#volume-fallback');
  if (volFallback) volFallback.hidden = state === 'normal';
}

// ── 生命周期 ─────────────────────────────

function renderCurrentStock() {
  const code = store.get('currentStock');
  if (!code) return;
  const token = ++_chartToken;
  // 根据当前 tab（kline/volume）渲染对应数据到 #kline-canvas
  // 默认 K线
  const stack = document.querySelector('.kv-stack');
  const type = stack?.dataset?.kvView === 'volume' ? 'volume' : 'kline';
  logger.info(`re-render ${type} chart for ${code} period=${_currentPeriod}`);
  renderChart(code, _currentPeriod, type, token);
}

function bindPeriodTabs() {
  const tabs = document.getElementById('period-tabs');
  if (!tabs || tabs.dataset.bound === '1') return;
  tabs.dataset.bound = '1';
  tabs.querySelectorAll('button[data-period]').forEach(btn => {
    btn.addEventListener('click', () => {
      const period = btn.dataset.period || '1M';
      if (period === _currentPeriod) return;
      _currentPeriod = period;
      tabs.querySelectorAll('button[data-period]').forEach(b => {
        const active = b.dataset.period === _currentPeriod;
        b.classList.toggle('on', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
      renderCurrentStock();
    });
  });
}

/** 初始化：订阅 currentStock 重新拉图 */
function init() {
  bindPeriodTabs();
  if (_inited) return;
  _inited = true;
  logger.info('chart module init');

  // 订阅股票变化 → 按当前周期重新拉图
  store.on('currentStock', (code) => {
    if (!code) return;
    renderCurrentStock();
    // renderIndicators 已废弃（signals.js 独家负责 #indicators-grid）
  });

  // v1.3 fix: 如果 currentStock 已在 chart.init() 前设置，立即渲染
  //（app.js initV2View 先 set currentStock 再调 chart.init()）
  const cur = store.get('currentStock');
  if (cur) renderCurrentStock();
}

// 调试钩子
if (typeof window !== 'undefined') window.__chart = {
  renderKLine, renderVolume, renderIndicators, setCardState, renderChart,
};

export const chart = { init, renderKLine, renderVolume, renderIndicators, setCardState, renderChart };
