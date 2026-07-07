// signals-page.js · v1.1 · 2026-06-14
// 场景 4 市场信号 —— 4 类信号卡片墙
//
// 数据源：/api/signals/<type>  （type = hot / fund / dragon / report）
// v1 mock 返回稳定种子数据
//
// 行为：
// - 4 类信号卡片墙
// - 每类独立 4 态
// - 点卡片跳 /v2?code=xxxxx

import { store } from './store.js';
import { logger } from './logger.js';

const TYPES = [
  { key: 'hot',    label: '🔥 题材热点', desc: '游资流入 + 涨幅领跑' },
  { key: 'fund',   label: '💰 资金流向', desc: '北向 / 主力 / 大单' },
  { key: 'dragon', label: '🐉 龙虎榜',   desc: '游资席位 + 净买卖' },
  { key: 'report', label: '📄 研报',     desc: '机构评级 + 目标价' },
];

let _data = {};
let _prediction = null;

// ── 拉数据 ──
async function fetchPrediction() {
  try {
    const resp = await fetch('/api/signals/today_prediction', { signal: store.getRequestSignal() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');
    _prediction = data.data;
  } catch (e) {
    if (e.name !== 'AbortError') logger.warn(`fetchPrediction 失败: ${e.message}`);
    _prediction = null;
  }
}

async function fetchSignals() {
  const myToken = store.getRequestToken();
  setState('loading');
  try {
    await fetchPrediction();
    const resp = await fetch('/api/signals/all', { signal: store.getRequestSignal() });
    if (myToken !== store.getRequestToken()) return;
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');
    _data = data.data || {};
    renderAll(_data, data.source, data.unavailable || {});
    if (Object.keys(_data).length === 0) setState('empty');
    else setState('normal', data.source);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`fetchSignals 失败: ${e.message}`);
    setState('error');
  }
}

// ── 渲染 ──
function renderAll(data, source = '', unavailable = {}) {
  const grid = document.getElementById('signals-grid');
  if (!grid) return;

  grid.innerHTML = `${renderPrediction(_prediction)}${TYPES.map(t => {
    const items = data[t.key] || [];
    const topItems = items.slice(0, 8);
    return `
      <div class="card signal-card" data-type="${t.key}">
        <div class="card-h">
          <span class="title">${t.label}</span>
          <span class="meta">${items.length} 条</span>
        </div>
        <div class="card-b" data-slot="body">
          <div data-state="normal">
            <div style="font-size: var(--fs-caption); color: var(--color-text-2); margin-bottom: var(--space-2);">${t.desc} · ${formatSource(source)}</div>
            ${topItems.length ? renderItems(t.key, topItems) : `
              <div class="sub" style="color: var(--color-text-3);">${unavailable[t.key] || '暂无真实数据'}</div>
            `}
          </div>
          <div data-state="loading" hidden></div>
          <div data-state="empty" hidden></div>
          <div data-state="error" hidden></div>
        </div>
      </div>`;
  }).join('')}`;

  // 绑卡片内事件
  grid.querySelectorAll('.signal-card').forEach(card => {
    const type = card.dataset.type;
    const slot = card.querySelector('[data-slot="body"]');
    slot.setAttribute('data-active-state', 'normal');

    // 点项目跳深度分析
    card.querySelectorAll('[data-code]').forEach(el => {
      el.style.cursor = 'pointer';
      el.addEventListener('click', () => {
        window.location.href = `/v2?code=${encodeURIComponent(el.dataset.code)}`;
      });
    });
  });
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function renderPrediction(p) {
  if (!p) {
    return `
      <div class="card" style="grid-column: 1 / -1;">
        <div class="card-h"><span class="title">🔮 今日预测</span><span class="meta">加载失败</span></div>
        <div class="card-b"><div class="sub" style="color: var(--color-text-3);">今日预测暂不可用</div></div>
      </div>`;
  }
  const up = p.up_sectors || [];
  const down = p.down_sectors || [];
  const stocks = p.low_value_stocks || [];
  const policies = p.policy_hits || [];
  const date = p.calendar?.date || '';
  const weekday = p.calendar?.weekday_cn || '';
  const openText = p.calendar?.is_market_open_today ? '今日开盘' : '今日休市';
  return `
    <div class="card signal-card" style="grid-column: 1 / -1;" data-type="prediction">
      <div class="card-h">
        <span class="title">🔮 今日预测</span>
        <span class="meta">${esc(date)} ${esc(weekday)} · ${esc(openText)} · ${esc(p.direction || '震荡')}</span>
      </div>
      <div class="card-b" data-slot="body">
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--space-4);">
          <div>
            <div class="sub" style="color: var(--color-text-3); margin-bottom:6px;">预测上涨板块</div>
            ${up.length ? up.map(x => `<div style="padding:5px 0;border-bottom:1px solid var(--color-border-sub);"><span class="pos">${esc(x.sector)} +${x.score}</span><div class="sub" style="font-size:var(--fs-micro);">${(x.reason || []).slice(0,2).map(esc).join(' / ')}</div></div>`).join('') : '<div class="sub">暂无明确上涨板块</div>'}
          </div>
          <div>
            <div class="sub" style="color: var(--color-text-3); margin-bottom:6px;">预测承压板块</div>
            ${down.length ? down.map(x => `<div style="padding:5px 0;border-bottom:1px solid var(--color-border-sub);"><span class="neg">${esc(x.sector)} ${x.score}</span><div class="sub" style="font-size:var(--fs-micro);">${(x.reason || []).slice(0,2).map(esc).join(' / ')}</div></div>`).join('') : '<div class="sub">暂无明确承压板块</div>'}
          </div>
          <div>
            <div class="sub" style="color: var(--color-text-3); margin-bottom:6px;">5只影响低估值个股</div>
            ${stocks.length ? stocks.map(s => `<div data-code="${esc(s.code)}" style="cursor:pointer; padding:5px 0;border-bottom:1px solid var(--color-border-sub);display:flex;justify-content:space-between;gap:8px;"><div><span class="num">${esc(s.code)}</span> <span>${esc(s.name)}</span><div class="sub" style="font-size:var(--fs-micro);">PE ${s.pe ?? '—'} / PB ${s.pb ?? '—'} · ${esc((s.matched || []).join('/'))}</div></div><span class="${(s.impact_score || 0) >= 0 ? 'pos' : 'neg'}">${(s.impact_score || 0) >= 0 ? '+' : ''}${s.impact_score || 0}</span></div>`).join('') : '<div class="sub">暂无候选</div>'}
          </div>
        </div>
        <div style="margin-top: var(--space-4); display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: var(--space-4);">
          <div>
            <div class="sub" style="color: var(--color-text-3); margin-bottom:6px;">国际股市影响</div>
            <pre style="white-space:pre-wrap;margin:0;font-family:var(--font-sans);font-size:var(--fs-caption);line-height:1.55;color:var(--color-text-2);">${esc(p.global_summary || '暂无')}</pre>
          </div>
          <div>
            <div class="sub" style="color: var(--color-text-3); margin-bottom:6px;">政策/法规/财联社近12小时</div>
            <div class="sub" style="margin-bottom:6px;">财联社样本 ${p.news_count_12h || 0} 条 · ${esc(p.method || '')}</div>
            ${policies.length ? policies.slice(0,4).map(n => `<div style="padding:4px 0;border-bottom:1px solid var(--color-border-sub);">${esc(n.title)}<div class="sub" style="font-size:var(--fs-micro);">${esc(n.time || '')}</div></div>`).join('') : '<div class="sub">暂无明确政策/法规命中</div>'}
          </div>
        </div>
      </div>
    </div>`;
}

function formatSource(source) {
  if (source === 'real:tencent-tracked') return '真实数据 · 腾讯行情（自选/持仓）';
  if (source === 'real:tencent-cache') return '真实数据 · 腾讯行情缓存';
  if (source === 'real') return '真实数据';
  return source || '真实数据';
}

function renderItems(type, items) {
  return items.map((it, i) => {
    if (type === 'hot') {
      return `
        <div data-code="${it.code}" style="display:flex; justify-content:space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border-sub);">
          <div>
            <span class="num">${i + 1}.</span>
            <span style="font-family: var(--font-mono); margin-left: 6px;">${it.code}</span>
            <span style="color: var(--color-text-2); margin-left: 6px;">${it.name}</span>
          </div>
          <span class="pos">+${it.change_pct.toFixed(2)}%</span>
        </div>`;
    } else if (type === 'fund') {
      return `
        <div data-code="${it.code}" style="display:flex; justify-content:space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border-sub);">
          <div>
            <span style="font-family: var(--font-mono);">${it.code}</span>
            <span style="color: var(--color-text-2); margin-left: 6px;">${it.name}</span>
          </div>
          <span class="${it.north_flow == null ? '' : (it.north_flow >= 0 ? 'pos' : 'neg')}">${it.north_flow == null ? `成交量 ${(it.volume || 0).toLocaleString()}` : `${it.north_flow >= 0 ? '+' : ''}${(it.north_flow / 1e8).toFixed(2)}亿`}</span>
        </div>`;
    } else if (type === 'dragon') {
      return `
        <div data-code="${it.code}" style="display:flex; justify-content:space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border-sub);">
          <div>
            <span style="font-family: var(--font-mono);">${it.code}</span>
            <span style="color: var(--color-text-2); margin-left: 6px;">${it.name}</span>
            <span style="color: var(--color-text-3); margin-left: 6px; font-size: var(--fs-micro);">${it.seat || ''}</span>
          </div>
          <span class="${it.net >= 0 ? 'pos' : 'neg'}">${it.net >= 0 ? '+' : ''}${(it.net / 1e4).toFixed(0)}万</span>
        </div>`;
    } else if (type === 'report') {
      return `
        <div data-code="${it.code}" style="display:flex; justify-content:space-between; padding: 4px 0; border-bottom: 1px solid var(--color-border-sub);">
          <div>
            <span style="font-family: var(--font-mono);">${it.code}</span>
            <span style="color: var(--color-text-2); margin-left: 6px;">${it.name}</span>
            <span class="chip" style="margin-left: 6px;">${it.rating || '买入'}</span>
          </div>
          <span style="color: var(--color-text-1);">¥${it.target_price?.toFixed(1) || '—'}</span>
        </div>`;
    }
    return '';
  }).join('');
}

function setState(state, source = '') {
  // 整个页面只有一个 state（不细化到每卡）
  const meta = document.getElementById('signals-meta');
  if (meta) {
    if (state === 'loading') meta.textContent = '加载中…';
    else if (state === 'error') meta.textContent = '加载失败';
    else if (state === 'empty') meta.textContent = '暂无数据';
    else meta.textContent = formatSource(source);
  }
}

// ── 生命周期 ──
let _inited = false;
function init() {
  if (_inited) return;
  _inited = true;
  logger.info('signals-page module init');
  fetchSignals();
  // 每 60s 自动刷新
  setInterval(fetchSignals, 60 * 1000);
}

if (typeof window !== 'undefined') window.__signalsPage = { init, fetchSignals };

export const signalsPage = { init };
