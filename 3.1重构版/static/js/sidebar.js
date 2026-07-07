// sidebar.js · v1.3 · 2026-06-14
// 侧边栏 —— 自选股 + 持仓 + 行点击切换股票
//
// v1.1 第二批增量：
// - "+ 加" 按钮可点击 → prompt 输入 code → POST /api/watchlist
// - 删除按钮（hover 显示）→ DELETE /api/watchlist/<code>
// - 抽屉式（移动端）：可被 .sidebar.open 切换
//
// v1.2 推到：拖拽分组、键盘导航、虚拟滚动（持仓多时）

import { store } from './store.js';
import { navigate } from './router.js';
import { logger } from './logger.js';
import { exportCSV, datedFilename } from './exporter.js';

const API = {
  positions: '/api/patrol/positions',
  quotes:    '/api/patrol/positions/quotes',
  watchlist: '/api/watchlist',
};

/** 从后端拉持仓列表（侧边栏第一组） */
async function loadPositions() {
  try {
    const resp = await fetch(API.positions);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.success) {
      store.set('positions', data.positions || data.data || []);
      renderSidebar();
      if (data.positions?.length || data.data?.length) {
        loadQuotes((data.positions || data.data).map(p => p.code));
      }
    } else {
      logger.warn(`positions API: ${data.error || 'unknown error'}`);
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`loadPositions failed: ${e.message}`);
  }
}

/** 拉持仓的实时报价（同时也会带回自选/持仓列表的报价） */
async function loadQuotes(codes) {
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
        if (q && q.code) byCode[q.code] = q;
      }
      // 自选股：服务端只返回持仓报价；自选股走腾讯真实行情
      const watchlist = store.get('watchlist') || [];
      const trackedCodes = (codes && codes.length ? codes : [
        ...new Set([
          ...((store.get('positions') || []).map(p => p.code)),
          ...watchlist.map(w => w.code),
        ]),
      ]).filter(Boolean);
      const missing = trackedCodes.filter(c => !byCode[c]);
      if (missing.length) {
        try {
          const r2 = await fetch(`/api/quote/batch?codes=${encodeURIComponent(missing.join(','))}`, {
            signal: store.getRequestSignal(),
          });
          if (r2.ok) {
            const d2 = await r2.json();
            if (d2 && d2.success && d2.data) {
              for (const [code, q] of Object.entries(d2.data)) {
                byCode[code] = q;
              }
            }
          }
        } catch (_) { /* 自选报价失败不影响主流程 */ }
      }
      store.set('quotes', { ...store.get('quotes'), ...byCode });
      renderSidebar();
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`loadQuotes failed: ${e.message}`);
  }
}

/** v1.2: 把自选股按 project 分组，返回 { project -> items[] } 保持原 sort_order */
function groupWatchlistByProject(watchlist) {
  const groups = new Map();
  for (const w of watchlist) {
    const p = w.project || '默认';
    if (!groups.has(p)) groups.set(p, []);
    groups.get(p).push(w);
  }
  // 组内按 sort_order 升序
  for (const arr of groups.values()) {
    arr.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
  }
  return groups;
}

/** 渲染侧边栏（持仓组 + 自选组, v1.2 自选按 project 分组） */
function renderSidebar() {
  const sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  const positions = store.get('positions') || [];
  const watchlist = store.get('watchlist') || [];
  const quotes = store.get('quotes') || {};
  const currentStock = store.get('currentStock');

  // 持仓组（第一行作为"持仓 (N)" + "+ 加"）
  const positionsHTML = positions.length
    ? positions.map(p => {
        const q = quotes[p.code] || {};
        const pct = q.change_pct != null ? q.change_pct : 0;
        const up = pct >= 0;
        return `
          <div class="row ${up ? 'up' : 'down'} ${p.code === currentStock ? 'active' : ''}" data-code="${p.code}" data-group="position" data-pid="${p.id}" role="button" tabindex="0" aria-label="选择 ${p.name || p.code}">
            <span class="bar" aria-hidden="true"></span>
            <span class="code">${p.code}</span>
            <span class="name">${p.name || '名称获取中'}</span>
            <span class="pct">${up ? '+' : ''}${pct.toFixed(1)}%</span>
            <button class="row-del" data-del-position="${p.id}" data-code="${p.code}" aria-label="删除持仓 ${p.code}" tabindex="-1">×</button>
          </div>`;
      }).join('')
    : '<div class="row empty">暂无持仓</div>';

  // 自选组: v1.2 按 project 分段
  const groups = groupWatchlistByProject(watchlist);
  const watchlistHTML = watchlist.length
    ? Array.from(groups.entries()).map(([project, items]) => {
        const rows = items.map(w => {
          const q = quotes[w.code] || {};
          const pct = q.change_pct != null ? q.change_pct : 0;
          const up = pct >= 0;
          return `
            <div class="row ${up ? 'up' : 'down'} ${w.code === currentStock ? 'active' : ''}"
                 data-code="${w.code}" data-group="watchlist" data-project="${escapeAttr(project)}"
                 draggable="true" tabindex="0" role="button"
                 aria-label="选择 ${w.name || w.code}">
              <span class="bar" aria-hidden="true"></span>
              <span class="code">${w.code}</span>
              <span class="name">${w.name || '—'}</span>
              <span class="pct">${up ? '+' : ''}${pct.toFixed(1)}%</span>
              <button class="row-del" data-del="${w.code}" aria-label="移除 ${w.code}" tabindex="-1">×</button>
            </div>`;
        }).join('');
        return `
          <div class="subgroup" data-subgroup="${escapeAttr(project)}">
            <div class="subgroup-title" data-subgroup-title="${escapeAttr(project)}">
              <span>${escapeHtml(project)} (${items.length})</span>
              <button class="subgroup-rename" data-rename-project="${escapeAttr(project)}" type="button" title="重命名 / 改色" tabindex="-1">✎</button>
            </div>
            ${rows}
            <div class="subgroup-dropzone" data-dropzone="${escapeAttr(project)}" aria-label="${escapeAttr(project)} 投放区"></div>
          </div>`;
      }).join('')
    : '<div class="row empty">暂无自选</div>';

  // 整段重建
  sidebar.innerHTML = `
    <div class="group">
      <div class="group-title"><span>持仓 (${positions.length})</span><button class="group-add" data-add="position" type="button" title="加持仓（v1.2）">+ 加</button></div>
      ${positionsHTML}
    </div>
    <div class="group">
      <div class="group-title">
        <span>自选 (${watchlist.length})</span>
        <button class="group-export" data-export="watchlist" type="button" title="导出自选股为 CSV" ${watchlist.length ? '' : 'disabled'}>导出</button>
        <button class="group-add" data-add="watchlist" type="button" title="加自选股">+ 加</button>
        <button class="group-add-group" data-add-group="watchlist" type="button" title="新建分组">+ 组</button>
      </div>
      ${watchlistHTML}
    </div>
  `;

  // 绑选股事件
  sidebar.querySelectorAll('.row[data-code]').forEach(row => {
    row.addEventListener('click', (e) => {
      // 删除按钮独立处理（不触发选股）
      if (e.target.matches('.row-del')) return;
      const code = row.dataset.code;
      selectStock(code);
    });
    row.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        const code = row.dataset.code;
        selectStock(code);
      }
    });
  });  // 绑"+ 加"按钮
  sidebar.querySelectorAll('.group-add[data-add="watchlist"]').forEach(btn => {
    btn.addEventListener('click', () => promptAddWatchlist());
  });

  // 绑"+ 加" 持仓按钮
  sidebar.querySelectorAll('.group-add[data-add="position"]').forEach(btn => {
    btn.addEventListener('click', () => promptAddPosition());
  });

  // 绑"+ 组"新建分组
  sidebar.querySelectorAll('.group-add-group[data-add-group="watchlist"]').forEach(btn => {
    btn.addEventListener('click', () => promptAddProject());
  });

  // 绑重命名组按钮
  sidebar.querySelectorAll('.subgroup-rename[data-rename-project]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      promptRenameProject(btn.dataset.renameProject);
    });
  });

  // 绑导出按钮(v1.2)
  sidebar.querySelectorAll('.group-export[data-export="watchlist"]').forEach(btn => {
    btn.addEventListener('click', () => exportWatchlistCSV());
  });

  // 绑删除按钮
  sidebar.querySelectorAll('.row-del[data-del]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const code = btn.dataset.del;
      removeWatchlist(code);
    });
  });

  // 绑持仓删除按钮
  sidebar.querySelectorAll('.row-del[data-del-position]').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const pid = Number(btn.dataset.delPosition);
      const code = btn.dataset.code || '';
      removePosition(pid, code);
    });
  });

  // v1.2: 拖拽 · 组内重排 + 跨组移动
  bindWatchlistDragEvents(sidebar);
}

// ── v1.2: 拖拽排序 + 跨组拖动 ──
let _wlDragSrc = null;  // { code, project }

function bindWatchlistDragEvents(sidebar) {
  if (!sidebar) return;
  // 行拖拽源
  sidebar.querySelectorAll('.row[data-group="watchlist"][draggable="true"]').forEach(row => {
    row.addEventListener('dragstart', (e) => {
      _wlDragSrc = { code: row.dataset.code, project: row.dataset.project };
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', row.dataset.code);
    });
    row.addEventListener('dragend', () => {
      row.classList.remove('dragging');
      sidebar.querySelectorAll('.drag-over, .drop-target').forEach(el => {
        el.classList.remove('drag-over', 'drop-target');
      });
      _wlDragSrc = null;
    });
  });
  // 行作为 drop target（行间排序）
  sidebar.querySelectorAll('.row[data-group="watchlist"]').forEach(row => {
    row.addEventListener('dragover', (e) => {
      if (!_wlDragSrc) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      row.classList.add('drag-over');
    });
    row.addEventListener('dragleave', () => row.classList.remove('drag-over'));
    row.addEventListener('drop', async (e) => {
      if (!_wlDragSrc) return;
      e.preventDefault();
      row.classList.remove('drag-over');
      const dstCode = row.dataset.code;
      const dstProject = row.dataset.project;
      if (dstCode === _wlDragSrc.code) return;
      // 同组内重排 vs 跨组
      if (_wlDragSrc.project === dstProject) {
        await reorderWithinProject(_wlDragSrc.project, _wlDragSrc.code, dstCode);
      } else {
        await moveToProject(_wlDragSrc.code, _wlDragSrc.project, dstProject, dstCode);
      }
    });
  });
  // 组投放区（拖到空白处 → 加到该组末尾）
  sidebar.querySelectorAll('.subgroup-dropzone[data-dropzone]').forEach(zone => {
    zone.addEventListener('dragover', (e) => {
      if (!_wlDragSrc) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      zone.classList.add('drop-target');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drop-target'));
    zone.addEventListener('drop', async (e) => {
      if (!_wlDragSrc) return;
      e.preventDefault();
      zone.classList.remove('drop-target');
      const targetProject = zone.dataset.dropzone;
      if (_wlDragSrc.project === targetProject) return;
      await moveToProject(_wlDragSrc.code, _wlDragSrc.project, targetProject, null);
    });
  });
}

/** 同组内拖到 dstCode 之前 */
async function reorderWithinProject(project, srcCode, dstCode) {
  const list = (store.get('watchlist') || []).filter(w => (w.project || '默认') === project);
  const codes = list.map(w => w.code);
  const srcIdx = codes.indexOf(srcCode);
  const dstIdx = codes.indexOf(dstCode);
  if (srcIdx < 0 || dstIdx < 0) return;
  codes.splice(srcIdx, 1);
  codes.splice(dstIdx, 0, srcCode);
  await persistReorder(project, codes);
}

/** 跨组移动: src 从 srcProject 拖到 dstProject,插到 dstCode 之前(或末尾) */
async function moveToProject(srcCode, srcProject, dstProject, dstCode) {
  // 1) src 从 srcProject 中移除
  const srcList = (store.get('watchlist') || []).filter(w => (w.project || '默认') === srcProject);
  const srcCodes = srcList.map(w => w.code).filter(c => c !== srcCode);
  await persistReorder(srcProject, srcCodes);

  // 2) 插到 dstProject
  const dstList = (store.get('watchlist') || []).filter(w => (w.project || '默认') === dstProject);
  const dstCodes = dstList.map(w => w.code);
  const insertAt = dstCode ? dstCodes.indexOf(dstCode) : -1;
  if (insertAt >= 0) {
    dstCodes.splice(insertAt, 0, srcCode);
  } else {
    dstCodes.push(srcCode);
  }
  await persistReorder(dstProject, dstCodes);
}

/** 把某组的 codes 顺序写回后端,后端一次性事务更新 project + sort_order */
async function persistReorder(project, codes) {
  if (!codes.length && project) {
    // 整组清空也走一次,让后端知道顺序(其实不用)
    return;
  }
  const ordered = codes.map((code, i) => ({ code, project, sort_order: i }));
  try {
    const resp = await fetch('/api/watchlist/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ordered }),
    });
    const d = await resp.json();
    if (!d.success) throw new Error(d.error || 'reorder failed');
    // 用后端返回的最新列表覆盖 store
    if (Array.isArray(d.data)) {
      store.set('watchlist', d.data);
      renderSidebar();
    }
    logger.info(`已更新 ${project} 组顺序 (${codes.length} 条)`);
  } catch (e) {
    logger.error(`reorder 失败: ${e.message}`);
  }
}

/** v1.2: 新建分组(弹窗输入组名) */
async function promptAddProject() {
  const name = (window.prompt('新建分组名（如:白马 / 周期 / 题材）') || '').trim();
  if (!name) return;
  // 创建空分组:不直接写库,而是让用户接下来"加自选到该组"
  // 简化:在 store 里临时记一下新建组名,加自选时引导用户选
  // 这里改方案:直接加一条占位自选(弹窗输入 code),若用户取消则清掉
  const code = (window.prompt(`加入 "${name}" 的第一只股票代码:`) || '').trim().toUpperCase();
  if (!code) return;
  await addWatchlist(code, code, name);
}

/** v1.2: 重命名组(弹窗输入新名) */
async function promptRenameProject(oldName) {
  const newName = (window.prompt(`重命名分组 "${oldName}" 为:`, oldName) || '').trim();
  if (!newName || newName === oldName) return;
  try {
    const resp = await fetch('/api/watchlist/rename-project', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old: oldName, new: newName }),
    });
    const d = await resp.json();
    if (!d.success) throw new Error(d.error || 'rename failed');
    if (Array.isArray(d.data)) {
      store.set('watchlist', d.data);
      renderSidebar();
    }
    logger.info(`分组 ${oldName} → ${newName} (${d.updated || 0} 条)`);
  } catch (e) {
    logger.error(`rename 失败: ${e.message}`);
  }
}

// ── 工具:转义 ──
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}
function escapeAttr(s) {
  return String(s ?? '').replace(/"/g, '&quot;');
}

/** v1.2: 导出自选股为 CSV */
function exportWatchlistCSV() {
  const watchlist = store.get('watchlist') || [];
  if (!watchlist.length) {
    logger.warn('自选为空,无需导出');
    return;
  }
  const quotes = store.get('quotes') || {};
  const columns = [
    { key: 'code',       label: '代码' },
    { key: 'name',       label: '名称' },
    { key: 'price',      label: '现价',    format: v => v ? Number(v).toFixed(3) : '' },
    { key: 'change_pct', label: '当日涨跌', format: v => v != null ? (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%' : '' },
  ];
  const rows = watchlist.map(w => ({
    code: w.code,
    name: w.name || '',
    price: quotes[w.code]?.price ?? '',
    change_pct: quotes[w.code]?.change_pct ?? '',
  }));
  exportCSV({
    filename: datedFilename('watchlist'),
    rows,
    columns,
  });
  logger.info(`已导出 ${rows.length} 条自选`);
}

/** 切换选中股票 */
function selectStock(code) {
  if (!code) return;
  const clean = String(code).trim().toUpperCase();
  store.set('currentStock', clean);
  logger.info(`选择股票: ${clean}`);
  // 点击左侧持仓/自选即进入单股深度页，避免已选中但仍停留在其他页面或工具栏未同步
  navigate(`#/v2?code=${encodeURIComponent(clean)}`);
}

// 监听 currentStock 变化，重渲染侧边栏（高亮）
store.on('currentStock', () => renderSidebar());
// 监听持仓/报价变化，重渲染
store.on('positions', () => renderSidebar());
store.on('quotes', () => renderSidebar());

// ── 持仓/自选变化时广播事件，让 patrol 页面同步刷新 ──
function _broadcastPositionsUpdate() {
  window.dispatchEvent(new CustomEvent('positions-updated'));
}

store.on('positions', _broadcastPositionsUpdate);
store.on('watchlist', _broadcastPositionsUpdate);

/** 拉自选列表（v1.1） */
async function loadWatchlist() {
  try {
    const resp = await fetch(API.watchlist, { signal: store.getRequestSignal() });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.success) {
      store.set('watchlist', data.data || []);
      renderSidebar();
      if (data.data && data.data.length) loadQuotes(data.data.map(w => w.code));
    }
  } catch (e) {
    if (e.name === 'AbortError') return;
    logger.error(`loadWatchlist 失败: ${e.message}`);
  }
}

/**
 * 加自选 —— 公共 API（cmdk + sidebar 都调）
 *   - 默认 code = currentStock，否则 prompt 用户输入
 *   - 后端 409 表示已在自选，安静返回
 */
export async function addWatchlist(code, name, project) {
  const target = (code || '').trim().toUpperCase();
  if (!target) return { ok: false, reason: 'empty' };
  try {
    const body = { code: target, name: name || target };
    if (project) body.project = project;
    const resp = await fetch(API.watchlist, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (resp.status === 409) {
      logger.info(`${target} 已在自选`);
      return { ok: true, duplicate: true };
    }
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (data.success) {
      logger.info(`已加入自选: ${target}${project ? ` (${project})` : ''}`);
      // 重新拉服务端真实列表（带 name 等字段）
      await loadWatchlist();
      return { ok: true };
    }
    return { ok: false, reason: data.error };
  } catch (e) {
    logger.error(`加自选失败 ${target}: ${e.message}`);
    return { ok: false, reason: e.message };
  }
}

/** 删自选 */
async function removeWatchlist(code) {
  const target = (code || '').trim();
  if (!target) return;
  try {
    const resp = await fetch(`${API.watchlist}/${encodeURIComponent(target)}`, { method: 'DELETE' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    logger.info(`已移除自选: ${target}`);
    await loadWatchlist();
  } catch (e) {
    logger.error(`删自选失败 ${target}: ${e.message}`);
  }
}

/** 删持仓（按 id 调 DELETE /api/patrol/positions/<id>，成功后重拉持仓 + 广播给巡检页） */
async function removePosition(positionId, code = '') {
  if (!positionId) return;
  if (!window.confirm(`删除持仓 ${code || '#' + positionId}？`)) return;
  try {
    const resp = await fetch(`${API.positions}/${positionId}`, { method: 'DELETE' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json().catch(() => ({}));
    if (data && data.success === false) {
      throw new Error(data.error || '删除失败');
    }
    logger.info(`已移除持仓: ${code || '#' + positionId}`);
    await loadPositions();
    // loadPositions → store.set('positions', …) 已经会触发 _broadcastPositionsUpdate，
    // 巡检页 (patrol-page.js) 会自动重新拉取，无需额外通知。
  } catch (e) {
    logger.error(`删持仓失败 ${code || positionId}: ${e.message}`);
    alert('删除失败: ' + e.message);
  }
}

/** "+ 加" 按钮 → prompt 输入 → addWatchlist */
function promptAddWatchlist() {
  const current = store.get('currentStock');
  // 默认填 currentStock，但允许用户改
  const input = window.prompt('输入 A 股 6 位代码加入自选（如 600519）：', current || '');
  if (input == null) return;          // 用户取消
  const code = input.trim();
  if (!code) return;
  addWatchlist(code);
}

/** 持仓 "+ 加" 按钮 → prompt 输入 → 添加持仓 */
async function promptAddPosition() {
  const current = store.get('currentStock');
  const code = window.prompt('输入股票代码（如 600519）：', current || '');
  if (!code || code.trim() === '') return;

  const sharesStr = window.prompt('输入持仓数量：', '1000');
  if (!sharesStr || sharesStr.trim() === '') return;
  const shares = parseFloat(sharesStr);

  const priceStr = window.prompt('输入成本价格：', '');
  if (!priceStr || priceStr.trim() === '') return;
  const cost_price = parseFloat(priceStr);

  try {
    const resp = await fetch('/api/patrol/positions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stock_code: code.trim().toUpperCase(),
        position_quantity: shares,
        position_price: cost_price,
      }),
    });
    const data = await resp.json();
    if (data.success) {
      logger.info(`已添加持仓: ${code} x${shares} @${cost_price}`);
      await loadPositions();
      renderSidebar();
    } else {
      logger.error(`添加持仓失败: ${data.error}`);
      alert('添加失败: ' + (data.error || '未知错误'));
    }
  } catch (e) {
    logger.error(`添加持仓请求失败: ${e.message}`);
    alert('添加失败: ' + e.message);
  }
}

/** 初始化：拉数据 + 渲染 */
export function initSidebar() {
  renderSidebar();
  loadPositions();
  loadWatchlist();
  initSidebarToggle();
  initNavLinks();
}

/** SPA 导航链接 */
function initNavLinks() {
  document.querySelectorAll('[data-route]').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      navigate(link.dataset.route);
    });
  });
}

/**
 * 抽屉开关 —— v1.1 第二批
 *   - 汉堡按钮 .sidebar-toggle 点击 → toggle body.sidebar-open
 *   - 遮罩 .sidebar-backdrop 点击 → 关闭
 *   - ESC 关闭
 *   - 选中一行后自动关闭（防止移动端选完还得手动关）
 */
function initSidebarToggle() {
  const toggle = document.querySelector('.sidebar-toggle');
  const backdrop = document.querySelector('.sidebar-backdrop');
  if (!toggle) return;

  function open() {
    document.body.classList.add('sidebar-open');
    toggle.setAttribute('aria-expanded', 'true');
    if (backdrop) backdrop.removeAttribute('hidden');
  }
  function close() {
    document.body.classList.remove('sidebar-open');
    toggle.setAttribute('aria-expanded', 'false');
    if (backdrop) backdrop.setAttribute('hidden', '');
  }
  function toggleFn() {
    if (document.body.classList.contains('sidebar-open')) close();
    else open();
  }

  toggle.addEventListener('click', toggleFn);
  if (backdrop) backdrop.addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.body.classList.contains('sidebar-open')) close();
  });
  // 选中一行后自动关（仅小屏抽屉模式下有意义；桌面端 body 永远没 sidebar-open class）
  document.addEventListener('click', (e) => {
    if (!document.body.classList.contains('sidebar-open')) return;
    const row = e.target.closest('.sidebar .row[data-code]');
    if (row && !e.target.matches('.row-del')) close();
  });
}
