// 模拟浏览器,跑 app.js 看哪个模块炸
// 用 Node 自带的 import-meta 注入 window/document 占位

import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');

// 1. 收集所有 ES module 路径
const modules = [
  'static/js/logger.js',
  'static/js/store.js',
  'static/js/sse.js',
  'static/js/exporter.js',
  'static/js/theme.js',
  'static/js/cmdk.js',
  'static/js/sidebar.js',
  'static/js/ai-panel.js',
  'static/js/chart.js',
  'static/js/signals.js',
  'static/js/table.js',
  'static/js/splitter.js',
  'static/js/perf.js',
  'static/js/patrol-page.js',
  'static/js/scan.js',
  'static/js/signals-page.js',
  'static/js/app.js',
];

// 2. 用 vm.Module 跑每个 module 来 catch 顶层副作用
const errors = [];
for (const rel of modules) {
  const fp = resolve(root, rel);
  try {
    const src = readFileSync(fp, 'utf8');
    // 简单检查:尝试编译为 Script,看有没有裸 import 解析错误
    new vm.Script(src, { filename: fp });
    process.stdout.write(`  ✓ ${rel}\n`);
  } catch (e) {
    errors.push({ file: rel, error: e.message });
    process.stdout.write(`  ✗ ${rel}\n    ${e.message}\n`);
  }
}

if (errors.length) {
  console.log(`\n${errors.length} module(s) with parse/load issues`);
  process.exit(1);
} else {
  console.log(`\nAll ${modules.length} modules parse OK`);
}
