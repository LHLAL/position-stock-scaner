// perf.js · v1.2 · 2026-06-14
// 性能预算测量 —— 实际跑一次写基线
//
// 测量项（对应 design §7.5）：
//   - FCP (First Contentful Paint)
//   - LCP (Largest Contentful Paint)        目标 < 1.5s
//   - TTI (Time to Interactive, 简化版)      目标 < 2.0s
//   - Long Tasks (>50ms) 累计 / 数量
//   - JS heap size                          目标 < 250MB
//
// 数据流：
//   1. 页面加载时启动测量
//   2. 通过 PerformanceObserver 监听各指标
//   3. 写入 store.perf（订阅可观察）
//   4. 控制台打印 summary
//
// 调用：在 index-v2.html 末尾加载（不阻塞）

import { store } from './store.js';
import { logger } from './logger.js';

const TARGETS = {
  LCP: 1500,     // ms
  FCP: 1000,     // ms
  TTI: 2000,     // ms
  LONG_TASK_BUDGET: 200,  // ms（累计 > 200ms 视为不健康）
  HEAP: 250 * 1024 * 1024,  // 250MB
};

const metrics = {
  fcp: null,
  lcp: null,
  tti: null,
  longTasks: [],   // {start, duration, name}
  heapUsed: null,
  jsResources: [],
};

const _t0 = performance.now();

function _now() { return Math.round(performance.now() - _t0); }

function _publish() {
  store.set('perf', { ...metrics, capturedAt: Date.now() });
}

// ── FCP / LCP ──
function observePaint() {
  if (typeof PerformanceObserver === 'undefined') return;
  try {
    const po = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.name === 'first-contentful-paint') {
          metrics.fcp = Math.round(entry.startTime);
        }
      }
      _publish();
    });
    po.observe({ type: 'paint', buffered: true });

    const lcpPo = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length) {
        metrics.lcp = Math.round(entries[entries.length - 1].startTime);
      }
      _publish();
    });
    lcpPo.observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (e) {
    logger.warn(`paint observer failed: ${e.message}`);
  }
}

// ── Long Tasks ──
function observeLongTasks() {
  if (typeof PerformanceObserver === 'undefined') return;
  try {
    const po = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.duration < 50) continue;  // 50ms 阈值
        metrics.longTasks.push({
          start: Math.round(entry.startTime),
          duration: Math.round(entry.duration),
          name: entry.name || 'unknown',
        });
      }
      _publish();
    });
    po.observe({ type: 'longtask', buffered: true });
  } catch (e) {
    logger.warn(`longtask observer failed: ${e.message}`);
  }
}

// ── TTI（简化版：最后一个长任务结束 + 5s 静默窗口）──
function estimateTTI() {
  if (typeof PerformanceObserver === 'undefined') return;
  let lastLongTask = 0;
  try {
    const po = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.startTime + entry.duration > lastLongTask) {
          lastLongTask = entry.startTime + entry.duration;
        }
      }
      // 5s 静默窗口后计算 TTI
      setTimeout(() => {
        metrics.tti = Math.round(lastLongTask + 5000);
        _publish();
        _summary();
      }, 5000);
    });
    po.observe({ type: 'longtask', buffered: true });
    // 同时兜底 30s 一定输出
    setTimeout(() => {
      if (metrics.tti == null) {
        metrics.tti = Math.round(_now());
        _publish();
        _summary();
      }
    }, 30000);
  } catch (e) {
    metrics.tti = Math.round(_now());
    _summary();
  }
}

// ── 内存（每 30s 采样）──
function sampleMemory() {
  if (!('memory' in performance)) return;
  const sample = () => {
    metrics.heapUsed = performance.memory.usedJSHeapSize;
    _publish();
  };
  sample();
  setInterval(sample, 30 * 1000);
}

// ── JS 资源大小 ──
function collectResources() {
  if (!performance.getEntriesByType) return;
  const entries = performance.getEntriesByType('resource')
    .filter(e => e.name.endsWith('.js') || e.name.endsWith('.css'));
  metrics.jsResources = entries.map(e => ({
    name: e.name.split('/').pop(),
    size: e.transferSize || e.encodedBodySize || 0,
    duration: Math.round(e.duration),
  })).sort((a, b) => b.size - a.size);
  _publish();
}

// ── 总结输出 ──
function _summary() {
  const longTaskTotal = metrics.longTasks.reduce((s, t) => s + t.duration, 0);
  const heapMB = metrics.heapUsed ? (metrics.heapUsed / 1024 / 1024).toFixed(1) : '?';

  const lines = [
    '────────── perf summary ──────────',
    `FCP  ${metrics.fcp ?? '?'}ms  ${_check(metrics.fcp, TARGETS.FCP)}`,
    `LCP  ${metrics.lcp ?? '?'}ms  ${_check(metrics.lcp, TARGETS.LCP)}`,
    `TTI  ${metrics.tti ?? '?'}ms  ${_check(metrics.tti, TARGETS.TTI)}`,
    `LongTasks  ${metrics.longTasks.length} 个, 累计 ${longTaskTotal}ms  ${_check(TARGETS.LONG_TASK_BUDGET, longTaskTotal, true)}`,
    `Heap  ${heapMB}MB  ${_check(TARGETS.HEAP, metrics.heapUsed ?? 0, true)}`,
    'JS 资源（前 5 大）：',
    ...metrics.jsResources.slice(0, 5).map(r => `  ${r.name.padEnd(30)} ${(r.size/1024).toFixed(1)}KB  ${r.duration}ms`),
    '─────────────────────────────────',
  ];
  console.log(lines.join('\n'));

  // 写一份给 backend 抓（devtools 网络面板能看到）
  console.log('[perf] store.perf =', store.get('perf'));
}

function _check(target, actual, lowerIsBetter = false) {
  if (actual == null) return '?';
  if (lowerIsBetter) {
    return actual <= target ? '✓' : `✗ (目标 ${target})`;
  }
  return actual <= target ? '✓' : `✗ (目标 ${target}ms)`;
}

// ── 启动 ──
function init() {
  if (typeof window === 'undefined') return;
  logger.info('perf monitor init');

  observePaint();
  observeLongTasks();
  estimateTTI();
  sampleMemory();
  // 资源统计在 window load 之后
  if (document.readyState === 'complete') {
    collectResources();
  } else {
    window.addEventListener('load', collectResources);
  }
}

// DOMContentLoaded 启动（不阻塞）
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}

if (typeof window !== 'undefined') window.__perf = { metrics, TARGETS, summary: _summary };

export const perf = { init, summary: _summary };
