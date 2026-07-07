// exporter.js · v1.2 · 2026-06-14
// 通用 CSV 导出 —— 纯前端 Blob + a.download,不需要后端库
//
// 用法:
//   import { exportCSV } from './exporter.js';
//   exportCSV({ filename: 'positions-2026-06-14.csv', rows: [...], columns: [...] });
//
// columns 形如: [{ key: 'code', label: '代码' }, { key: 'name', label: '名称' }]
// rows 形如:   [{ code: '600519', name: '贵州茅台', price: 1234.56 }]

/**
 * 转义 CSV 单元格 —— RFC 4180
 * - 含逗号 / 引号 / 换行 → 整段加双引号
 * - 内部双引号 → 双写 ""
 */
function escapeCell(v) {
  if (v == null) return '';
  const s = String(v);
  if (/[",\n\r]/.test(s)) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

/**
 * 把 rows 序列化为 CSV 字符串
 * @param {Array<object>} rows
 * @param {Array<{key: string, label?: string}>} columns
 * @returns {string}
 */
export function toCSV(rows, columns) {
  if (!Array.isArray(rows) || !rows.length) return '';
  if (!Array.isArray(columns) || !columns.length) {
    // 没指定 columns → 用第一行 keys
    columns = Object.keys(rows[0]).map(k => ({ key: k, label: k }));
  }
  const header = columns.map(c => escapeCell(c.label || c.key)).join(',');
  const body = rows.map(r =>
    columns.map(c => escapeCell(c.format ? c.format(r[c.key], r) : r[c.key])).join(',')
  ).join('\n');
  // 前置 BOM → Excel 打开 UTF-8 不乱码
  return '﻿' + header + '\n' + body;
}

/**
 * 触发浏览器下载
 * @param {object} opts
 * @param {string} opts.filename  文件名,带 .csv 后缀
 * @param {Array<object>} opts.rows     数据行
 * @param {Array<{key, label?, format?}>} [opts.columns]  列定义
 * @param {string} [opts.charset='utf-8']
 * @returns {{filename: string, count: number, bytes: number}}
 */
export function exportCSV({ filename, rows, columns, charset = 'utf-8' }) {
  if (!filename) throw new Error('filename 必填');
  if (!Array.isArray(rows)) throw new Error('rows 必须是数组');

  const csv = toCSV(rows, columns || []);
  // 没数据也要下载(空表头),但只下空表头略奇怪 → 给个空提示
  if (!rows.length) {
    console.warn('[exporter] rows 为空,只导出表头');
  }

  const blob = new Blob([csv], { type: `text/csv;charset=${charset};` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  // 等一帧再清理(浏览器需要时间发起下载)
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 0);

  const out = { filename, count: rows.length, bytes: new Blob([csv]).size };
  console.info(`[exporter] 已导出 ${filename} (${out.count} 行, ${out.bytes} 字节)`);
  return out;
}

/**
 * 生成带日期的默认文件名: prefix-YYYY-MM-DD.csv
 */
export function datedFilename(prefix, ext = 'csv') {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${prefix}-${yyyy}-${mm}-${dd}.${ext}`;
}

// 全局暴露(供 inline onclick 或控制台调用)
if (typeof window !== 'undefined') {
  window.__exporter = { exportCSV, toCSV, datedFilename };
}
