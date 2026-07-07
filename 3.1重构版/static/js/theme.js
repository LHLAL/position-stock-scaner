// theme.js · v1.1 · 2026-06-14
// 浅色 / 深色主题切换
//
// 行为：
//   - 初次加载读 localStorage('theme')；缺失则跟随 prefers-color-scheme
//   - .theme-toggle 点击切换 → html[data-theme="light|dark"] + 写 localStorage
//   - 切换时 dispatch 'theme:change' 事件，让其他模块（图表）重渲染
//
// 选 light/dark 而非"auto"——v1.1 只 ship 二选一，避免 OS 切主题时
// 与用户手动选择的歧义。v1.2 再加 auto 选项（监听 matchMedia change）。

import { logger } from './logger.js';

const STORAGE_KEY = 'theme';

function readPreferred() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
  } catch {}
  // 跟系统
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'light') {
    root.setAttribute('data-theme', 'light');
  } else {
    root.removeAttribute('data-theme');
  }
  // 同步 statusbar 按钮的图标显示
  document.querySelectorAll('[data-theme-icon-dark]').forEach(el => {
    el.toggleAttribute('hidden', theme === 'light');
  });
  document.querySelectorAll('[data-theme-icon-light]').forEach(el => {
    el.toggleAttribute('hidden', theme !== 'light');
  });
  // 触发自定义事件（图表/Plotly 监听重渲染）
  window.dispatchEvent(new CustomEvent('theme:change', { detail: { theme } }));
}

export function initTheme() {
  const initial = readPreferred();
  applyTheme(initial);

  // 绑切换按钮
  document.querySelectorAll('.theme-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
      const next = current === 'light' ? 'dark' : 'light';
      applyTheme(next);
      try { localStorage.setItem(STORAGE_KEY, next); } catch {}
      logger.info(`主题切换: ${next}`);
    });
  });
}

if (typeof window !== 'undefined') window.__theme = { applyTheme, readPreferred };
