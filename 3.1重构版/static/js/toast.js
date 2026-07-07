/**
 * toast.js · 通知提示组件
 * 用于显示新闻提醒、操作反馈等
 */

import { store } from './store.js';
import { logger } from './logger.js';

// Toast 容器
let _container = null;

// 存储当前显示的 toast
const _toasts = new Map(); // id -> element

// 最大显示数量
const MAX_TOASTS = 5;

// 默认显示时长（毫秒）
const DEFAULT_DURATION = {
  info: 5000,
  success: 4000,
  warning: 6000,
  error: 8000,
};

// 颜色映射
const TYPE_COLORS = {
  info: 'var(--color-accent-1)',
  success: 'var(--color-accent-2)', // 红色（上涨）
  warning: 'var(--color-accent-4)',
  error: 'var(--color-accent-3)',   // 绿色（下跌）
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/**
 * 确保容器存在
 */
function ensureContainer() {
  if (_container) return;

  _container = document.createElement('div');
  _container.id = 'toast-container';
  _container.style.cssText = `
    position: fixed;
    top: 70px;
    right: 16px;
    z-index: 9999;
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 400px;
    pointer-events: none;
  `;
  document.body.appendChild(_container);
}

/**
 * 显示 Toast
 * @param {Object} options
 * @param {string} options.title - 标题
 * @param {string} options.message - 消息内容
 * @param {string} options.type - 类型: info / success / warning / error
 * @param {number} options.duration - 显示时长(ms)，0 表示不自动关闭
 * @param {string} options.url - 点击跳转链接
 * @param {string[]} options.stocks - 关联股票代码
 * @returns {string} toast ID
 */
export function showToast({ title, message, type = 'info', duration, url = '', stocks = [] }) {
  ensureContainer();

  const id = 'toast_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
  const color = TYPE_COLORS[type] || TYPE_COLORS.info;
  const autoCloseDuration = duration ?? DEFAULT_DURATION[type] ?? 5000;

  const toast = document.createElement('div');
  toast.id = id;
  toast.style.cssText = `
    background: var(--color-bg-1);
    border: 1px solid var(--color-border);
    border-left: 4px solid ${color};
    border-radius: 4px;
    padding: 12px 16px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    pointer-events: auto;
    cursor: ${url ? 'pointer' : 'default'};
    animation: toastSlideIn 0.3s ease-out;
    transition: all 0.2s ease;
  `;

  // 图标
  const icons = {
    info: 'ℹ️',
    success: '✅',
    warning: '⚠️',
    error: '❌',
  };

  // 关联股票标签
  const stocksHtml = stocks.length ? `
    <div style="margin-top: 6px; display: flex; gap: 4px; flex-wrap: wrap;">
      ${stocks.map(s => `
        <span style="
          font-size: 11px;
          padding: 2px 6px;
          background: var(--color-bg-2);
          border-radius: 3px;
          color: var(--color-text-2);
        ">${esc(s)}</span>
      `).join('')}
    </div>
  ` : '';

  toast.innerHTML = `
    <div style="display: flex; align-items: flex-start; gap: 8px;">
      <span style="font-size: 16px;">${icons[type] || icons.info}</span>
      <div style="flex: 1; min-width: 0;">
        <div style="font-weight: 500; color: var(--color-text-1); margin-bottom: 4px;">
          ${esc(title)}
        </div>
        <div style="font-size: 12px; color: var(--color-text-2); line-height: 1.4;">
          ${esc(message)}
        </div>
        ${stocksHtml}
      </div>
      <button class="toast-close" style="
        background: none;
        border: none;
        padding: 0;
        margin: 0;
        cursor: pointer;
        color: var(--color-text-3);
        font-size: 16px;
        line-height: 1;
        width: 20px;
        height: 20px;
        display: flex;
        align-items: center;
        justify-content: center;
        border-radius: 3px;
      ">×</button>
    </div>
  `;

  // 点击跳转
  if (url) {
    toast.addEventListener('click', (e) => {
      if (e.target.closest('.toast-close')) return;
      window.open(url, '_blank', 'noopener');
    });
  }

  // 关闭按钮
  const closeBtn = toast.querySelector('.toast-close');
  if (closeBtn) {
    closeBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      closeToast(id);
    });
  }

  // 自动关闭
  if (autoCloseDuration > 0) {
    setTimeout(() => closeToast(id), autoCloseDuration);
  }

  // 限制最大数量
  if (_toasts.size >= MAX_TOASTS) {
    const oldestId = _toasts.keys().next().value;
    closeToast(oldestId);
  }

  _container.appendChild(toast);
  _toasts.set(id, toast);

  logger.info(`toast shown: ${title}`);
  return id;
}

/**
 * 关闭指定 Toast
 */
export function closeToast(id) {
  const toast = _toasts.get(id);
  if (!toast) return;

  toast.style.animation = 'toastSlideOut 0.2s ease-in forwards';
  setTimeout(() => {
    toast.remove();
    _toasts.delete(id);
  }, 200);
}

/**
 * 关闭所有 Toast
 */
export function clearAll() {
  for (const id of _toasts.keys()) {
    closeToast(id);
  }
}

/**
 * 快捷方法
 */
export const toast = {
  info: (title, message, opts = {}) => showToast({ title, message, type: 'info', ...opts }),
  success: (title, message, opts = {}) => showToast({ title, message, type: 'success', ...opts }),
  warning: (title, message, opts = {}) => showToast({ title, message, type: 'warning', ...opts }),
  error: (title, message, opts = {}) => showToast({ title, message, type: 'error', ...opts }),
  close: closeToast,
  clearAll,
};

// 添加动画样式
function addAnimations() {
  if (document.getElementById('toast-animations')) return;
  const style = document.createElement('style');
  style.id = 'toast-animations';
  style.textContent = `
    @keyframes toastSlideIn {
      from {
        opacity: 0;
        transform: translateX(100%);
      }
      to {
        opacity: 1;
        transform: translateX(0);
      }
    }
    @keyframes toastSlideOut {
      from {
        opacity: 1;
        transform: translateX(0);
      }
      to {
        opacity: 0;
        transform: translateX(100%);
      }
    }
  `;
  document.head.appendChild(style);
}

// 页面加载时添加动画
if (typeof document !== 'undefined') {
  addAnimations();
}

// 调试钩子
if (typeof window !== 'undefined') {
  window.__toast = toast;
}
