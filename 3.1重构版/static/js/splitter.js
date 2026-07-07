// splitter.js · v1.1 · 2026-06-14
// 拖拽分割条 —— 2 / 3 栏布局的列宽拖动 + localStorage 持久化
//
// 用法：
//   <div class="splitter" id="main-split">
//     <div class="pane" data-pane="left">左栏</div>
//     <div class="handle" data-handle></div>
//     <div class="pane" data-pane="right">右栏</div>
//   </div>
//   import { initSplitter } from './splitter.js';
//   initSplitter('#main-split', { storageKey: 'split-width-v1' });
//
// 行为：
//   - 拖动 handle → 调整左右两 pane 的 fr 比例
//   - 双击 handle → 恢复默认 1:1
//   - 宽度持久化到 localStorage（key 由 storageKey 决定）
//   - 移动端（<=1024px）禁用拖拽（v1.1 推到 v1.2）

const DEFAULTS = {
  ratio: 0.55,         // 左 pane 占总宽度的比例
  min: 0.25,           // 拖动下限
  max: 0.75,           // 拖动上限
};

export function initSplitter(rootSelector, options = {}) {
  const root = typeof rootSelector === 'string' ? document.querySelector(rootSelector) : rootSelector;
  if (!root) return;
  const opts = { ...DEFAULTS, ...options };
  const storageKey = options.storageKey || 'splitter-ratio';
  const handles = root.querySelectorAll('[data-handle]');
  if (handles.length === 0) return;

  // 读 localStorage
  let ratio = parseFloat(localStorage.getItem(storageKey) || '');
  if (!Number.isFinite(ratio) || ratio < opts.min || ratio > opts.max) {
    ratio = opts.ratio;
  }
  applyRatio(root, ratio);

  // 绑定每个 handle
  handles.forEach(handle => bindHandle(handle, root, opts, storageKey, applyRatio));
}

function applyRatio(root, ratio) {
  // 找所有 .pane 元素，根据 [data-pane] 顺序设置 fr
  const panes = root.querySelectorAll('.pane');
  if (panes.length < 2) return;
  const left = panes[0];
  const right = panes[panes.length - 1];
  left.style.flex  = `${ratio} 1 0`;
  right.style.flex = `${(1 - ratio)} 1 0`;
  // 触发一个 resize 事件（让 Plotly 等图表重新计算尺寸）
  window.dispatchEvent(new Event('splitter:resize'));
}

function bindHandle(handle, root, opts, storageKey, applyRatio) {
  let dragging = false;
  let startX = 0;
  let startRatio = 0;
  let rafId = null;

  handle.addEventListener('mousedown', (e) => {
    // 移动端禁用（CSS @media 也不显示，但 JS 兜底）
    if (window.innerWidth <= 1024) return;
    dragging = true;
    startX = e.clientX;
    const panes = root.querySelectorAll('.pane');
    if (panes.length < 2) return;
    const leftRect  = panes[0].getBoundingClientRect();
    const rightRect = panes[panes.length - 1].getBoundingClientRect();
    const total = leftRect.width + rightRect.width + handle.offsetWidth;
    startRatio = leftRect.width / total;
    document.body.classList.add('splitter-dragging');
    handle.setAttribute('data-resizing', '');
    e.preventDefault();
  });

  document.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      const total = root.getBoundingClientRect().width;
      const dx = e.clientX - startX;
      const newRatio = Math.max(opts.min, Math.min(opts.max, startRatio + dx / total));
      applyRatio(root, newRatio);
    });
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('splitter-dragging');
    handle.removeAttribute('data-resizing');
    // 持久化
    const panes = root.querySelectorAll('.pane');
    if (panes.length >= 2) {
      const leftRect = panes[0].getBoundingClientRect();
      const rightRect = panes[panes.length - 1].getBoundingClientRect();
      const total = leftRect.width + rightRect.width;
      const ratio = leftRect.width / total;
      try { localStorage.setItem(storageKey, ratio.toFixed(4)); } catch {}
    }
  });

  // 双击 → 恢复默认
  handle.addEventListener('dblclick', () => {
    applyRatio(root, opts.ratio);
    try { localStorage.removeItem(storageKey); } catch {}
  });
}

if (typeof window !== 'undefined') window.__splitter = { initSplitter };
