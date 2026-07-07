// market.js · v1.0 · 2026-06-17
// 市场情绪 + 个股新闻/板块政策

import { store } from './store.js';
import { logger } from './logger.js';

const API = {
  sentiment: '/api/sentiment/market',
  news: (code) => `/api/news/${encodeURIComponent(code)}`,
};

let _inited = false;
let _lastSentimentTs = 0;
const SENTIMENT_TTL_MS = 60 * 1000;

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function fmtPct(v) {
  const n = Number(v || 0);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function fmtYi(v) {
  const n = Number(v || 0);
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}亿`;
}

function cls(v) {
  return Number(v || 0) >= 0 ? 'pos' : 'neg';
}

function renderSentiment(data) {
  const box = document.getElementById('market-sentiment-box');
  const meta = document.getElementById('market-sentiment-meta');
  if (!box) return;

  if (!data) {
    box.innerHTML = `<div class="empty-block" style="padding: var(--space-3);"><div class="sub">暂无市场情绪数据</div></div>`;
    return;
  }

  const ad = data.advance_decline || {};
  const indices = data.indices || [];
  const top = data.sector_top || [];
  const bot = data.sector_bot || [];
  const inflow = data.sector_inflow || [];
  const nb = data.northbound || data.north || {};
  const political = data.political_sector_impact || [];
  const temp = Number(data.thermometer || data.advance_decline?.up - data.advance_decline?.down || 0);
  const tempCls = temp >= 0 ? 'pos' : 'neg';

  const metaText = data.mood || '中性';
  if (meta) meta.textContent = `真实数据 · ${metaText} · 北向 ${fmtYi(nb.total_yi)}`;

  box.innerHTML = `
    <div class="score-card-row" style="align-items: stretch; gap: var(--space-3);">
      <div class="score-cell score-${temp >= 0 ? 'up' : 'down'}" style="min-width: 140px;">
        <div class="num ${tempCls}" style="color: var(--color-accent-${temp >= 0 ? 2 : 3});">${temp >= 0 ? '+' : ''}${temp.toFixed(1)}</div>
        <div class="lbl">情绪温度</div>
        <div class="sub" style="font-size: var(--fs-micro); color: var(--color-text-3);">${esc(data.mood || '中性')}</div>
      </div>
      <div style="flex:1; display:grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: var(--space-2);">
        ${indices.map(i => `
          <div class="kpi" style="padding: var(--space-2);">
            <div class="lbl">${esc(i.name)}</div>
            <div class="num ${cls(i.change_pct)}" style="font-size: var(--fs-body);">${Number(i.price || 0).toFixed(2)} ${fmtPct(i.change_pct)}</div>
          </div>`).join('')}
      </div>
    </div>
    <div style="margin-top: var(--space-3); display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-3);">
      <div>
        <div class="sub" style="color: var(--color-text-3); margin-bottom:4px;">市场宽度</div>
        <div>上涨 <span class="pos">${ad.up || 0}</span> / 下跌 <span class="neg">${ad.down || 0}</span> / 平盘 ${ad.flat || 0}</div>
        <div>涨停 <span class="pos">${ad.limit_up || 0}</span> / 跌停 <span class="neg">${ad.limit_down || 0}</span></div>
      </div>
      <div>
        <div class="sub" style="color: var(--color-text-3); margin-bottom:4px;">领涨板块</div>
        ${top.length ? top.map(s => `<div>${esc(s.name)} <span class="pos">${fmtPct(s.change_pct)}</span></div>`).join('') : '<div class="sub">暂无板块涨幅数据</div>'}
      </div>
      <div>
        <div class="sub" style="color: var(--color-text-3); margin-bottom:4px;">领跌板块</div>
        ${bot.length ? bot.map(s => `<div>${esc(s.name)} <span class="neg">${fmtPct(s.change_pct)}</span></div>`).join('') : '<div class="sub">暂无板块跌幅数据</div>'}
      </div>
      <div>
        <div class="sub" style="color: var(--color-text-3); margin-bottom:4px;">主力流入板块</div>
        ${inflow.length ? inflow.map(s => `<div>${esc(s.name)} <span class="${cls(s.main_net)}">${fmtYi(s.main_net)}</span></div>`).join('') : '<div class="sub">暂无资金流数据</div>'}
      </div>
    </div>
    <div style="margin-top: var(--space-4);">
      <div class="sub" style="color: var(--color-text-3); margin-bottom:8px;">时政 / 政策 / 新闻情绪对板块影响</div>
      ${political.length ? `
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--space-3);">
          ${political.slice(0, 6).map(p => `
            <div class="kpi" style="padding: var(--space-2);">
              <div class="lbl">${esc(p.sector)} <span class="${cls(p.score)}">${esc(p.impact)}</span></div>
              <div class="num ${cls(p.score)}" style="font-size: var(--fs-body);">${p.score >= 0 ? '+' : ''}${Number(p.score || 0).toFixed(1)} · 置信 ${Number(p.confidence || 0).toFixed(0)}%</div>
              <div class="sub" style="font-size: var(--fs-micro); color: var(--color-text-3);">关键词：${(p.keywords || []).map(esc).join(' / ') || '—'}</div>
              <div style="margin-top:4px; font-size: var(--fs-micro); line-height:1.45; color: var(--color-text-2);">
                ${(p.headlines || []).slice(0, 2).map(h => `<div>• ${esc(h.title)}</div>`).join('')}
              </div>
            </div>`).join('')}
        </div>` : '<div class="sub">暂无可归因的政策/时政情绪数据</div>'}
    </div>`;
}

function renderNews(data) {
  const box = document.getElementById('stock-news-box');
  const meta = document.getElementById('stock-news-meta');
  if (!box) return;
  if (!data) {
    box.innerHTML = `<div class="empty-block" style="padding: var(--space-3);"><div class="sub">选择股票后加载新闻</div></div>`;
    if (meta) meta.textContent = '真实数据源';
    return;
  }

  const stock = data.stock_news || [];
  const sector = data.sector_news || [];
  const market = data.market_news || [];
  const cls = data.cls_news || [];
  const m = data.meta || {};
  if (meta) meta.textContent = `${m.name || m.code || ''} · ${m.sector || '行业未知'} · 财联社+东财`;

  const section = (title, rows) => `
    <div>
      <div class="sub" style="color: var(--color-text-3); margin-bottom:6px;">${title}</div>
      ${rows.length ? rows.slice(0, 6).map(n => `
        <div style="padding:6px 0; border-bottom: var(--border-w-1) solid var(--color-border);">
          <a href="${esc(n.url || '#')}" target="_blank" rel="noopener" style="color: var(--color-text-1); text-decoration:none;">${esc(n.title || '无标题')}</a>
          <div class="sub" style="font-size: var(--fs-micro); color: var(--color-text-3);">${esc(n.date || '')} · ${esc(n.source || '')}</div>
        </div>`).join('') : '<div class="sub">暂无数据</div>'}
    </div>`;

  box.innerHTML = `
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: var(--space-4);">
      ${section('个股新闻', stock)}
      ${section('板块/政策', sector)}
      ${section('财联社电报', cls)}
      ${section('7×24 快讯', market)}
    </div>`;
}

async function fetchSentiment({ force = false } = {}) {
  const now = Date.now();
  if (!force && now - _lastSentimentTs < SENTIMENT_TTL_MS) return;
  _lastSentimentTs = now;
  try {
    const resp = await fetch(API.sentiment, { signal: store.getRequestSignal() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');
    renderSentiment(data.data);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.warn(`市场情绪加载失败: ${e.message}`);
    renderSentiment(null);
  }
}

async function fetchNews(code) {
  if (!code) {
    renderNews(null);
    return;
  }
  try {
    const resp = await fetch(API.news(code), { signal: store.getRequestSignal() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');
    if (store.get('currentStock') !== code) return;
    renderNews(data.data);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.warn(`新闻加载失败: ${e.message}`);
    renderNews(null);
  }
}

function init() {
  if (_inited) return;
  _inited = true;
  logger.info('market module init');
  fetchSentiment({ force: true });
  const cur = store.get('currentStock');
  if (cur) fetchNews(cur);
  else renderNews(null);
  store.on('currentStock', (code) => {
    fetchSentiment({ force: false });
    fetchNews(code);
  });
}

if (typeof window !== 'undefined') window.__market = { init, fetchSentiment, fetchNews };

export const market = { init, fetchSentiment, fetchNews };
