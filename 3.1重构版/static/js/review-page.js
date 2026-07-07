import { store } from './store.js';
import { logger } from './logger.js';
import { navigate } from './router.js';

let _inited = false;
let _activeMode = 'premarket';
let _data = { premarket: null, postmarket: null };

const API = {
  premarket: '/api/review/premarket',
  postmarket: '/api/review/postmarket',
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function clsByValue(v) {
  const n = Number(v || 0);
  return n > 0 ? 'pos' : n < 0 ? 'neg' : '';
}

async function fetchReview(mode = _activeMode) {
  const body = document.getElementById('review-body');
  const meta = document.getElementById('review-meta');
  if (body) body.innerHTML = renderLoading(mode);
  if (meta) meta.textContent = '加载中…';
  try {
    const resp = await fetch(API[mode], { signal: store.getRequestSignal() });
    const json = await resp.json().catch(() => ({}));
    if (!resp.ok || !json.success) throw new Error(json.error || `HTTP ${resp.status}`);
    _data[mode] = json.data;
    if (_activeMode === mode) render();
    logger.info(`${mode === 'premarket' ? '盘前' : '盘后'}复盘已加载`);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`fetchReview(${mode}) 失败: ${e.message}`);
    if (body) body.innerHTML = renderError(e.message);
    if (meta) meta.textContent = '加载失败';
  }
}

function render() {
  const body = document.getElementById('review-body');
  const meta = document.getElementById('review-meta');
  const data = _data[_activeMode];
  if (!body) return;
  if (!data) {
    body.innerHTML = renderLoading(_activeMode);
    fetchReview(_activeMode);
    return;
  }
  body.innerHTML = _activeMode === 'premarket' ? renderPremarket(data) : renderPostmarket(data);
  if (meta) meta.textContent = `${data.source || '复用现有数据'} · ${formatTime(data.generated_at)}`;
  bindCodeClicks(body);
}

function formatTime(t) {
  if (!t) return '刚刚';
  try { return new Date(t).toLocaleString('zh-CN', { hour12: false }); }
  catch { return t; }
}

function renderLoading(mode) {
  return `
    <div class="card" style="grid-column:1/-1;">
      <div class="card-h"><span class="title">${mode === 'premarket' ? '🌅 盘前复盘' : '📰 盘后复盘'}</span><span class="meta">加载中…</span></div>
      <div class="card-b" style="padding:var(--space-4);">
        <div class="skeleton w70" style="margin-bottom:var(--space-2);"></div>
        <div class="skeleton w90"></div>
      </div>
    </div>`;
}

function renderError(message) {
  return `
    <div class="card" style="grid-column:1/-1;">
      <div class="card-b" style="padding:var(--space-4);">
        <div class="error-block">
          <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M24 4 L44 40 L4 40 Z M24 18 L24 30 M24 34 L24 36"/></svg>
          <div class="head">复盘加载失败</div>
          <div class="code">${esc(message)}</div>
          <div class="actions"><button class="btn-danger" id="btn-review-retry">立即重试</button></div>
        </div>
      </div>
    </div>`;
}

function renderHeadline(d, title) {
  const h = d.headline || {};
  return `
    <div class="card review-headline" style="grid-column:1/-1;">
      <div class="card-h">
        <span class="title">${title}</span>
        <span class="meta">${esc(formatTime(d.generated_at))}</span>
      </div>
      <div class="card-b">
        <div class="review-kpis">
          <div><span class="sub">方向</span><strong>${esc(h.direction || '震荡')}</strong></div>
          <div><span class="sub">仓位</span><strong>${esc(h.position_advice || '控制仓位')}</strong></div>
          <div><span class="sub">风险</span><strong>${esc(h.risk_level || '中')}</strong></div>
        </div>
        <p class="review-summary">${esc(h.summary || '')}</p>
        <div class="review-actions">
          ${(h.actions || []).map((x, i) => `<div><span class="num">${i + 1}.</span>${esc(x)}</div>`).join('') || '<div class="sub">暂无行动建议</div>'}
        </div>
      </div>
    </div>`;
}

function renderTableCard(title, meta, headers, rows, rowFn, empty = '暂无数据') {
  return `
    <div class="card">
      <div class="card-h"><span class="title">${title}</span><span class="meta">${esc(meta || '')}</span></div>
      <div class="card-b flush">
        ${rows && rows.length ? `
          <table class="review-table">
            <thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
            <tbody>${rows.map(rowFn).join('')}</tbody>
          </table>` : `<div class="empty-block" style="padding:var(--space-4);"><div class="sub">${empty}</div></div>`}
      </div>
    </div>`;
}

function renderListCard(title, meta, items, itemFn, empty = '暂无数据') {
  return `
    <div class="card">
      <div class="card-h"><span class="title">${title}</span><span class="meta">${esc(meta || '')}</span></div>
      <div class="card-b">
        <div class="review-list">
          ${items && items.length ? items.map(itemFn).join('') : `<div class="sub">${empty}</div>`}
        </div>
      </div>
    </div>`;
}

function renderPremarket(d) {
  return `
    ${renderHeadline(d, '🌅 盘前操作结论')}
    ${renderTableCard('🔗 板块联动', 'A 股产业链映射', ['产业链', '映射方向', '信号'], d.sector_mapping || [], x => `
      <tr><td>${esc(x.chain)}</td><td>${esc(x.mapping)}</td><td>${esc(x.signal)}</td></tr>`)}
    ${renderListCard('📰 要闻速递', '财联社', d.news || [], (n, i) => `
      <div class="review-news"><span class="num">${i + 1}.</span><div><strong>${esc(n.title)}</strong><div class="sub">${esc(n.date || n.time || n.source || '')}</div></div></div>`)}
    ${renderTableCard('🔥 热点追踪', '今日预测', ['方向', '板块', '分数', '原因'], d.hotspots || [], x => `
      <tr><td class="${x.direction === 'up' ? 'pos' : 'neg'}">${x.direction === 'up' ? '看多' : '承压'}</td><td>${esc(x.name)}</td><td>${esc(x.score)}</td><td>${esc(x.reason)}</td></tr>`)}
    ${renderTableCard('💼 持仓影响', '自选 / 持仓', ['代码', '名称', '盈亏', '影响', '建议'], d.affected_positions || [], x => `
      <tr data-code="${esc(x.code)}"><td class="num">${esc(x.code)}</td><td>${esc(x.name)}</td><td class="${clsByValue(x.profit_loss_pct)}">${x.profit_loss_pct > 0 ? '+' : ''}${esc(x.profit_loss_pct)}%</td><td>${x.impact_score > 0 ? '+' : ''}${esc(x.impact_score)}</td><td>${esc((x.matched || []).join(' / '))}</td></tr>`, '暂无持仓')}
    ${renderTableCard('💎 科技赛道低估值卡位', '热门赛道 · 关键环节 · 可点击深度分析', ['代码', '名称', '赛道/环节', 'PE/PB', '护城河 · 不可替代性'], d.low_value_stocks || [], x => `
      <tr data-code="${esc(x.code)}"><td class="num">${esc(x.code)}</td><td>${esc(x.name)}</td><td><strong>${esc(x.track || '')}</strong><div class="sub" style="font-size:var(--fs-micro);">${esc(x.node || '')}</div></td><td>PE ${esc(x.pe ?? '—')} / PB ${esc(x.pb ?? '—')}</td><td>${esc(x.moat || '')}<div class="sub" style="font-size:var(--fs-micro);">${esc(x.irreplaceable || '')}</div></td></tr>`, '今日热门科技赛道暂无满足低估值的卡位标的')}
  `;
}

function renderPostmarket(d) {
  return `
    ${renderHeadline(d, '📰 盘后复盘结论')}
    ${renderTableCard('📊 大盘解码', '结构强弱', ['对象', '趋势', '特征', '分数'], d.market_decode || [], x => `
      <tr><td>${esc(x.label)}</td><td>${esc(x.trend)}</td><td>${esc(x.feature)}</td><td class="${clsByValue(x.score)}">${x.score > 0 ? '+' : ''}${esc(x.score)}</td></tr>`)}
    ${renderTableCard('😊 市场情绪', '样本 / 主线', ['指标', '数值', '信号'], d.sentiment || [], x => `
      <tr><td>${esc(x.label)}</td><td>${esc(x.value)}</td><td>${esc(x.signal)}</td></tr>`)}
    ${renderListCard('📏 市场宽度', 'MVP 近似', [d.breadth || {}], x => `
      <div><strong>${esc(x.summary || '暂无')}</strong><div class="sub">上涨方向 ${esc(x.up_count || 0)} · 承压方向 ${esc(x.down_count || 0)}</div></div>`)}
    ${renderTableCard('📈 量能分析', 'fallback', ['指标', '数值', '信号'], d.volume || [], x => `
      <tr><td>${esc(x.label)}</td><td>${esc(x.value)}</td><td>${esc(x.signal)}</td></tr>`)}
    ${renderTableCard('🔥 热点回顾', '今日预测', ['方向', '板块', '分数', '原因'], d.hotspots || [], x => `
      <tr><td class="${x.direction === 'up' ? 'pos' : 'neg'}">${x.direction === 'up' ? '强' : '弱'}</td><td>${esc(x.name)}</td><td>${esc(x.score)}</td><td>${esc(x.reason)}</td></tr>`)}
    ${renderTableCard('💼 持仓归因', '收益 / 风险', ['代码', '名称', '盈亏', '今日', '动作'], d.position_attribution || [], x => `
      <tr data-code="${esc(x.code)}"><td class="num">${esc(x.code)}</td><td>${esc(x.name)}</td><td class="${clsByValue(x.profit_loss_pct)}">${x.profit_loss_pct > 0 ? '+' : ''}${esc(x.profit_loss_pct)}%</td><td class="${clsByValue(x.today_change_pct)}">${x.today_change_pct > 0 ? '+' : ''}${esc(x.today_change_pct)}%</td><td>${esc(x.action)}</td></tr>`, '暂无持仓')}
    ${renderListCard('🛡️ 风控检查', '明日前', d.risk_checks || [], (x, i) => `<div><span class="num">${i + 1}.</span>${esc(x)}</div>`)}
    ${renderListCard('🔭 明日策略', '行动清单', d.tomorrow_strategy || [], (x, i) => `<div><span class="num">${i + 1}.</span>${esc(x)}</div>`)}
  `;
}

function bindTabs() {
  const tabs = document.getElementById('review-tabs');
  if (!tabs) return;
  tabs.querySelectorAll('[data-review-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.reviewMode;
      if (!mode || mode === _activeMode) return;
      _activeMode = mode;
      tabs.querySelectorAll('[data-review-mode]').forEach(b => {
        const active = b.dataset.reviewMode === mode;
        b.classList.toggle('on', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      render();
    });
  });
}

function bindCodeClicks(root) {
  root.querySelectorAll('[data-code]').forEach(row => {
    row.style.cursor = 'pointer';
    row.addEventListener('click', () => navigate(`#/v2?code=${encodeURIComponent(row.dataset.code)}`));
  });
}

export function init() {
  if (!_inited) {
    _inited = true;
    bindTabs();
    document.getElementById('btn-review-refresh')?.addEventListener('click', () => fetchReview(_activeMode));
    document.addEventListener('click', (e) => {
      if (e.target?.id === 'btn-review-retry') fetchReview(_activeMode);
    });
  }
  render();
  if (!_data[_activeMode]) fetchReview(_activeMode);
}

if (typeof window !== 'undefined') window.__reviewPage = { init, fetchReview };

export const reviewPage = { init, fetchReview };
