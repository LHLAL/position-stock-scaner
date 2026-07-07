// bottleneck-page.js · v1.0 · 铲子股卡位策略页面
// 路由: #/bottleneck
// 功能: 热门板块选择 + 卡脖子候选股票卡片墙 + 评分排序

import { store } from './store.js';
import { logger } from './logger.js';

const API = '/api/screener/bottleneck';

let _data = null;
let _meta = null;
let _loading = false;
let _activeSectors = [];

// ── 初始化 ──────────────────────────────────
export function init() {
  const root = document.getElementById('view-bottleneck');
  if (!root) return;

  // 绑定刷新按钮
  const refreshBtn = document.getElementById('btn-bottleneck-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => fetchBottleneck(true));
  }

  // 绑定板块过滤器
  const sectorBar = document.getElementById('bottleneck-sectors');
  if (sectorBar) {
    sectorBar.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-sector]');
      if (!btn) return;
      const sector = btn.dataset.sector;
      if (!sector) return;
      // toggle
      const idx = _activeSectors.indexOf(sector);
      if (idx >= 0) {
        _activeSectors.splice(idx, 1);
        btn.classList.remove('on');
      } else {
        _activeSectors.push(sector);
        btn.classList.add('on');
      }
      fetchBottleneck(true);
    });
  }

  // 首次加载
  fetchBottleneck();
  logger.info('bottleneck page init');
}

// ── 拉数据 ──────────────────────────────────
async function fetchBottleneck(force = false) {
  if (_loading) return;
  _loading = true;

  const body = document.getElementById('bottleneck-body');
  if (body) body.innerHTML = '<div style="text-align:center;padding:var(--space-6);color:var(--color-text-3);">加载中…</div>';

  try {
    const params = new URLSearchParams();
    if (_activeSectors.length) {
      params.set('sectors', _activeSectors.join(','));
    }
    params.set('pe_max', '80');
    params.set('pb_max', '10');
    params.set('max_mc', '300');
    params.set('min_turnover', '1.0');
    params.set('limit', '30');

    const url = `${API}?${params.toString()}`;
    const resp = await fetch(url, { signal: store.getRequestSignal() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const json = await resp.json();
    if (!json.success) throw new Error(json.error || 'API error');

    _data = json.data || [];
    _meta = json.meta || {};
    render();
  } catch (e) {
    if (e.name !== 'AbortError') {
      logger.error(`bottleneck fetch failed: ${e.message}`);
      if (body) body.innerHTML = `<div style="text-align:center;padding:var(--space-6);color:var(--color-accent-3);">加载失败: ${e.message}</div>`;
    }
  } finally {
    _loading = false;
  }
}

// ── 渲染 ────────────────────────────────────
function render() {
  const root = document.getElementById('view-bottleneck');
  if (!root) return;

  // 1. 板块过滤器
  const sectorBar = document.getElementById('bottleneck-sectors');
  if (sectorBar && _meta.available_sectors) {
    const available = _meta.available_sectors;
    const html = available.map(s => {
      const active = _activeSectors.includes(s);
      return `<button type="button" data-sector="${s}" class="pill ${active ? 'on' : ''}" title="${s}">${s}</button>`;
    }).join('');
    sectorBar.innerHTML = html;
  }

  // 2. meta 信息
  const metaEl = document.getElementById('bottleneck-meta');
  if (metaEl && _meta) {
    metaEl.textContent = `扫描 ${_meta.scanned || 0} 只 · 命中 ${_meta.candidates_count || 0} 只 · 来源 ${_meta.source || ''}`;
  }

  // 3. sector_summary 柱状图（简单文本版）
  const summaryEl = document.getElementById('bottleneck-summary');
  if (summaryEl && _meta.sector_summary) {
    const items = Object.entries(_meta.sector_summary)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);
    const max = items[0]?.[1] || 1;
    summaryEl.innerHTML = items.map(([name, count]) => {
      const pct = Math.round((count / max) * 100);
      return `
        <div class="bar-row" style="display:flex;align-items:center;gap:8px;margin:4px 0;font-size:var(--fs-caption);">
          <span style="width:80px;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${name}</span>
          <div style="flex:1;height:8px;background:var(--color-bg-1);border-radius:4px;overflow:hidden;">
            <div style="width:${pct}%;height:100%;background:var(--color-accent-2);border-radius:4px;"></div>
          </div>
          <span style="width:30px;text-align:right;">${count}</span>
        </div>`;
    }).join('');
  }

  // 4. 候选卡片墙
  const body = document.getElementById('bottleneck-body');
  if (!body) return;

  if (!_data || !_data.length) {
    body.innerHTML = `
      <div style="grid-column:1/-1;text-align:center;padding:var(--space-6);color:var(--color-text-3);">
        <div style="font-size:var(--fs-body);margin-bottom:var(--space-2);">暂无候选</div>
        <div style="font-size:var(--fs-caption);">${_meta.error || '当前筛选条件下没有匹配的股票，请放宽条件或切换板块'}</div>
      </div>`;
    return;
  }

  body.innerHTML = _data.map(c => renderCard(c)).join('');

  // 5. 绑定卡片点击 → 跳转单股深度
  body.querySelectorAll('[data-code]').forEach(card => {
    card.addEventListener('click', () => {
      const code = card.dataset.code;
      if (code) {
        store.set('currentStock', code);
        window.location.hash = '#/v2';
      }
    });
  });

  // 6. 缓存命中监控面板（异步拉，不阻塞主渲染）
  fetchCacheStats().then(renderCacheStats).catch(() => {});
}

// ── 单张卡片 ────────────────────────────────
function renderCard(c) {
  const changeCls = c.change_pct > 0 ? 'pos' : c.change_pct < 0 ? 'neg' : '';
  const changeSign = c.change_pct > 0 ? '+' : '';
  const multi = (c.multi_sectors || []).length ? `<span class="pill" style="margin-left:4px;">+${c.multi_sectors.length} 热点</span>` : '';

  return `
    <div class="card bottleneck-card" data-code="${c.code}" style="cursor:pointer;" title="点击查看 ${c.code} 深度分析">
      <div class="card-h" style="justify-content:space-between;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="code" style="font-family:var(--font-mono);font-size:var(--fs-body);font-weight:var(--fw-semibold);">${c.code}</span>
          <span class="name" style="font-size:var(--fs-body);">${c.name}</span>
          <span class="pill" style="background:var(--color-bg-1);">${c.sector}</span>
          ${multi}
        </div>
        <div style="font-family:var(--font-mono);font-size:var(--fs-display);font-weight:var(--fw-bold);color:var(--color-accent-2);">${c.score}</div>
      </div>
      <div class="card-b">
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:var(--space-2);font-size:var(--fs-caption);margin-bottom:var(--space-2);">
          <div><span style="color:var(--color-text-2);">现价</span> <b>${c.price.toFixed(2)}</b></div>
          <div><span style="color:var(--color-text-2);">涨跌</span> <b class="${changeCls}">${changeSign}${c.change_pct.toFixed(2)}%</b></div>
          <div><span style="color:var(--color-text-2);">换手</span> <b>${c.turnover.toFixed(1)}%</b></div>
          <div><span style="color:var(--color-text-2);">市值</span> <b>${c.market_cap_yi}亿</b></div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:var(--space-2);font-size:var(--fs-caption);margin-bottom:var(--space-2);">
          <div><span style="color:var(--color-text-2);">PE</span> <b>${c.pe.toFixed(1)}</b></div>
          <div><span style="color:var(--color-text-2);">PB</span> <b>${c.pb.toFixed(1)}</b></div>
          <div><span style="color:var(--color-text-2);">卡脖子</span> <b>${(c.matched_keywords || []).join(', ') || '—'}</b></div>
        </div>
        <div style="font-size:var(--fs-caption);color:var(--color-text-2);line-height:1.5;">
          <b style="color:var(--color-text-1);">卡脖子环节:</b> ${c.bottleneck || '—'}
        </div>
        <div style="font-size:var(--fs-caption);color:var(--color-text-3);margin-top:4px;">${c.reason || ''}</div>
      </div>
    </div>`;
}

// ── 缓存命中监控 ──────────────────────────────
async function fetchCacheStats() {
  const resp = await fetch('/api/cache/stats', { signal: store.getRequestSignal() });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  const json = await resp.json();
  if (!json.success) throw new Error(json.error || 'API error');
  return json.data || {};
}

function renderCacheStats(stats) {
  const container = document.getElementById('bottleneck-cache-panel');
  if (!container) return;
  if (!stats || !stats.total_requests) {
    container.innerHTML = '';
    return;
  }

  const hitRate = stats.hit_rate || 0;
  const rateColor = hitRate >= 80 ? 'var(--color-accent-2)' : hitRate >= 50 ? 'var(--color-accent-1)' : 'var(--color-accent-3)';

  // 最近命中日志
  const recentLog = (stats.recent_log || []).slice(-10).map(entry => {
    const icon = entry.hit ? '✅' : '❌';
    const ts = entry.ts ? entry.ts.split('T')[1]?.split('.')[0] || entry.ts : '';
    return `<span style="font-size:10px;opacity:0.7;">${icon} ${ts}</span>`;
  }).join(' ');

  container.innerHTML = `
    <div style="display:flex;align-items:center;gap:var(--space-3);padding:var(--space-2) var(--space-3);font-size:var(--fs-caption);background:var(--color-bg-1);border-radius:var(--radius-lg);">
      <div style="font-weight:var(--fw-semibold);">🧠 缓存命中</div>
      <div style="flex:1;height:8px;background:var(--color-border);border-radius:4px;overflow:hidden;">
        <div style="width:${hitRate}%;height:100%;background:${rateColor};border-radius:4px;transition:width 0.3s;"></div>
      </div>
      <div style="font-family:var(--font-mono);font-weight:var(--fw-bold);color:${rateColor};">${hitRate}%</div>
      <div style="color:var(--color-text-2);">${stats.hit || 0} 命中 / ${stats.miss || 0} 未命中 / ${stats.active_keys || 0} 活跃键</div>
    </div>
    <div style="padding:var(--space-1) var(--space-3);font-size:var(--fs-caption);color:var(--color-text-3);">${recentLog}</div>
  `;
}
