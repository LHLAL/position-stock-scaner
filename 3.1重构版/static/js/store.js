// store.js · v1.2 · 2026-06-14
// 极简中央状态（发布订阅）—— 替代老 index.html 的全局变量污染
//
// 用法：
//   import { store } from './store.js';
//   store.set('currentStock', '600519');
//   store.get('currentStock');
//   store.on('currentStock', (newVal, oldVal) => { ... });
//
// 设计取舍：
// - 不引入第三方状态库（zustand / redux），项目体量不值
// - 不做不可变更新（直接 mutate + 通知），性能足够 + 心智简单
// - key 字符串化，避免 ref equality 问题
// - 持久化仅 client_id（用 localStorage），其他不持久（页面 reload 重新加载）

const _state = {
  // ── 持久化字段（localStorage 同步）──
  clientId: null,        // SSE 重连复用，codex [P1] 关键

  // ── 当前会话状态 ──
  currentStock: null,    // 选中的股票代码
  currentTab: 'analyze', // analyze / batch / patrol / signals

  // ── SSE 连接状态 ──
  sseStatus: 'idle',     // idle / connecting / connected / reconnecting / error
  sseAttempts: 0,        // 重连尝试次数

  // ── 加载状态（每卡片独立）──
  // key: `${cardName}`，value: 'idle' | 'loading' | 'empty' | 'error' | 'stale'
  cardState: {},

  // ── 分析结果（每次新分析覆盖）──
  analysis: null,        // 完整 final_result payload
  scores: null,          // 最新 scores_update
  aiStream: '',          // 累积的 ai_stream chunk
  events: [],            // SSE log 事件流（最近 100 条）

  // ── 侧边栏 ──
  watchlist: [],         // 自选股列表
  positions: [],         // 持仓列表
  quotes: {},            // 实时报价 key: code
};

const _listeners = new Map();  // key -> Set<fn>

// ── 请求取消机制（Codex P2 修复）──
// currentStock 变化时 abort 所有 in-flight fetch，避免旧股票响应覆盖新股票
let _stockController = new AbortController();
let _stockToken = 0;

// ── 持久化字段名 ──
const _PERSIST_KEYS = ['clientId'];

// ── 启动时从 localStorage 恢复 ──
function _loadPersisted() {
  try {
    const stored = localStorage.getItem('stock-scanner-state');
    if (stored) {
      const parsed = JSON.parse(stored);
      for (const key of _PERSIST_KEYS) {
        if (parsed[key] != null) _state[key] = parsed[key];
      }
    }
  } catch (e) {
    console.warn('[store] localStorage parse failed:', e);
  }
  // 第一次访问，生成 client_id
  if (!_state.clientId) {
    _state.clientId = _uuid();
    _persist();
  }
}

function _persist() {
  try {
    const toSave = {};
    for (const key of _PERSIST_KEYS) toSave[key] = _state[key];
    localStorage.setItem('stock-scanner-state', JSON.stringify(toSave));
  } catch (e) {
    console.warn('[store] localStorage save failed:', e);
  }
}

function _uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  // fallback
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function _notify(key, newVal, oldVal) {
  const set = _listeners.get(key);
  if (!set) return;
  for (const fn of set) {
    try { fn(newVal, oldVal); }
    catch (e) { console.error(`[store] listener for "${key}" threw:`, e); }
  }
}

// ── Public API ──
export const store = {
  /** 读取一个 key */
  get(key) { return _state[key]; },

  /** 设置一个 key，触发监听器 */
  set(key, value) {
    const old = _state[key];
    if (old === value) return;
    _state[key] = value;
    if (_PERSIST_KEYS.includes(key)) _persist();
    if (key === 'currentStock') {
      // 取消所有 in-flight fetch
      _stockController.abort();
      _stockController = new AbortController();
      _stockToken += 1;
    }
    _notify(key, value, old);
  },

  /**
   * 获取当前请求的 AbortSignal
   * 用法：fetch(url, { signal: store.getRequestSignal() })
   * 切股票时 signal 自动 abort，浏览器取消网络请求
   */
  getRequestSignal() {
    return _stockController.signal;
  },

  /**
   * 获取当前请求 token（用于响应回来时的"还是同一个请求吗"校验）
   * 用法：
   *   const myToken = store.getRequestToken();
   *   const resp = await fetch(url);
   *   if (store.getRequestToken() !== myToken) return;  // 已被新请求取代
   */
  getRequestToken() {
    return _stockToken;
  },

  /** 批量更新（用 object 浅合并） */
  update(patch) {
    for (const [k, v] of Object.entries(patch)) this.set(k, v);
  },

  /** 订阅一个 key 的变化（fn 立即以当前值调用一次） */
  on(key, fn) {
    if (!_listeners.has(key)) _listeners.set(key, new Set());
    _listeners.get(key).add(fn);
    fn(_state[key], undefined);  // 立即触发
    return () => _listeners.get(key).delete(fn);  // 返回 unsubscribe
  },

  /** 取消订阅（按 fn 引用） */
  off(key, fn) {
    const set = _listeners.get(key);
    if (set) set.delete(fn);
  },

  /** 调试用：打印当前状态 */
  _debug() {
    return JSON.parse(JSON.stringify(_state));
  },
};

// 启动时从 localStorage 恢复 + 生成 client_id
_loadPersisted();

// 调试钩子
if (typeof window !== 'undefined') window.__store = store;
