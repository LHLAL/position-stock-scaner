// patrol-page.js · v1.1 · 2026-06-14
// 场景 3 持仓监控 —— 持久化的持仓表 + 实时报价
//
// 数据源：
//   - /api/patrol/positions  GET   持仓列表
//   - /api/patrol/positions/quotes  GET  批量报价
//   - SSE 'log' / 其他事件  → store.events 自动汇集
//
// 行为：
//   - 自动每 5s 刷新报价（交易时段）
//   - 表格列：代码 / 名称 / 成本 / 现价 / 市值 / 盈亏 / 占比 / 操作
//   - 点行 → 跳 /v2?code=xxxxx
//   - 4 态 + sticky header

import { store } from './store.js';
import { navigate } from './router.js';
import { logger } from './logger.js';
import { sse }   from './sse.js';
import { exportCSV, datedFilename } from './exporter.js';

const API = {
  positions: '/api/patrol/positions',
  quotes:    '/api/patrol/positions/quotes',
};

const REFRESH_INTERVAL_MS = 10 * 1000;  // 10s 刷新

let _refreshTimer = null;
let _positions = [];
let _prevPnl = {};  // 用于 P&L 刷新闪烁 {code: pnl}

// ── 拉数据（直接调 API，不依赖 sidebar 时序）──
async function fetchPositions() {
  try {
    const resp = await fetch('/api/patrol/positions');
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.success) {
      _positions = data.positions || data.data || [];
      renderTable(_positions, store.get('quotes') || {});
      if (_positions.length === 0) setState('empty');
      else setState('normal');
      updateStats(_positions, store.get('quotes') || {});
      if (_positions.length) fetchQuotes(_positions.map(p => p.code));
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`fetchPositions 失败: ${e.message}`);
    setState('error');
  }
}

async function fetchQuotes(codes) {
  if (!codes.length) return;
  const myToken = store.getRequestToken();
  try {
    const resp = await fetch(API.quotes, {
      method: 'GET',
      signal: store.getRequestSignal(),
    });
    if (myToken !== store.getRequestToken()) return;
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.success) {
      const byCode = {};
      for (const [, q] of Object.entries(data.quotes || {})) {
        if (q && q.code) {
          byCode[q.code] = {
            ...q,
            price: q.current_price ?? q.price ?? 0,
          };
        }
      }
      store.set('quotes', { ...store.get('quotes'), ...byCode });
      renderTable(_positions, store.get('quotes') || {});
      updateStats(_positions, store.get('quotes') || {});
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.warn(`fetchQuotes 失败: ${e.message}`);
  }
}

// ── Helpers ──
function fmt(v) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
function fmt2(v) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function fmtPct(v) {
  if (v == null || isNaN(v)) return '—';
  return (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
}
function pnlBar(pct) {
  if (pct == null || isNaN(pct)) return '';
  const w = Math.min(Math.abs(pct) * 5, 100); // 每 1% = 5px，最多 100%
  const cls = pct >= 0 ? 'pos' : 'neg';
  return `<span class="pnl-bar ${cls}" style="width:${w}px"></span>`;
}

// ── 渲染 ──
function renderTable(positions, quotes) {
  const tbody = document.getElementById('patrol-tbody');
  if (!tbody) return;

  if (!positions || !positions.length) {
    tbody.innerHTML = `
      <tr><td colspan="8">
        <div class="empty-block" style="padding: var(--space-4);">
          <svg viewBox="0 0 48 48" aria-hidden="true" style="width: 32px; height: 32px;">
            <rect x="8" y="8" width="32" height="32" rx="2"/>
            <path d="M16 24 L20 28 L32 16"/>
          </svg>
          <div class="head" style="font-size: var(--fs-body);">暂无持仓</div>
          <div class="sub">在右侧持仓列表添加股票</div>
        </div>
      </td></tr>`;
    return;
  }

  tbody.innerHTML = positions.map(p => {
    const q = quotes[p.code] || {};
    const current = q.price || 0;
    const cost    = p.cost_price || 0;
    const shares  = p.shares || 0;
    const market  = current * shares;
    const pnl     = (current - cost) * shares;
    const pnlPct  = cost ? ((current - cost) / cost * 100) : 0;
    const pct     = q.change_pct || 0;
    const dayChange = current * shares * (pct / 100);
    // P&L 闪烁：值变化时加动画 class
    const prev = _prevPnl[p.code];
    const flashCls = (prev !== undefined && prev !== pnl) ? 'pnl-flash' : '';
    _prevPnl[p.code] = pnl;
    return `
      <tr data-id="${p.id}" data-code="${p.code}" draggable="true">
        <td class="drag-handle" title="拖拽排序" aria-hidden="true">⋮⋮</td>
        <td>${p.code}</td>
        <td><span class="name" title="${p.name || ''}">${p.name || '名称获取中'}</span></td>
        <td class="num-cell">${fmt2(cost)}</td>
        <td class="num-cell">${fmt2(current)} <span class="${pct >= 0 ? 'pos' : 'neg'}" style="font-size:var(--fs-micro)">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span></td>
        <td class="num-cell">${fmt(market)}</td>
        <td class="num-cell ${pnl >= 0 ? 'pos' : 'neg'} ${flashCls}">${pnl >= 0 ? '+' : ''}${fmt(pnl)} ${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%${pnlBar(pnlPct)}</td>
        <td class="num-cell">${dayChange >= 0 ? '+' : ''}${fmt(dayChange)}</td>
        <td class="col-action">
          <button class="action-btn" title="深度分析 ${p.code}" data-action="analyze" data-code="${p.code}">分析</button>
          <button class="action-btn action-btn-del" title="删除 ${p.code}" data-action="remove" data-id="${p.id}" data-code="${p.code}">×</button>
        </td>
      </tr>`;
  }).join('');

  // 事件 - v1.2: 接拖拽排序
  bindRowEvents();
  bindDragEvents();
}

// ── 行事件绑定 · v1.2 ──
function bindRowEvents() {
  const tbody = document.getElementById('patrol-tbody');
  if (!tbody) return;
  tbody.querySelectorAll('tr[data-code]').forEach(tr => {
    tr.style.cursor = 'pointer';
    tr.addEventListener('click', (e) => {
      if (e.target.closest('button')) return;
      const code = tr.dataset.code;
      store.set('currentStock', code);
      navigate(`#/v2?code=${encodeURIComponent(code)}`);
    });
  });
  tbody.querySelectorAll('button[data-action="analyze"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const code = btn.dataset.code;
      store.set('currentStock', code);
      navigate(`#/v2?code=${encodeURIComponent(code)}`);
    });
  });
  tbody.querySelectorAll('button[data-action="remove"]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (confirm(`删除 ${btn.dataset.code}?`)) {
        const pid = Number(btn.dataset.id);
        logger.info(`删除持仓: ${btn.dataset.code}`);
        // v1.2: 真实删除 (成功后本地移除)
        fetch(`/api/patrol/positions/${pid}`, { method: 'DELETE' })
          .then(r => r.json())
          .then(d => {
            if (d.success) {
              _positions = _positions.filter(p => p.id !== pid);
              renderTable(_positions, store.get('quotes') || {});
              updateStats(_positions, store.get('quotes') || {});
            } else {
              logger.error('删除失败: ' + (d.error || 'unknown'));
            }
          })
          .catch(e => logger.error('DELETE 失败: ' + e.message));
      }
    });
  });
}

function updateStats(positions, quotes) {
  const totalCost = positions.reduce((s, p) => s + (p.cost_price || 0) * (p.shares || 0), 0);
  const totalMarket = positions.reduce((s, p) => {
    const cur = (quotes[p.code] || {}).price || 0;
    return s + cur * (p.shares || 0);
  }, 0);
  const totalPnl = totalMarket - totalCost;
  const totalPnlPct = totalCost ? (totalPnl / totalCost * 100) : 0;
  const winCount = positions.filter(p => {
    const cur = (quotes[p.code] || {}).price || 0;
    return cur > (p.cost_price || 0);
  }).length;
  const winRate = positions.length ? (winCount / positions.length * 100) : 0;

  // Mini 进度条
  const pnlBarWidth = Math.min(Math.abs(totalPnlPct) * 5, 100);

  const statsEl = document.getElementById('patrol-stats');
  if (statsEl) {
    statsEl.innerHTML = `
      <div class="kpi">
        <div class="lbl">💰 总市值</div>
        <div class="num">¥${fmt(totalMarket)}</div>
        <div class="kpi-bar-inner"><div style="width:${totalMarket ? 60 : 0}%"></div></div>
      </div>
      <div class="kpi">
        <div class="lbl">📈 总盈亏</div>
        <div class="num ${totalPnl >= 0 ? 'pos' : 'neg'}">${totalPnl >= 0 ? '+' : ''}¥${fmt(Math.abs(totalPnl))} (${totalPnlPct >= 0 ? '+' : ''}${totalPnlPct.toFixed(1)}%)</div>
        <div class="kpi-bar-inner ${totalPnl >= 0 ? 'pos' : 'neg'}"><div style="width:${pnlBarWidth}%"></div></div>
      </div>
      <div class="kpi">
        <div class="lbl">📦 持仓数</div>
        <div class="num">${positions.length}</div>
        <div class="sub">共 ${positions.reduce((s, p) => s + (p.shares || 0), 0).toLocaleString()} 股</div>
      </div>
      <div class="kpi">
        <div class="lbl">🎯 胜率</div>
        <div class="num ${winRate >= 60 ? 'pos' : winRate < 40 ? 'neg' : ''}">${winRate.toFixed(0)}%</div>
        <div class="sub">${winCount} 赚 / ${positions.length - winCount} 亏</div>
      </div>`;
  }
}

function setState(state) {
  const card = document.querySelector('[data-card="patrol-table"]');
  const slot = card?.querySelector('[data-slot="body"]');
  if (slot) slot.setAttribute('data-active-state', state);
}

function updateMeta(text) {
  const meta = document.getElementById('patrol-meta');
  if (meta) meta.textContent = text;
}

// ── 导出 CSV · v1.2 ──
function exportPositionsCSV() {
  if (!_positions.length) {
    logger.warn('当前无持仓,无需导出');
    return;
  }
  const quotes = store.get('quotes') || {};
  const columns = [
    { key: 'code',         label: '代码' },
    { key: 'name',         label: '名称' },
    { key: 'shares',       label: '持股数' },
    { key: 'cost_price',   label: '成本价',  format: v => v ? Number(v).toFixed(3) : '' },
    { key: 'price',        label: '现价',    format: v => v ? Number(v).toFixed(3) : '' },
    { key: 'market_value', label: '市值',    format: (v, r) => ((quotes[r.code]?.price || 0) * (r.shares || 0)).toFixed(2) },
    { key: 'pnl',          label: '盈亏额',  format: (v, r) => (((quotes[r.code]?.price || 0) - (r.cost_price || 0)) * (r.shares || 0)).toFixed(2) },
    { key: 'pnl_pct',      label: '盈亏率',  format: (v, r) => r.cost_price ? ((((quotes[r.code]?.price || 0) - r.cost_price) / r.cost_price) * 100).toFixed(2) + '%' : '' },
    { key: 'change_pct',   label: '当日涨跌', format: v => v != null ? (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' : '' },
    { key: 'project',      label: '项目分组' },
    { key: 'notes',        label: '备注' },
  ];
  // 注入行情价到行
  const rows = _positions.map(p => ({
    ...p,
    price: quotes[p.code]?.price ?? '',
    change_pct: quotes[p.code]?.change_pct ?? '',
  }));
  exportCSV({
    filename: datedFilename('positions'),
    rows,
    columns,
  });
  logger.info(`已导出 ${rows.length} 条持仓`);
}

// ── 拖拽排序 · v1.2 ──
let _dragSrcId = null;
let _dragHover = null;
function bindDragEvents() {
  const tbody = document.getElementById('patrol-tbody');
  if (!tbody) return;
  tbody.querySelectorAll('tr[data-id]').forEach(tr => {
    tr.addEventListener('dragstart', (e) => {
      _dragSrcId = tr.dataset.id;
      tr.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      // 必须 setData 才能在 Firefox 触发 dragover
      e.dataTransfer.setData('text/plain', tr.dataset.id);
    });
    tr.addEventListener('dragend', () => {
      tr.classList.remove('dragging');
      tbody.querySelectorAll('tr.drag-over').forEach(r => r.classList.remove('drag-over'));
      _dragSrcId = null;
      _dragHover = null;
    });
    tr.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      if (_dragHover && _dragHover !== tr) _dragHover.classList.remove('drag-over');
      tr.classList.add('drag-over');
      _dragHover = tr;
    });
    tr.addEventListener('dragleave', () => {
      tr.classList.remove('drag-over');
    });
    tr.addEventListener('drop', async (e) => {
      e.preventDefault();
      tr.classList.remove('drag-over');
      if (!_dragSrcId || _dragSrcId === tr.dataset.id) return;
      const srcId = Number(_dragSrcId);
      const dstId = Number(tr.dataset.id);
      // 计算新顺序：找到 src 在原数组的位置，移到 dst 位置
      const ids = _positions.map(p => p.id);
      const srcIdx = ids.indexOf(srcId);
      const dstIdx = ids.indexOf(dstId);
      if (srcIdx < 0 || dstIdx < 0) return;
      ids.splice(srcIdx, 1);
      ids.splice(dstIdx, 0, srcId);
      _positions = ids.map(id => _positions.find(p => p.id === id));
      // 本地立刻重渲染
      renderTable(_positions, store.get('quotes') || {});
      // 持久化
      try {
        const resp = await fetch('/api/patrol/positions/reorder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ order: ids }),
        });
        const d = await resp.json();
        if (d.success) {
          logger.info(`拖拽排序成功: ${d.updated} 条`);
        } else {
          logger.error('排序持久化失败: ' + (d.error || 'unknown'));
        }
      } catch (err) {
        logger.error('reorder 请求失败: ' + err.message);
      }
    });
  });
}

// ── 同步 store.positions 变化 → 触发重新拉取（patrol 表格不依赖 sidebar 的 store）──
store.on('positions', () => {
  // sidebar 更新了 positions 时，重新拉取最新数据
  fetchPositions();
});

// ── 监听 sidebar 广播的事件（跨模块同步）──
window.addEventListener('positions-updated', () => {
  fetchPositions();
});

// ── 自动刷新 ──
function startAutoRefresh() {
  if (_refreshTimer) return;
  _refreshTimer = setInterval(() => {
    if (_positions.length) fetchQuotes(_positions.map(p => p.code));
  }, REFRESH_INTERVAL_MS);
}

function stopAutoRefresh() {
  if (_refreshTimer) { clearInterval(_refreshTimer); _refreshTimer = null; }
}

// ── 生命周期 ──
let _inited = false;

function init() {
  if (_inited) return;
  _inited = true;
  logger.info('patrol module init');
  fetchPositions();               // 立即拉取数据（sidebar 可能已错过初始广播）
  startAutoRefresh();
  updateMeta(`每 ${REFRESH_INTERVAL_MS / 1000}s 刷新报价`);

  // v1.2: 导出 CSV 按钮
  const exportBtn = document.querySelector('[data-action="export-csv"]');
  if (exportBtn) {
    exportBtn.addEventListener('click', exportPositionsCSV);
  }

  // 页面隐藏时停刷新（节流）
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopAutoRefresh();
    } else {
      // 页面恢复可见时，如果 patrol view 被隐藏则不再刷新
      const patrolView = document.getElementById('view-patrol');
      if (patrolView && patrolView.classList.contains('view-hidden')) return;
      startAutoRefresh();
    }
  });
}

if (typeof window !== 'undefined') window.__patrolPage = { init, fetchPositions };

export const patrolPage = { init };
