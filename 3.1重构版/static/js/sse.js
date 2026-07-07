// sse.js · v1.2 · 2026-06-14
// SSE 客户端 —— 修复 Codex [P1] 断流问题
//
// 关键设计：
// 1. **client_id 持久化**：localStorage 存储（store.clientId），跨重连复用
//    防止老 EventSource 换新 client_id 导致后端 SseManager 派发错位
// 2. **指数退避重连**：1s → 2s → 4s → 8s → 16s → 30s（封顶）
// 3. **事件回调注册**：on(eventName, fn) 替代 addEventListener
//    内部仍用 addEventListener，但提供更友好的 API
// 4. **状态可观察**：连接状态写 store.sseStatus，UI 自动响应
//
// 已知事件类型（与后端 src/api/analyze_routes.py 一致）：
//   connected / log / progress / scores_update / ai_stream /
//   final_result / analysis_complete / error

import { store } from './store.js';

const BACKOFF_SCHEDULE = [1000, 2000, 4000, 8000, 16000, 30000];
const MAX_RECONNECT_ATTEMPTS = Infinity;  // 永远重试，UI 可调

// 已知事件类型
const KNOWN_EVENTS = [
  'connected', 'log', 'progress',
  'scores_update', 'ai_stream', 'partial_result',
  'final_result', 'analysis_complete', 'error',
  'news_alert',  // 新闻提醒事件
];

class SSEClient {
  constructor() {
    this._es = null;          // EventSource 实例
    this._handlers = new Map();  // event -> Set<fn>
    this._closing = false;    // 主动关闭标记（重连时跳过）
    this._attempt = 0;        // 当前重连尝试次数
    this._reconnectTimer = null;
  }

  /**
   * 注册事件回调
   * @param {string} event - 事件名（如 'scores_update'）或 '*'（通配）
   * @param {function} fn - 回调 (data: any) => void
   * @returns {function} unsubscribe
   */
  on(event, fn) {
    if (!this._handlers.has(event)) this._handlers.set(event, new Set());
    this._handlers.get(event).add(fn);
    return () => this._handlers.get(event)?.delete(fn);
  }

  /** 取消订阅 */
  off(event, fn) {
    this._handlers.get(event)?.delete(fn);
  }

  /** 启动连接（如果未连接） */
  connect() {
    if (this._es && this._es.readyState !== EventSource.CLOSED) return;
    this._closing = false;
    this._open();
  }

  /** 主动关闭（不再重连） */
  close() {
    this._closing = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._es) {
      this._es.close();
      this._es = null;
    }
    store.set('sseStatus', 'idle');
  }

  /** 强制重连（用户点重连按钮时调用） */
  reconnect() {
    this._attempt = 0;
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    if (this._es) { this._es.close(); this._es = null; }
    this._open();
  }

  // ── 内部 ──

  _open() {
    const clientId = store.get('clientId');
    if (!clientId) {
      console.error('[sse] no clientId in store');
      return;
    }

    store.set('sseStatus', this._attempt === 0 ? 'connecting' : 'reconnecting');
    store.set('sseAttempts', this._attempt);

    const url = `/api/sse?client_id=${encodeURIComponent(clientId)}`;
    console.log(`[sse] connecting (attempt ${this._attempt + 1}): ${url}`);

    try {
      this._es = new EventSource(url);
    } catch (e) {
      console.error('[sse] EventSource ctor failed:', e);
      this._scheduleReconnect();
      return;
    }

    this._es.addEventListener('open', () => {
      console.log('[sse] connected');
      this._attempt = 0;
      store.set('sseStatus', 'connected');
    });

    // 注册所有已知事件类型
    for (const evt of KNOWN_EVENTS) {
      this._es.addEventListener(evt, (e) => this._dispatch(evt, e));
    }

    // 原生 error 事件
    this._es.addEventListener('error', (e) => {
      console.warn('[sse] error event:', e);
      // EventSource 在断网时自动重连，但我们的 url 带 client_id 不会变
      // 这里只需更新状态和清理
      if (this._es && this._es.readyState === EventSource.CLOSED) {
        this._es = null;
        this._scheduleReconnect();
      }
    });
  }

  _dispatch(eventName, event) {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      console.warn(`[sse] failed to parse ${eventName}:`, event.data);
      data = event.data;
    }

    // 1) 触发该事件的所有 handler
    const handlers = this._handlers.get(eventName);
    if (handlers) {
      for (const fn of handlers) {
        try { fn(data); }
        catch (e) { console.error(`[sse] handler for ${eventName} threw:`, e); }
      }
    }

    // 2) 通配 handler
    const wildcards = this._handlers.get('*');
    if (wildcards) {
      for (const fn of wildcards) {
        try { fn(eventName, data); }
        catch (e) { console.error(`[sse] wildcard handler threw:`, e); }
      }
    }

    // 3) 内置副作用：更新 store 的派生状态
    this._applyToStore(eventName, data);
  }

  _applyToStore(eventName, data) {
    switch (eventName) {
      case 'scores_update':
        // Codex P2 修复：scoring 由 signals.js 独占写 store.scores
        // sse.js 只转发事件，不重复写 store
        break;

      case 'ai_stream':
        // 累积到 aiStream（每个 chunk 是 text 片段）
        if (data && typeof data.content === 'string') {
          const prev = store.get('aiStream') || '';
          store.set('aiStream', prev + data.content);
        }
        break;

      case 'final_result':
      case 'analysis_complete':
        store.set('analysis', data);
        store.set('aiStream', '');  // 重置流
        break;

      case 'log':
        if (data && data.message) {
          const events = store.get('events') || [];
          events.unshift({
            ts: Date.now(),
            type: data.type || 'info',
            message: data.message,
          });
          // 保留最近 100 条
          if (events.length > 100) events.length = 100;
          store.set('events', events);
        }
        break;

      case 'progress':
        // progress 事件携带 percent，写入 store 以便 UI 展示进度条
        if (data && typeof data.percent === 'number') {
          // 简化处理：暂时不暴露到 store，UI 自行监听 progress 事件
        }
        break;

      case 'error':
        // 服务端推送的错误事件 —— 记录到 events
        const errs = store.get('events') || [];
        errs.unshift({
          ts: Date.now(),
          type: 'error',
          message: data?.message || JSON.stringify(data),
        });
        if (errs.length > 100) errs.length = 100;
        store.set('events', errs);
        break;
    }
  }

  _scheduleReconnect() {
    if (this._closing) return;
    if (this._attempt >= MAX_RECONNECT_ATTEMPTS) {
      store.set('sseStatus', 'error');
      return;
    }

    const delay = BACKOFF_SCHEDULE[Math.min(this._attempt, BACKOFF_SCHEDULE.length - 1)];
    this._attempt += 1;
    store.set('sseStatus', 'reconnecting');
    store.set('sseAttempts', this._attempt);

    console.log(`[sse] reconnect in ${delay}ms (attempt ${this._attempt})`);
    this._reconnectTimer = setTimeout(() => this._open(), delay);
  }
}

// 单例
export const sse = new SSEClient();

// 调试钩子
if (typeof window !== 'undefined') {
  window.__sse = sse;

  // 页面隐藏时主动断开，可见时重连（节流后台流量 + 提升笔记本续航）
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      // 不主动 close，留给浏览器自然处理
    } else {
      // 回到前台，强制重连一次（防止 stale）
      if (sse._es && sse._es.readyState !== EventSource.OPEN) {
        sse.reconnect();
      }
    }
  });
}
