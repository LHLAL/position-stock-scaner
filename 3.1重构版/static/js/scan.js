// scan.js · v1.2 · 2026-06-14
// 场景 2 扫盘 —— 多股票批量筛选
//
// 数据源：/api/screener (v3.0 production 已有 SmartStockScreener)
//
// 行为：
// - 选股器参数（涨幅/量比/北向/题材）+ 排序
// - 大表格 5000 行虚拟滚动（v1.1 推到 v1.2，本轮用简单 render）
// - 点行 → 跳 /v2?code=xxxxx 进入深度分析
// - v1.2: 每次筛选自动保存快照，提供"对比两次结果"功能
//
// 4 态：normal / loading / empty / error

import { store } from './store.js';
import { logger } from './logger.js';
import { sse }   from './sse.js';
import { exportCSV, datedFilename } from './exporter.js';
import { navigate } from './router.js';

const API = {
  screener: '/api/screener/enriched',  // GET - 增强扫盘（真实行情 + 持仓 + 板块/北向）
  snapshots: '/api/screener/snapshots',
  compare:   '/api/screener/compare',
};

// ── 选股器参数 ──
const FILTERS = [
  { key: 'all',     label: '全部' },
  { key: 'top_gain', label: '涨幅榜',   sortBy: 'change_pct',  asc: false },
  { key: 'top_loss', label: '跌幅榜',   sortBy: 'change_pct',  asc: true  },
  { key: 'volume',  label: '量比榜',   sortBy: 'volume_ratio', asc: false },
  { key: 'north',   label: '北向资金', sortBy: 'north_flow',  asc: false },
  { key: 'hot',     label: '题材热点', sortBy: 'heat',        asc: false },
];

let _activeFilter = 'all';
let _activeScope = 'tracked';  // 'tracked' | 'all'
let _results = [];  // 当前展示的股票列表
let _latestSnapshotId = null;
let _snapshots = [];   // 历史快照列表
let _compareA = null;   // 对比基准
let _compareB = null;   // 对比当前
let _compareResult = null;  // diff 结果

// ── 渲染表格 ──
function renderTable(items) {
  const tbody = document.getElementById('scan-tbody');
  if (!tbody) return;

  if (!items || !items.length) {
    tbody.innerHTML = `
      <tr><td colspan="11">
        <div class="empty-block" style="padding: var(--space-4);">
          <svg viewBox="0 0 48 48" aria-hidden="true" style="width: 32px; height: 32px;">
            <rect x="6" y="10" width="36" height="28" rx="2"/>
            <path d="M12 18 L18 24 L24 18 M30 18 L36 24 M12 30 L18 24 M30 30 L36 24"/>
          </svg>
          <div class="head" style="font-size: var(--fs-body);">暂无符合条件的股票</div>
          <div class="sub">尝试切换筛选或调整参数</div>
        </div>
      </td></tr>`;
    return;
  }

  tbody.innerHTML = items.slice(0, 200).map((s, i) => {
    const cls = (s.change_pct || 0) >= 0 ? 'pos' : 'neg';
    const pnlCls = (s.position_pnl_pct || 0) >= 0 ? 'pos' : 'neg';
    function n(v, d = 2) {
      return v != null && !isNaN(v) ? Number(v).toFixed(d) : '—';
    }
    return `
      <tr data-code="${s.code}" data-index="${i}">
        <td>${i + 1}</td>
        <td class="num-cell">${s.code || '—'}</td>
        <td>${s.name || '—'}${s.in_position ? '<span class="chip">持仓</span>' : ''}</td>
        <td class="num-cell ${cls}">${s.change_pct >= 0 ? '+' : ''}${n(s.change_pct)}%</td>
        <td class="num-cell">${n(s.price)}</td>
        <td class="num-cell">${n(s.volume_ratio)}</td>
        <td class="num-cell">${n(s.turnover_pct)}%</td>
        <td class="num-cell">${n(s.pe, 1)}</td>
        <td class="num-cell ${pnlCls}">${s.position_pnl_pct == null ? '—' : (s.position_pnl_pct >= 0 ? '+' : '') + n(s.position_pnl_pct) + '%'}</td>
        <td class="num-cell">${n(s.final_score)}</td>
        <td>${(s.themes || []).slice(0, 2).map(t => `<span class="chip">${t}</span>`).join('') || '—'}</td>
      </tr>`;
  }).join('');

  // 绑点击行 → 跳 /v2 (SPA 路由)
  tbody.querySelectorAll('tr[data-code]').forEach(tr => {
    tr.addEventListener('click', () => {
      const code = tr.dataset.code;
      store.set('currentStock', code);
      navigate(`#/v2?code=${encodeURIComponent(code)}`);
    });
    tr.style.cursor = 'pointer';
  });
}

function formatFlow(v) {
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(2) + '万';
  return v.toFixed(0);
}

// ── 拉数据 ──
async function fetchScreener(filterKey) {
  const myToken = store.getRequestToken();
  setState(_activeScope === 'all' ? 'loading' : 'loading');

  const filter = FILTERS.find(f => f.key === filterKey) || FILTERS[0];
  const params = new URLSearchParams({
    strategy: filterKey.toUpperCase(),
    limit: _activeScope === 'all' ? '100' : '200',
    scope: _activeScope,
  });

  try {
    const resp = await fetch(API.screener + '?' + params.toString(), {
      method: 'GET',
      signal: store.getRequestSignal(),
    });
    if (myToken !== store.getRequestToken()) return;  // 切股票/切场景，丢弃
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data.success) throw new Error(data.error || 'API error');

    _results = data.data || [];
    if (_results.length === 0) {
      setState('empty');
    } else {
      setState('normal');
      renderTable(_results);
    }
    const scopeLabel = _activeScope === 'all' ? '全市场' : '自选/持仓';
    const source = data.source === 'screener:v3'
      ? '智能选股引擎'
      : (data.source === 'real:tencent-tracked' ? '腾讯行情' : (data.source || '未知'));
    const timeLabel = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    updateMeta(`${_results.length} 只 · ${filter.label} · ${scopeLabel} · ${source} · ${timeLabel}`);

    // 保存快照：仅关注池（避免全市场数据污染 snapshots 对比功能）
    if (_activeScope === 'tracked') {
      try {
        const codes = _results.map(r => r.code);
        const resp2 = await fetch('/api/screener/snapshots', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            label: filter.label,
            strategy: filter.key,
            params: {},
            codes: codes,
          }),
        });
        const d2 = await resp2.json();
        if (d2.success) {
          _latestSnapshotId = d2.id;
        }
      } catch (e) { /* 非致命 */ }

      // 加载快照列表（用于"对比"）
      loadSnapshotsList();
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`扫盘失败: ${e.message}`);
    setState('error');
  }
}

// ── 4 态驱动 ──
function setState(state) {
  const card = document.querySelector('[data-card="scan-table"]');
  const slot = card?.querySelector('[data-slot="body"]');
  if (!slot) return;
  slot.setAttribute('data-active-state', state);
  slot.querySelectorAll('[data-state]').forEach(el => {
    el.hidden = el.dataset.state !== state;
  });
}

function updateMeta(text) {
  const meta = document.getElementById('scan-meta') || document.getElementById('scan-table-meta');
  if (meta) meta.textContent = text;
}

// ── 筛选按钮 + 范围切换 ──
function bindFilters() {
  const bar = document.getElementById('scan-filters');
  if (!bar) return;

  // 范围切换（关注池 / 全市场）
  const scopeToggle = document.createElement('span');
  scopeToggle.style.cssText = 'display:flex; gap:2px; margin-right:8px; padding-right:8px; border-right:1px solid var(--color-border);';
  ['tracked', 'all'].forEach(s => {
    const btn = document.createElement('button');
    const labels = { tracked: '📌 关注池', all: '🌐 全市场' };
    btn.textContent = labels[s] || s;
    btn.dataset.scope = s;
    if (s === _activeScope) btn.classList.add('on');
    btn.addEventListener('click', () => {
      _activeScope = s;
      scopeToggle.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.scope === s));
      // 重新加载
      fetchScreener(_activeFilter);
    });
    scopeToggle.appendChild(btn);
  });
  bar.appendChild(scopeToggle);

  // 筛选策略按钮
  FILTERS.forEach(f => {
    const btn = document.createElement('button');
    btn.textContent = f.label;
    btn.dataset.filter = f.key;
    if (f.key === _activeFilter) btn.classList.add('on');
    btn.addEventListener('click', () => {
      // 只移除筛选按钮的 on，保留范围切换的 on
      bar.querySelectorAll('[data-filter]').forEach(b => b.classList.remove('on'));
      btn.classList.add('on');
      _activeFilter = f.key;
      fetchScreener(f.key);
    });
    bar.appendChild(btn);
  });
}

// ── v1.2 快照加载 / 对比 ──
async function loadSnapshotsList() {
  try {
    const resp = await fetch(API.snapshots, { signal: store.getRequestSignal() });
    const d = await resp.json();
    if (!d.success) return;
    _snapshots = d.snapshots || [];
    // 当前选中的快照设为最新一条
    if (_latestSnapshotId == null && _snapshots.length) {
      _latestSnapshotId = _snapshots[0].id;
    }
  } catch (e) {
    logger.warn('loadSnapshotsList 失败: ' + e.message);
  }
}

/** 拉两条快照做 diff */
async function compareTwoSnapshots(aId, bId) {
  if (aId === bId) {
    _compareResult = null;
    return;
  }
  try {
    const resp = await fetch(`${API.compare}?a=${aId}&b=${bId}`);
    const d = await resp.json();
    if (!d.success) {
      logger.error('对比失败: ' + (d.error || 'unknown'));
      return;
    }
    _compareA = d.a;
    _compareB = d.b;
    _compareResult = d;
    renderCompareDiff();
  } catch (e) {
    logger.error('compare 请求失败: ' + e.message);
  }
}

/** 渲染 diff：在结果表里按 entered / exited / still_in 上色 */
function renderCompareDiff() {
  if (!_compareResult) return;
  const { entered, exited, still_in } = _compareResult;
  const tbody = document.getElementById('scan-tbody');
  if (!tbody) return;
  // 给行打 class
  tbody.querySelectorAll('tr[data-code]').forEach(tr => {
    const code = tr.dataset.code;
    tr.classList.remove('cmp-entered', 'cmp-exited', 'cmp-still');
    if (entered.includes(code)) tr.classList.add('cmp-entered');
    else if (exited.includes(code)) tr.classList.add('cmp-exited');
    else if (still_in.includes(code)) tr.classList.add('cmp-still');
  });
  updateMeta(
    `对比 #${_compareA.id} → #${_compareB.id}  ` +
    `新增 ${entered.length}  退出 ${exited.length}  仍持 ${still_in.length}`,
  );
}

/** 暴露给外部 UI（页面 / dev tools）的 diff API */
function compareWithSnapshot(snapshotId) {
  compareTwoSnapshots(snapshotId, _latestSnapshotId);
}

// ── 初始化 ──
let _inited = false;
function init() {
  if (_inited) return;
  _inited = true;
  logger.info('scan module init');
  bindFilters();
  fetchScreener(_activeFilter);
  loadSnapshotsList();

  // v1.2: 导出 CSV
  const exportBtn = document.querySelector('[data-action="export-csv"]');
  if (exportBtn) {
    exportBtn.addEventListener('click', exportScanCSV);
  }
}

/** v1.2: 导出当前扫盘结果 */
function exportScanCSV() {
  if (!_results.length) {
    logger.warn('当前结果为空,无需导出');
    return;
  }
  const filter = FILTERS.find(f => f.key === _activeFilter) || FILTERS[0];
  const columns = [
    { key: 'code',        label: '代码' },
    { key: 'name',        label: '名称' },
    { key: 'price',       label: '现价',     format: v => v ? Number(v).toFixed(3) : '' },
    { key: 'change_pct',  label: '涨跌幅',   format: v => v != null ? (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' : '' },
    { key: 'volume_ratio',label: '量比',     format: v => v ? Number(v).toFixed(2) : '' },
    { key: 'volume',      label: '成交量' },
    { key: 'north_flow',  label: '北向资金', format: v => v ? formatFlow(v) : '' },
    { key: 'sector',      label: '行业' },
    { key: 'themes',      label: '题材',     format: v => Array.isArray(v) ? v.join('/') : (v || '') },
    { key: 'final_score', label: '综合分' },
  ];
  exportCSV({
    filename: datedFilename(`scan-${filter.key}`),
    rows: _results,
    columns,
  });
  logger.info(`已导出 ${_results.length} 条扫盘结果 (${filter.label})`);
}

if (typeof window !== 'undefined') window.__scan = { init, fetchScreener, compareWithSnapshot, loadSnapshotsList };

export const scan = { init, compareWithSnapshot };
