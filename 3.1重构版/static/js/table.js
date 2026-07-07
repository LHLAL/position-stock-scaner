// table.js · v1.4 · 2026-06-16
// 财务/估值卡片 · sticky header + zebra + 排序 + 子 tab 切换
//
// v1.4：4 个子 tab 都能切换并展示真实数据。
//   - 财务：腾讯行情 18 项估值/价格字段
//   - 龙虎榜：东财 datacenter
//   - 资金：同花顺北向 + 东财 push2 个股主力
//   - 大宗：东财 datacenter

import { store } from './store.js';
import { logger } from './logger.js';

const API = {
  financials: (code) => `/api/financials/${encodeURIComponent(code)}`,
  dragon:     (code) => `/api/financials/${encodeURIComponent(code)}/dragon`,
  fund:       (code) => `/api/financials/${encodeURIComponent(code)}/fund`,
  block:      (code) => `/api/financials/${encodeURIComponent(code)}/block`,
};

let _sortKey = 'label';
let _sortDir = 'asc';
let _rawData = [];
let _activeTab = 'finance';
let _tabData  = { finance: null, dragon: null, fund: null, block: null };
let _tabError = { finance: null, dragon: null, fund: null, block: null };
let _tabSource = { finance: null, dragon: null, fund: null, block: null };
let _tabMeta  = { finance: null, dragon: null, fund: null, block: null };
let _inited = false;

const UNAVAILABLE_TEXT = {
  finance:{ head: '请选择股票', sub: '选择股票后加载真实财务/估值数据' },
  dragon: { head: '暂无龙虎榜数据', sub: '当前无近期上榜记录' },
  fund:   { head: '暂无资金流向数据', sub: '当前未拉取到北向/主力数据' },
  block:  { head: '暂无大宗交易数据', sub: '当前无近期大宗交易记录' },
};

function describeSource(source) {
  if (!source) return '真实数据';
  if (source === 'real:tencent')           return '真实数据 · 腾讯行情';
  if (source === 'real:eastmoney')          return '真实数据 · 东财数据中心';
  if (source === 'real:hexin+eastmoney')    return '真实数据 · 同花顺 + 东财';
  return source;
}

// ── 渲染 ──
function renderTable(items) {
  const tbody = document.getElementById('financials-tbody');
  const thead = document.getElementById('financials-thead');
  if (!tbody) return;

  if (!items || !items.length) {
    const reason = UNAVAILABLE_TEXT[_activeTab];
    tbody.innerHTML = `
      <tr><td colspan="5">
        <div class="empty-block" style="padding: var(--space-3);">
          <svg viewBox="0 0 48 48" aria-hidden="true" style="width: 32px; height: 32px;">
            <rect x="8" y="8" width="32" height="32" rx="2"/>
            <path d="M14 16 L34 16 M14 22 L34 22 M14 28 L26 28"/>
          </svg>
          <div class="head" style="font-size: var(--fs-body);">${reason.head}</div>
          <div class="sub">${reason.sub}</div>
        </div>
      </td></tr>`;
    return;
  }

  const sorted = [...items].sort((a, b) => {
    const av = a[_sortKey], bv = b[_sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'number' && typeof bv === 'number') {
      return _sortDir === 'asc' ? av - bv : bv - av;
    }
    return _sortDir === 'asc'
      ? String(av).localeCompare(String(bv))
      : String(bv).localeCompare(String(av));
  });

  tbody.innerHTML = sorted.map(({ label, current, previous, change, peer }) => {
    const cls = (change || '').startsWith('+') ? 'pos'
              : (change || '').startsWith('-') ? 'neg' : '';
    return `
      <tr>
        <td>${label}</td>
        <td>${current ?? '—'}</td>
        <td>${previous ?? '—'}</td>
        <td class="${cls}">${change ?? '—'}</td>
        <td>${peer ?? '—'}</td>
      </tr>`;
  }).join('');

  if (thead) {
    thead.querySelectorAll('th[data-sort]').forEach(th => {
      const k = th.dataset.sort;
      const arrow = k === _sortKey ? (_sortDir === 'asc' ? ' ↑' : ' ↓') : '';
      th.setAttribute('aria-sort',
        k === _sortKey ? (_sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
      if (!th.querySelector('.sort-arrow')) {
        const span = document.createElement('span');
        span.className = 'sort-arrow';
        span.style.cssText = 'color: var(--color-accent-1); margin-left: 2px;';
        th.appendChild(span);
      }
      th.querySelector('.sort-arrow').textContent = arrow;
    });
  }
}

function updateFinancialsMeta(source) {
  const meta = document.getElementById('financials-meta');
  if (!meta) return;
  meta.textContent = describeSource(source);
}

function renderActiveTab() {
  const cached = _tabData[_activeTab];
  _rawData = cached || [];
  updateFinancialsMeta(_tabSource[_activeTab]);
  if (cached && cached.length) {
    setState('financials', 'normal');
    renderTable(cached);
  } else if (cached && !cached.length) {
    // 已加载但是空（比如 dragon 暂无上榜）
    setState('financials', 'normal');
    renderTable([]);
  } else {
    setState('financials', 'normal');
    renderTable([]);
  }
}

// ── 拉数据（按 tab）──
async function fetchTab(tab, code) {
  if (!code) return;
  if (_tabData[tab]) {
    renderActiveTab();
    return;
  }
  setState('financials', 'loading');
  const urlByTab = {
    finance: API.financials(code),
    dragon:  API.dragon(code),
    fund:    API.fund(code),
    block:   API.block(code),
  };
  try {
    const resp = await fetch(urlByTab[tab], { signal: store.getRequestSignal() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');

    const items = data.data || [];
    _tabData[tab]   = items;
    _tabSource[tab] = data.source || 'real';
    _tabMeta[tab]   = data.meta || null;
    _tabError[tab]  = null;
    if (_activeTab === tab) {
      _rawData = items;
      updateFinancialsMeta(_tabSource[tab]);
      renderTable(items);
    }
    setState('financials', 'normal');
    logger.info(`financials[${tab}] loaded for ${code} (${items.length} 项)`);
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`fetchTab[${tab}] 失败: ${e.message}`);
    _tabError[tab] = e.message;
    if (_activeTab === tab) {
      _tabData[tab] = [];
      _rawData = [];
      updateFinancialsMeta('真实数据获取失败');
      setState('financials', 'error');
      renderTable([]);
    }
  }
}

function fetchFinancials(code) { return fetchTab('finance', code); }

// ── 子 tab 切换 ──
function bindFinTabs() {
  const tabs = document.getElementById('financial-tabs');
  if (!tabs) return;
  tabs.querySelectorAll('button[data-fin-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      const tab = btn.dataset.finTab;
      if (!tab || tab === _activeTab) return;
      _activeTab = tab;
      tabs.querySelectorAll('button[data-fin-tab]').forEach(b => {
        const active = b.dataset.finTab === _activeTab;
        b.classList.toggle('on', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      renderActiveTab();
      const code = store.get('currentStock');
      if (code && !_tabData[tab]) {
        fetchTab(tab, code);
      }
    });
  });
}

function bindSort() {
  const thead = document.getElementById('financials-thead');
  if (!thead) return;
  thead.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const k = th.dataset.sort;
      if (_sortKey === k) {
        _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        _sortKey = k;
        _sortDir = 'asc';
      }
      renderTable(_rawData);
    });
  });
}

function setState(cardName, state) {
  const card = document.querySelector(`[data-card="${cardName}"]`);
  const slot = card?.querySelector('[data-slot="body"]');
  if (!slot) return;
  slot.setAttribute('data-active-state', state);
  slot.querySelectorAll('[data-state]').forEach(el => {
    el.hidden = el.dataset.state !== state;
  });
}

function init() {
  if (_inited) return;
  _inited = true;
  logger.info('table module init');
  bindSort();
  bindFinTabs();
  renderTable([]);

  // SPA 重新进入 v2 视图：若当前已有股票，幂等拉一次
  const cur = store.get('currentStock');
  if (cur) fetchTab(_activeTab, cur);

  store.on('currentStock', (code) => {
    if (!code) return;
    // 切股票时只预拉当前激活的 tab，不并发打多个接口
    fetchTab(_activeTab, code);
  });
}

if (typeof window !== 'undefined') window.__table = { renderTable, fetchTab, fetchFinancials };

export const table = { init, fetchFinancials };
