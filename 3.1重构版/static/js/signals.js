// signals.js · v1.3 · 2026-06-14
// 4 维评分 + 雷达图 + L0/L1/L2/L3 信号条 + 历史趋势 sparkline
//
// 数据源：
//   - SSE 'scores_update' 事件 → 实时更新评分（后端在 AI 分析过程中持续推送）
//   - /api/indicators/<code> → 18 项技术指标 + L0-L3 信号 + 30 点历史
//
// v1.1 第二批新增：
//   - 4 维雷达图（120×120 内联 SVG，无依赖）
//   - 每条 L0-L3 信号显示 30 点 sparkline（极简 SVG 折线）
//
// 设计取舍：
//   - 雷达 + 数字双通道：4 维就 4 轴，纸面简洁；数字网格放右边给精确值
//   - sparkline 不画坐标轴，只看趋势走向

import { store } from './store.js';
import { logger } from './logger.js';
import { sse } from './sse.js';

const API = {
  indicators: (code) => `/api/indicators/${encodeURIComponent(code)}`,
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// ── 4 维评分 ───────────────────────────────
const SCORE_DIMS = [
  { key: 'technical',   label: '技术',   weight: 0.40 },
  { key: 'fundamental', label: '基本面', weight: 0.30 },
  { key: 'sentiment',   label: '情绪',   weight: 0.20 },
  { key: 'composite',   label: '综合',   weight: 0.10 },
];

let _scoreExplains = {};

/** 渲染评分卡到 #score-card-grid */
function renderScoreCard(scores, explains = _scoreExplains) {
  const grid = document.getElementById('score-card-grid');
  const radar = document.getElementById('score-radar');

  if (!scores) {
    if (grid) {
      grid.innerHTML = `
        <div class="empty-block" style="padding: var(--space-3);">
          <div class="sub" style="color: var(--color-text-3);">等待评分…</div>
        </div>`;
    }
    if (radar) radar.innerHTML = renderRadarSVG(null);
    return;
  }

  if (grid) {
    grid.innerHTML = SCORE_DIMS.map(({ key, label }) => {
      const val = scores[key];
      if (val == null) return '';
      const pct = Math.max(0, Math.min(100, val));
      const cls = pct >= 70 ? 'up' : pct >= 40 ? 'mid' : 'down';
      const ex = explains?.[key] || {};
      return `
        <div class="score-cell score-${cls}" title="${esc(ex.meaning || '')}\n${esc(ex.action || '')}">
          <div class="num">${Math.round(pct)}</div>
          <div class="lbl">${label}</div>
          <div class="bar"><div style="width: ${pct}%"></div></div>
          <div class="sub" style="margin-top:4px; font-size: var(--fs-micro); color: var(--color-text-3); line-height:1.35;">${esc(ex.action || '等待解读')}</div>
        </div>`;
    }).join('');
  }

  if (radar) radar.innerHTML = renderRadarSVG(scores);
}

/**
 * 4 轴雷达 SVG · 120×120
 *   轴序：技术（上）/ 基本面（右）/ 情绪（下）/ 综合（左）
 *   值域 0-100 → 半径 0-50
 */
function renderRadarSVG(scores) {
  const cx = 60, cy = 60, R = 50;
  // 4 个轴方向（顺时针，从顶部开始）：上、右、下、左
  const axes = [
    { key: 'technical',   label: '技术',   ang: -Math.PI / 2 },
    { key: 'fundamental', label: '基本面', ang: 0 },
    { key: 'sentiment',   label: '情绪',   ang:  Math.PI / 2 },
    { key: 'composite',   label: '综合',   ang:  Math.PI },
  ];

  // 背景圆环（25/50/75/100）
  const rings = [0.25, 0.5, 0.75, 1].map(r => `<circle cx="${cx}" cy="${cy}" r="${R * r}" fill="none" stroke="var(--chart-grid-line)" stroke-width="1" opacity="${r === 1 ? 1 : 0.5}"/>`).join('');
  // 轴线
  const axisLines = axes.map(a => {
    const x2 = cx + Math.cos(a.ang) * R;
    const y2 = cy + Math.sin(a.ang) * R;
    return `<line x1="${cx}" y1="${cy}" x2="${x2}" y2="${y2}" stroke="var(--chart-grid-line)" stroke-width="1" opacity="0.6"/>`;
  }).join('');
  // 轴标签
  const labels = axes.map(a => {
    const lr = R + 12;
    const x = cx + Math.cos(a.ang) * lr;
    const y = cy + Math.sin(a.ang) * lr;
    let anchor = 'middle';
    if (Math.abs(Math.cos(a.ang)) > 0.5) anchor = Math.cos(a.ang) > 0 ? 'start' : 'end';
    return `<text x="${x}" y="${y + 3}" fill="var(--color-text-3)" font-size="10" text-anchor="${anchor}">${a.label}</text>`;
  }).join('');

  // 数据多边形
  let dataShape = '';
  if (scores) {
    const pts = axes.map(a => {
      const v = Math.max(0, Math.min(100, scores[a.key] ?? 0));
      const r = R * (v / 100);
      const x = cx + Math.cos(a.ang) * r;
      const y = cy + Math.sin(a.ang) * r;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    // 顶点小圆
    const dots = axes.map(a => {
      const v = Math.max(0, Math.min(100, scores[a.key] ?? 0));
      const r = R * (v / 100);
      const x = cx + Math.cos(a.ang) * r;
      const y = cy + Math.sin(a.ang) * r;
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" fill="var(--color-accent-1)"/>`;
    }).join('');
    dataShape = `
      <polygon points="${pts}" fill="var(--color-accent-1)" fill-opacity="0.18" stroke="var(--color-accent-1)" stroke-width="1.5"/>
      ${dots}`;
  }

  return `
    <svg viewBox="0 0 120 120" width="120" height="120" role="img" aria-label="4 维评分雷达">
      ${rings}
      ${axisLines}
      ${dataShape}
      ${labels}
    </svg>`;
}

// ── L0/L1/L2/L3 信号条 ─────────────────────
const SIGNAL_LEVELS = [
  { key: 'L0', label: 'L0 5m',   desc: '5 分钟 K 线 · 极短线' },
  { key: 'L1', label: 'L1 日',    desc: '日 K · 短期趋势' },
  { key: 'L2', label: 'L2 周',    desc: '周 K · 中期趋势' },
  { key: 'L3', label: 'L3 长线',  desc: '缠论结构 · 长线趋势' },
];

/** 渲染 L0-L3 到 #signals-list */
function renderSignals(signals) {
  const list = document.getElementById('signals-list');
  const meta = document.getElementById('signals-meta');
  if (!list) return;

  if (!signals || !Object.keys(signals).length) {
    list.innerHTML = `
      <div class="empty-block" style="padding: var(--space-3);">
        <div class="sub" style="color: var(--color-text-3);">无信号数据</div>
      </div>`;
    if (meta) meta.textContent = '— —';
    return;
  }

  // 综合信号（4 个值的简单平均；后续可加权）
  const values = SIGNAL_LEVELS.map(l => signals[l.key]?.value || 0);
  const composite = values.reduce((a, b) => a + b, 0) / values.length;
  const compositeLabel = composite >= 0.3 ? '偏多' : composite <= -0.3 ? '偏空' : '中性';
  const compositeColor = composite >= 0 ? 'pos' : 'neg';
  if (meta) {
    meta.innerHTML = `综合 <span class="num ${compositeColor}" style="color: var(--color-accent-${composite >= 0 ? 2 : 3});">${composite >= 0 ? '+' : ''}${composite.toFixed(2)}</span> ${compositeLabel}`;
  }

  list.innerHTML = SIGNAL_LEVELS.map(({ key, label, desc }) => {
    const sig = signals[key];
    if (!sig) return '';
    const val = Math.max(-1, Math.min(1, sig.value || 0));
    const pct = Math.abs(val) * 50;  // -1..+1 → 0..50% 宽度
    const cls = val >= 0 ? 'pos' : 'neg';
    const sparkSVG = renderSparklineSVG(sig.history, val);
    const ex = sig.explain || {};
    return `
      <div class="signal-row" title="${esc(desc)}\n${esc(ex.meaning || '')}\n${esc(ex.action || '')}">
        <span class="lbl">${label}</span>
        <span class="track" aria-label="${label} 信号强度 ${val.toFixed(2)}"><div class="${cls}" style="width: ${pct}%"></div></span>
        <span class="spark" aria-hidden="true">${sparkSVG}</span>
        <span class="val ${cls}">${val >= 0 ? '+' : ''}${val.toFixed(2)}</span>
        <span class="sub" style="grid-column: 2 / -1; color: var(--color-text-3); font-size: var(--fs-micro);">${esc(ex.action || desc)}</span>
      </div>`;
  }).join('');
}

/**
 * Sparkline · 60×16 内联 SVG
 *   - history: number[] (-1..+1) 30 个点；缺数据时返回空 svg 占位
 *   - val: 当前值（决定线条颜色）
 */
function renderSparklineSVG(history, val) {
  const W = 60, H = 16, pad = 1;
  if (!Array.isArray(history) || history.length < 2) {
    return `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"></svg>`;
  }
  const n = history.length;
  const min = -1, max = 1;
  const xStep = (W - pad * 2) / (n - 1);
  const yScale = (v) => {
    const t = (v - min) / (max - min);  // 0..1
    return H - pad - t * (H - pad * 2);
  };
  const points = history.map((v, i) => `${(pad + i * xStep).toFixed(1)},${yScale(v).toFixed(1)}`).join(' ');
  const color = val >= 0 ? 'var(--color-accent-2)' : 'var(--color-accent-3)';
  // 0 基准线（虚线）
  const yZero = yScale(0);
  return `
    <svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" preserveAspectRatio="none">
      <line x1="0" y1="${yZero.toFixed(1)}" x2="${W}" y2="${yZero.toFixed(1)}" stroke="var(--chart-grid-line)" stroke-width="0.5" stroke-dasharray="2 2"/>
      <polyline fill="none" stroke="${color}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" points="${points}"/>
    </svg>`;
}

// ── 18 项技术指标 ─────────────────────────
let _activeIndTab = 'rsi';
let _indicatorData = [];

const IND_TAB_KEYWORDS = {
  rsi:     ['RSI'],
  macd:    ['MACD'],
  kdj:     ['KDJ', 'WR'],
  boll:    ['布林', '%B', 'BOLL', 'BIAS'],
  pattern: ['形态', '趋势', '量能', 'PDI', 'ADX', 'MTM', 'ROC', 'PSY'],
  chanlun: ['缠论', '中枢'],
};

function updateSourceMeta(source) {
  const label = source === 'real' ? '真实数据' : source;
  const indicatorsMeta = document.getElementById('indicators-meta');
  const signalsMeta = document.getElementById('signals-meta');
  if (indicatorsMeta) indicatorsMeta.textContent = label;
  if (signalsMeta && signalsMeta.textContent === '— —') signalsMeta.textContent = label;
}

function filterIndicatorsByTab(items, tab) {
  const keys = IND_TAB_KEYWORDS[tab] || [];
  return items.filter(it => keys.some(k => String(it.label || '').includes(k)));
}

function renderIndicators(indicators) {
  _indicatorData = indicators || [];
  const grid = document.getElementById('indicators-grid');
  if (!grid) return;

  if (!_indicatorData.length) {
    grid.innerHTML = `
      <div class="empty-block" style="padding: var(--space-3);">
        <svg viewBox="0 0 48 48" aria-hidden="true" style="width: 32px; height: 32px;"><circle cx="24" cy="24" r="18"/><path d="M16 24 L22 30 L32 18"/></svg>
        <div class="head" style="font-size: var(--fs-body);">暂无指标</div>
        <div class="sub">选择股票后加载真实技术指标</div>
      </div>`;
    return;
  }

  // 有数据时确保状态为 normal
  const card = document.querySelector('[data-card="indicators"]');
  const slot = card?.querySelector('[data-slot="body"]');
  if (slot) slot.setAttribute('data-active-state', 'normal');

  const items = filterIndicatorsByTab(_indicatorData, _activeIndTab);
  if (!items.length) {
    grid.innerHTML = `
      <div class="empty-block" style="padding: var(--space-3);">
        <div class="head" style="font-size: var(--fs-body);">该分类暂无指标</div>
        <div class="sub">尝试切换到其他技术指标分类</div>
      </div>`;
    return;
  }

  grid.innerHTML = items.map(({ label, value, level, explain }) => {
    const cls = level === 'pos' ? 'pos' : level === 'neg' ? 'neg' : '';
    const title = [explain?.meaning, explain?.action].filter(Boolean).join('\n');
    return `
      <span class="lbl" title="${esc(title)}">${esc(label)}</span>
      <span class="val ${cls}" title="${esc(title)}">${esc(value)}</span>
      <span class="sub" style="grid-column: 1 / -1; margin:-4px 0 4px; color: var(--color-text-3); font-size: var(--fs-micro); line-height:1.35;">${esc(explain?.meaning || '')} ${explain?.action ? '｜' + esc(explain.action) : ''}</span>`;
  }).join('');
}

function bindIndicatorTabs() {
  const tabs = document.getElementById('indicator-tabs');
  if (!tabs) return;
  tabs.querySelectorAll('button[data-ind-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.indTab;
      if (!tab || tab === _activeIndTab) return;
      _activeIndTab = tab;
      tabs.querySelectorAll('button[data-ind-tab]').forEach(b => {
        const active = b.dataset.indTab === _activeIndTab;
        b.classList.toggle('on', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      if (_indicatorData.length) renderIndicators(_indicatorData);
    });
  });
}

// ── 拉数据 ─────────────────────────────────
async function fetchIndicators(code) {
  const myToken = store.getRequestToken();
  setState('signals', 'loading');
  setIndicatorState('loading');
  try {
    const resp = await fetch(API.indicators(code), { signal: store.getRequestSignal() });
    if (myToken !== store.getRequestToken()) return;  // 切股票，丢弃
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.success) throw new Error(data.error || `HTTP ${resp.status}`);

    const payload = data.data || {};
    _scoreExplains = payload.score_explains || {};
    // v1.3: 后端 scores key 为 technical_score/fundamental_score/sentiment_score/comprehensive_score
    // 前端 SCORE_DIMS 期望 technical/fundamental/sentiment/composite
    const rawScores = payload.scores || {};
    const mappedScores = {
      technical:   rawScores.technical_score   ?? rawScores.technical   ?? null,
      fundamental: rawScores.fundamental_score ?? rawScores.fundamental ?? null,
      sentiment:   rawScores.sentiment_score   ?? rawScores.sentiment   ?? null,
      composite:   rawScores.comprehensive_score ?? rawScores.composite ?? null,
    };
    renderScoreCard(mappedScores, _scoreExplains);
    // 优先使用独立 API 的四层信号（懒加载），否则 fallback 到主接口的数据
    if (payload.four_layer) {
      renderSignals(payload.four_layer);
    } else {
      // 四层信号不在主接口里时（懒加载），启动后台拉取
      renderSignals(null);
      fetchFourLayer(code);
    }
    renderIndicators(payload.indicators || []);
    updateSourceMeta(data.source || 'real');
    setIndicatorState('normal');
    setState('signals', 'normal');
    logger.info(`indicators loaded for ${code}`);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`fetchIndicators 失败: ${e.message}`);
    updateSourceMeta('真实数据获取失败');
    setIndicatorState('error');
    setState('signals', 'error');
  }
}

// ── 4 态驱动 ─────────────────────────────
function setState(cardName, state) {
  const card = document.querySelector(`[data-card="${cardName}"]`);
  const slot = card?.querySelector('[data-slot="body"]');
  if (!slot) return;
  slot.setAttribute('data-active-state', state);
  slot.querySelectorAll('[data-state]').forEach(el => {
    el.hidden = el.dataset.state !== state;
  });
}

// 技术指标已独立成卡 data-card="indicators"
function setIndicatorState(state) {
  const card = document.querySelector('[data-card="indicators"]');
  const slot = card?.querySelector('[data-slot="body"]');
  if (!slot) return;
  const indSection = slot?.querySelector('.kv-indicator');
  if (!indSection) return;
  indSection.querySelectorAll('[data-state]').forEach(el => {
    el.hidden = el.dataset.state !== state;
  });
  // 非 normal 状态时清空 indicators-grid，避免旧内容和空状态提示重叠
  if (state !== 'normal') {
    const grid = document.getElementById('indicators-grid');
    if (grid) grid.innerHTML = '';
  }
}

// ── 接 SSE 事件 ───────────────────────────
sse.on('scores_update', (data) => {
  if (!data) return;
  // 后端在 AI 分析过程中持续推送 scores_update
  // 格式: {scores: {technical, fundamental, sentiment, comprehensive}, animate}
  const scores = data.scores || data;
  if (scores.technical != null || scores.comprehensive != null || scores.composite != null) {
    renderScoreCard(scores);
    // 同步写入 store，供其他模块订阅
    store.set('scores', scores);
  }
});

async function fetchFourLayer(code) {
  try {
    const resp = await fetch(`/api/indicators/${encodeURIComponent(code)}/signals`, {
      signal: store.getRequestSignal(),
    });
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.success && data.data) {
      renderSignals(data.data);
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.warn(`four_layer 懒加载失败: ${e.message}`);
  }
}

// ── 生命周期 ─────────────────────────────
function init() {
  logger.info('signals module init');
  bindIndicatorTabs();

  // 评分卡 + 信号 + 指标 默认占位
  renderScoreCard(null);
  renderSignals(null);
  renderIndicators(null);

  // SPA 重新进入 v2：若已有股票，先拉一次
  const cur = store.get('currentStock');
  if (cur) {
    fetchIndicators(cur);
  } else {
    setIndicatorState('empty');
  }

  // 订阅 currentStock 变化 → 重新拉
  store.on('currentStock', (code) => {
    if (code) {
      fetchIndicators(code);
    } else {
      setIndicatorState('empty');
    }
  });
}

if (typeof window !== 'undefined') window.__signals = { renderScoreCard, renderSignals, renderIndicators };

export const signals = { init, fetchIndicators };
