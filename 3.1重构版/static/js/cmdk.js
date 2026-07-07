// cmdk.js · v1.5 · 2026-06-14
// ⌘K 命令面板 —— 快速搜索 + 操作
//
// v1 范围：
//   - 搜索股票（从 store.positions / store.watchlist）
//   - 内置命令（重新分析、刷新 SSE、清空日志、切换主题）
//   - 加入自选（v1.1 已接 sidebar.addWatchlist 真 API）
// v1.2 交付：
//   - 模糊匹配 Fuse.js（动态 import 失败时回退 includes）
//   - 历史命令（localStorage 持久化，最近 20 条）
//
// 快捷键：
//   - ⌘K / Ctrl+K → 打开
//   - Esc → 关闭
//   - ↑↓ / Tab → 上下选
//   - Enter → 执行
//   - ⌫（在空输入框）→ 删除当前选中的历史项
//
// 数据流：纯前端，订阅 store 变化

import { store } from './store.js';
import { logger } from './logger.js';
import { sse }   from './sse.js';
import { addWatchlist } from './sidebar.js';
import { navigate } from './router.js';

// ── Fuse.js 动态加载 ───────────────────────
// v1.2: 用 ESM dynamic import 拉 Fuse.js（jsDelivr ESM 构建，~7KB gz）
//   - 首次打开 ⌘K 时触发加载（不影响首屏）
//   - 加载失败 → 回退 includes 子串匹配
//   - 加载中 → 也回退 includes（Fuse 加载是异步，必须 sync 给出结果）
let _fuse = null;
let _fuseLoadPromise = null;
const FUSE_OPTIONS = {
  keys: [
    { name: 'label',    weight: 0.5 },
    { name: 'keywords', weight: 0.4 },
    { name: 'sub',      weight: 0.1 },
  ],
  threshold: 0.4,         // 拼写容错：0=精确，1=全部通过
  distance: 100,          // 字符距离
  ignoreLocation: true,   // 全局搜索，不要 position-sensitive
  minMatchCharLength: 1,
  includeScore: false,
};
function _loadFuse() {
  if (_fuseLoadPromise) return _fuseLoadPromise;
  _fuseLoadPromise = import('https://cdn.jsdelivr.net/npm/fuse.js@7.0.0/dist/fuse.mjs')
    .then(mod => {
      _fuse = mod.default;
      logger.info('cmdk: Fuse.js 加载完成');
      return _fuse;
    })
    .catch(e => {
      logger.warn(`cmdk: Fuse.js 加载失败，回退 includes: ${e.message}`);
      _fuse = null;
      _fuseLoadPromise = null;  // 允许重试
      return null;
    });
  return _fuseLoadPromise;
}
// 启动时预加载（fire-and-forget，等 ⌘K 打开时就绪）
_loadFuse();

// ── 历史命令 store · v1.2 交付 ────────────
const HISTORY_KEY = 'cmdk-history';
const HISTORY_MAX = 20;

function _loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY);
    if (!raw) return [];
    const arr = JSON.parse(raw);
    return Array.isArray(arr) ? arr.slice(0, HISTORY_MAX) : [];
  } catch { return []; }
}
function _saveHistory(arr) {
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(arr.slice(0, HISTORY_MAX))); } catch {}
}
/** 推入一条历史。已存在则移到首位(去重)。 */
function _pushHistory(item) {
  if (!item || !item.id) return;
  let arr = _loadHistory().filter(h => h.id !== item.id);
  arr.unshift({
    id: item.id,
    type: item.type || 'cmd',
    label: item.label,
    sub: item.sub || '',
    keywords: item.keywords || [],
    at: Date.now(),
  });
  arr = arr.slice(0, HISTORY_MAX);
  _saveHistory(arr);
}
/** 删除一条历史。 */
function _removeHistory(id) {
  const arr = _loadHistory().filter(h => h.id !== id);
  _saveHistory(arr);
}
/** 把历史项转成可执行项(复用 run 闭包)——不存闭包,重跑时从静态命令 / store 重新拿。 */
function _materializeHistory(h) {
  // 内置命令：重新匹配 BUILTIN_COMMANDS
  const builtin = BUILTIN_COMMANDS.find(c => c.id === h.id);
  if (builtin) return builtin;
  // 股票：去 store 重新构造
  const code = h.id.startsWith('stock-') ? h.id.slice('stock-'.length) : null;
  if (code) {
    const inPositions = (store.get('positions') || []).find(p => p.code === code);
    if (inPositions) {
      return {
        id: h.id, type: 'stock',
        label: `${code}  ${inPositions.name || ''}`,
        sub: inPositions.cost_price ? `成本 ¥${inPositions.cost_price}` : '持仓',
        keywords: [code, inPositions.name || '', 'stock', '股票'],
        run: () => store.set('currentStock', code),
      };
    }
    const inWatchlist = (store.get('watchlist') || []).find(w => w.code === code);
    if (inWatchlist) {
      return {
        id: h.id, type: 'stock',
        label: `${code}  ${inWatchlist.name || ''}`,
        sub: '自选',
        keywords: [code, inWatchlist.name || '', 'stock', '股票'],
        run: () => store.set('currentStock', code),
      };
    }
  }
  // 找不到（比如自选被删了）→ 降级为 no-op
  return {
    id: h.id, type: 'stale',
    label: h.label,
    sub: '已失效',
    keywords: [],
    run: () => { logger.warn(`cmdk 历史项已失效: ${h.id}`); },
  };
}

// ── 内置命令 ─────────────────────────────────
const BUILTIN_COMMANDS = [
  {
    id: 'analyze',
    label: '分析当前股票',
    hint: '触发 AI 流式分析',
    keywords: ['分析', 'analyze', 'ai', '解读'],
    run: () => document.getElementById('btn-analyze')?.click(),
  },
  {
    id: 'reconnect-sse',
    label: '重新连接 SSE',
    hint: '强制重连（断流恢复）',
    keywords: ['重连', 'reconnect', 'sse', '连接'],
    run: () => { sse.reconnect(); },
  },
  {
    id: 'clear-log',
    label: '清空日志',
    hint: '清空 store.events',
    keywords: ['清空', 'clear', 'log', '日志'],
    run: () => { logger.clear(); },
  },
  {
    id: 'refresh-current',
    label: '刷新当前股票',
    hint: '切到同一只股票触发全部卡片重拉',
    keywords: ['刷新', 'refresh', 'reload'],
    run: () => {
      const code = store.get('currentStock');
      if (code) store.set('currentStock', code);
    },
  },
  {
    id: 'add-watchlist',
    label: '把当前股票加入自选',
    hint: 'POST /api/watchlist',
    keywords: ['自选', 'watchlist', '收藏', '加入'],
    run: async () => {
      const code = store.get('currentStock');
      if (!code) {
        // 无 currentStock 时由 sidebar 弹 prompt（cmdk 不直接弹，避免双窗口体验）
        const input = window.prompt('输入要加入自选的代码：', '');
        if (!input) return;
        await addWatchlist(input.trim());
        return;
      }
      await addWatchlist(code);
    },
  },
  {
    id: 'go-scan',
    label: '跳到扫盘',
    hint: '/scan',
    keywords: ['扫盘', 'scan', '筛选', '选股'],
    run: () => { navigate('#/scan'); },
  },
  {
    id: 'go-patrol',
    label: '跳到持仓监控',
    hint: '/patrol',
    keywords: ['持仓', 'patrol', '监控', '盈亏'],
    run: () => { navigate('#/patrol'); },
  },
  {
    id: 'go-signals',
    label: '跳到市场信号',
    hint: '/signals',
    keywords: ['信号', 'signals', '热点', '龙虎榜'],
    run: () => { navigate('#/signals'); },
  },
  {
    id: 'toggle-debug',
    label: '切换调试模式（打印 __store / __sse）',
    hint: 'DevTools 控制台',
    keywords: ['调试', 'debug', 'dev'],
    run: () => {
      console.log('[cmdk] debug snapshot:', {
        store: store._debug(),
        sse: { status: store.get('sseStatus'), attempts: store.get('sseAttempts') },
      });
    },
  },
];

let _isOpen = false;
let _selectedIndex = 0;
let _filteredItems = [];

class CmdK {
  constructor() {
    this._buildDOM();
    this._bindGlobalKeys();
  }

  // ── DOM 构建 ──
  _buildDOM() {
    // 防止重复创建
    if (document.getElementById('cmdk-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'cmdk-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', '命令面板');
    overlay.hidden = true;
    overlay.innerHTML = `
      <div class="cmdk-backdrop"></div>
      <div class="cmdk-panel">
        <div class="cmdk-input-row">
          <span class="cmdk-prefix" aria-hidden="true">⌘K</span>
          <input type="text" id="cmdk-input" placeholder="搜索股票 / 命令…" autocomplete="off" spellcheck="false" />
          <kbd class="cmdk-esc">Esc</kbd>
        </div>
        <div class="cmdk-list" id="cmdk-list" role="listbox" aria-label="命令结果"></div>
        <div class="cmdk-footer">
          <span><kbd>↑↓</kbd> 选择</span>
          <span><kbd>Enter</kbd> 执行</span>
          <span><kbd>Esc</kbd> 关闭</span>
        </div>
      </div>`;
    document.body.appendChild(overlay);

    this._input   = document.getElementById('cmdk-input');
    this._list    = document.getElementById('cmdk-list');
    this._overlay = overlay;

    // 事件
    this._input.addEventListener('input', () => this._render());
    this._input.addEventListener('keydown', (e) => this._onKey(e));

    overlay.querySelector('.cmdk-backdrop').addEventListener('click', () => this.close());
  }

  // ── 全局快捷键 ──
  _bindGlobalKeys() {
    document.addEventListener('keydown', (e) => {
      // ⌘K / Ctrl+K
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        this._isOpen ? this.close() : this.open();
        return;
      }
      // Esc（仅面板打开时）
      if (_isOpen && e.key === 'Escape') {
        e.preventDefault();
        this.close();
      }
    });
  }

  // ── 开 / 关 ──
  open() {
    _isOpen = true;
    this._overlay.hidden = false;
    this._input.value = '';
    this._render();
    setTimeout(() => this._input.focus(), 0);
  }

  close() {
    _isOpen = false;
    this._overlay.hidden = true;
  }

  // ── 列表构建 ──
  _collectItems() {
    const items = [];

    // 股票
    const stocks = [
      ...(store.get('positions') || []).map(p => ({
        id: `stock-${p.code}`,
        type: 'stock',
        label: `${p.code}  ${p.name || ''}`,
        sub: p.cost_price ? `成本 ¥${p.cost_price}` : '持仓',
        keywords: [p.code, p.name || '', 'stock', '股票'],
        run: () => store.set('currentStock', p.code),
      })),
      ...(store.get('watchlist') || []).map(w => ({
        id: `stock-${w.code}`,
        type: 'stock',
        label: `${w.code}  ${w.name || ''}`,
        sub: '自选',
        keywords: [w.code, w.name || '', 'stock', '股票'],
        run: () => store.set('currentStock', w.code),
      })),
    ];

    // 当前选中股票（无论是否在持仓/自选）置顶
    const current = store.get('currentStock');
    if (current) {
      items.push({
        id: `stock-current`,
        type: 'stock',
        label: `${current}  (当前)`,
        sub: '已在分析',
        keywords: [current, 'current', '当前'],
        run: () => { this.close(); },
      });
    }

    items.push(...stocks);
    items.push(...BUILTIN_COMMANDS);
    return items;
  }

  // ── 历史段 · v1.2 ──
  // 打开时若 query 为空,在列表前插入 N 条历史（最多 5 条，避免占据首位）
  _collectWithHistory(query) {
    const all = this._collectItems();
    if (query) return all;  // 有搜索时历史不掺合（结果以搜索为准）
    const history = _loadHistory().slice(0, 5);
    if (!history.length) return all;
    // 历史项物化（重新找 run 闭包）；stale 的降级项仍保留提示
    const historyItems = history.map(h => {
      const m = _materializeHistory(h);
      return { ...m, _isHistory: true, _at: h.at };
    });
    return [...historyItems, ...all];
  }

  _filter(query) {
    const all = this._collectWithHistory(query);
    if (!query) return all;

    const q = query.trim();
    if (!q) return all;

    // v1.2: 优先用 Fuse.js 模糊匹配；未加载完成时回退 includes
    if (_fuse) {
      try {
        const fuse = new _fuse(all, FUSE_OPTIONS);
        const results = fuse.search(q, { limit: 12 });
        return results.map(r => r.item);
      } catch (e) {
        logger.warn(`cmdk: Fuse.search 失败，回退: ${e.message}`);
      }
    }

    // 兜底：includes 子串匹配
    const lower = q.toLowerCase();
    return all.filter(item => {
      const haystack = [
        item.label,
        item.sub || '',
        ...(item.keywords || []),
      ].join(' ').toLowerCase();
      return haystack.includes(lower);
    }).slice(0, 12);
  }

  // ── 渲染 ──
  _render() {
    const query = this._input.value.trim();
    _filteredItems = this._filter(query);
    _selectedIndex = Math.min(_selectedIndex, Math.max(0, _filteredItems.length - 1));

    if (!_filteredItems.length) {
      this._list.innerHTML = `
        <div class="cmdk-empty">无匹配结果</div>`;
      return;
    }

    this._list.innerHTML = _filteredItems.map((item, i) => `
      <div class="cmdk-item ${i === _selectedIndex ? 'on' : ''} ${item._isHistory ? 'is-history' : ''} ${item.type === 'stale' ? 'is-stale' : ''}"
           role="option"
           aria-selected="${i === _selectedIndex ? 'true' : 'false'}"
           data-index="${i}"
           data-type="${item.type}">
        <div class="cmdk-item-label">
          ${item._isHistory ? '<span class="cmdk-tag">历史</span>' : ''}
          ${this._esc(item.label)}
        </div>
        <div class="cmdk-item-sub">${this._esc(item.sub || '')}</div>
      </div>
    `).join('');

    // 鼠标 hover → 选中
    this._list.querySelectorAll('.cmdk-item').forEach(el => {
      el.addEventListener('mouseenter', () => {
        _selectedIndex = Number(el.dataset.index);
        this._highlight();
      });
      el.addEventListener('click', () => this._run(_selectedIndex));
    });
  }

  _highlight() {
    this._list.querySelectorAll('.cmdk-item').forEach((el, i) => {
      el.classList.toggle('on', i === _selectedIndex);
      el.setAttribute('aria-selected', i === _selectedIndex ? 'true' : 'false');
    });
    // 滚动到可视区
    const sel = this._list.querySelector('.cmdk-item.on');
    sel?.scrollIntoView({ block: 'nearest' });
  }

  _esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // ── 键盘 ──
  _onKey(e) {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        _selectedIndex = (_selectedIndex + 1) % _filteredItems.length;
        this._highlight();
        break;
      case 'ArrowUp':
        e.preventDefault();
        _selectedIndex = _selectedIndex === 0 ? _filteredItems.length - 1 : _selectedIndex - 1;
        this._highlight();
        break;
      case 'Enter':
        e.preventDefault();
        this._run(_selectedIndex);
        break;
      case 'Backspace':
        // input 为空 + 当前选中的是历史项 → 删除该历史
        if (this._input.value === '') {
          if (this._deleteCurrentHistory()) {
            e.preventDefault();
          }
        }
        break;
      // Tab / Shift+Tab 不拦截，让浏览器默认走（焦点循环）
      // 没有其他可聚焦元素，所以 Tab 实际没影响；Shift+Tab 也无效果
    }
  }

  _run(index) {
    const item = _filteredItems[index];
    if (!item) return;
    logger.info(`cmdk: ${item.label}`);
    // 写入历史（去重 + 置顶），current / stale 项不写
    if (item.type !== 'stale' && item.id !== 'stock-current') {
      _pushHistory({
        id: item.id,
        type: item.type,
        label: item.label,
        sub: item.sub,
        keywords: item.keywords,
      });
    }
    try { item.run(); }
    catch (e) { logger.error(`cmdk 执行失败: ${e.message}`); }
    this.close();
  }

  /** 删除当前选中的历史项（⌫ 键触发，input 为空时） */
  _deleteCurrentHistory() {
    const item = _filteredItems[_selectedIndex];
    if (!item || !item._isHistory) return false;
    _removeHistory(item.id);
    this._render();
    return true;
  }
}

export const cmdk = new CmdK();

// 调试钩子
if (typeof window !== 'undefined') window.__cmdk = cmdk;
