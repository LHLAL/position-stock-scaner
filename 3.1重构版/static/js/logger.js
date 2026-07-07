// logger.js · v1.2.1 · 2026-06-14
// 日志/状态条 —— 替换老 index.html 的 addLog / clearLog / updateProgress
//
// v1.2.1 修复（Codex review P1）：
//   之前 `log()` 用 `console[type]` 取 console 函数，但 forwardConsole 已
//   override 这些方法 → log → console.info → log → ... 无限递归 → 栈溢出
//   现在 `log()` 用 `_origConsole` 取真正原始的 console 函数，绕过 override
//
// 数据源：store.events（sse.js 自动写入 'log' 事件）
//        + 本地 console 日志（通过 forwardConsole 接管）

import { store } from './store.js';

// ── 保存原始 console（在 forwardConsole 之前）──
const _origConsole = {
  log:   console.log.bind(console),
  warn:  console.warn.bind(console),
  error: console.error.bind(console),
  info:  (console.info || console.log).bind(console),
};

// ── 状态条 ─────────────────────────────────
function renderStatusBar() {
  const statusBar = document.querySelector('.statusbar');
  if (!statusBar) return;
  const sseStatus = store.get('sseStatus');
  const dot = statusBar.querySelector('.dot');
  const label = statusBar.querySelector('[data-sse-label]');

  const map = {
    idle:        { color: 'var(--color-text-3)', text: 'SSE 未连接' },
    connecting:  { color: 'var(--color-accent-4)', text: 'SSE 连接中…' },
    connected:   { color: 'var(--color-accent-2)', text: 'SSE 实时' },
    reconnecting: { color: 'var(--color-accent-4)', text: 'SSE 重连中…' },
    error:       { color: 'var(--color-accent-3)', text: 'SSE 错误' },
  };
  const m = map[sseStatus] || map.idle;
  if (dot) dot.style.background = m.color;
  if (label) label.textContent = m.text;
}

function renderStatusTime() {
  const el = document.querySelector('[data-status-time]');
  if (!el) return;
  el.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
}

// 监听状态变化
store.on('sseStatus', () => renderStatusBar());
document.addEventListener('DOMContentLoaded', () => {
  renderStatusBar();
  renderStatusTime();
  setInterval(renderStatusTime, 1000);
});

// ── 主动 log（同时输出到 console + 写 store.events）──
function log(type, message) {
  // 1. 写真正的 console（用 _origConsole 绕过 override）
  const fn = _origConsole[type] || _origConsole.log;
  fn(`[${type}]`, message);

  // 2. 写 store
  const events = store.get('events') || [];
  // 关键：必须新建数组（不 mutate），否则 store.set 视为 no-op
  const next = [{ ts: Date.now(), type, message }, ...events].slice(0, 100);
  store.set('events', next);
}

export const logger = {
  info:  (msg) => log('info', msg),
  warn:  (msg) => log('warn', msg),
  error: (msg) => log('error', msg),
  /** 清空日志（不影响 sse.js 后续写入） */
  clear: () => store.set('events', []),
};

// ── 把 console 转发到 log 系统（方便调试）──
function forwardConsole() {
  // 注意：override 的 console 方法用 _origConsole 输出到真实 console，
  //       然后调 log()。log() 内部也用 _origConsole，不会触发回环。
  for (const level of ['log', 'warn', 'error']) {
    console[level] = (...args) => {
      _origConsole[level].apply(console, args);
      const msg = args.map(a =>
        typeof a === 'string' ? a : (() => { try { return JSON.stringify(a); } catch { return String(a); } })()
      ).join(' ');
      log(level === 'log' ? 'info' : level, msg);
    };
  }
}
forwardConsole();
