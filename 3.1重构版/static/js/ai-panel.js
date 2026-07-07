// ai-panel.js · v1.3 · 2026-07-04
// AI 解读面板 —— 两阶段渲染：快速解读（规则）→ 深度分析（AI 流式）
//
// 数据流：
//   1. 用户选择股票 → app.js 调 fetchQuickAnalysis → showQuickAnalysis (快速 tab)
//   2. 用户点"分析" → app.js 调 triggerAnalysis → POST /api/analyze_stream
//   3. 后端 analyze_stock 完成 → 发 scores_update + partial_result（规则快速解读）
//   4. 本模块 partial_result handler → 渲染快速解读到 #ai-quick-content
//   5. 后端 AI 流开始 → ai_stream → 自动切到深度 tab，流式渲染到 #ai-deep-content
//   6. 后端 final_result / analysis_complete → finalize()
//
// 依赖：
//   - marked (CDN) · Markdown 解析
//   - DOMPurify (CDN) · XSS 防护
//   失败时降级纯文本
//
// 状态：
//   empty   · 等待首次分析
//   loading · 分析进行中（快速解读已出或等待中）
//   normal  · 完成（快速/深度 tab 可切换）
//   error   · 后端报错
//   stale   · 超过 5 分钟无新 chunk

import { store } from './store.js';
import { logger } from './logger.js';
import { sse } from './sse.js';

const MARKED_CDN     = 'https://cdn.jsdelivr.net/npm/marked@12.0.0/marked.min.js';
const DOMPURIFY_CDN  = 'https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js';

const STALE_TIMEOUT_MS = 5 * 60 * 1000;
const MAX_STREAM_SIZE = 100 * 1024;
const RENDER_DEBOUNCE_MS = 100;
const TRUNCATION_SUFFIX = '\n\n[… 内容过长已截断 …]';

class AIPanel {
  constructor() {
    this.stream = '';         // 深度分析累积文本
    this.quickStream = '';    // 快速解读累积文本（规则生成）
    this._truncated = false;
    this._activeMode = 'quick';  // 'quick' | 'deep'
    this._firstChunkArrived = false;
    this._hasQuickData = false;
    this._hasDeepData = false;
    this.marked = null;
    this.DOMPurify = null;
    this._depsPromise = null;
    this._lastChunkTs = 0;
    this._staleTimer = null;
    this._renderTimer = null;
  }

  // ── 依赖加载 ──
  async _loadDeps() {
    if (this.marked && this.DOMPurify) return true;
    if (this._depsPromise) return this._depsPromise;
    this._depsPromise = (async () => {
      let ok = true;
      if (typeof window.marked === 'undefined') {
        ok = ok && (await this._loadScript(MARKED_CDN));
      }
      if (typeof window.DOMPurify === 'undefined') {
        ok = ok && (await this._loadScript(DOMPURIFY_CDN));
      }
      this.marked     = window.marked     || null;
      this.DOMPurify  = window.DOMPurify  || null;
      if (!this.marked)    logger.warn('marked 未加载，AI 面板降级为纯文本');
      if (!this.DOMPurify) logger.warn('DOMPurify 未加载');
      return ok;
    })();
    return this._depsPromise;
  }

  _loadScript(src) {
    return new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = src;
      s.async = true;
      s.onload  = () => resolve(true);
      s.onerror = () => { logger.warn(`script load failed: ${src}`); resolve(false); };
      document.head.appendChild(s);
    });
  }

  // ── 公开 API ──

  /** 开始一次新分析（清空深度流，保留快速解读区） */
  async startAnalysis() {
    _finalized = false;
    this.stream = '';
    this._firstChunkArrived = false;
    this._hasDeepData = false;
    this._lastChunkTs = Date.now();
    this._startStaleTimer();
    this._setState('loading');
    this._renderProgress('获取数据中...');
    this._updateLoadingStatus('正在分析...', '获取市场数据中');
    await this._loadDeps();
    // 不渲染 stream（它是空的）— quick content 由 partial_result 渲染
  }

  _updateLoadingStatus(title, detail) {
    const titleEl = document.getElementById('ai-status-title');
    const detailEl = document.getElementById('ai-status-detail');
    if (titleEl) titleEl.textContent = title || '正在分析...';
    if (detailEl) detailEl.textContent = detail || '获取市场数据中';
  }

  /** 更新进度状态 */
  updateProgress(message, progress = null) {
    this._renderProgress(message);
    if (message.includes('获取') || message.includes('数据')) {
      this._updateLoadingStatus('数据获取中...', message);
    } else if (message.includes('AI') || message.includes('生成')) {
      this._updateLoadingStatus('AI 分析中...', message);
    } else if (message.includes('完成')) {
      this._updateLoadingStatus('分析完成', message);
    } else {
      this._updateLoadingStatus('分析进行中...', message);
    }
    logger.info(`分析进度: ${message}`);
  }

  /** 追加 AI 流 chunk（由 SSE ai_stream 回调调用） */
  appendChunk(chunk) {
    if (!chunk || this._truncated) return;
    // 首个 chunk 到达时取消 stale 超时（已有实际内容，不会永远卡 loading）
    if (!this._firstChunkArrived) {
      this._stopStaleTimer();
    }

    // 首个 chunk → 自动切换到深度 tab
    if (!this._firstChunkArrived) {
      this._firstChunkArrived = true;
      this._hasDeepData = true;
      this._setActiveMode('deep');
      this._updateLoadingStatus('AI 分析中...', '正在生成深度分析报告');
    }

    if (this.stream.length + chunk.length > MAX_STREAM_SIZE) {
      this.stream = this.stream.slice(0, MAX_STREAM_SIZE - TRUNCATION_SUFFIX.length) + TRUNCATION_SUFFIX;
      this._truncated = true;
      this.finalize();
      return;
    }

    this.stream += chunk;
    this._lastChunkTs = Date.now();
    this._renderProgress(`分析生成中... (${this.stream.length} 字)`);
    this._scheduleRender();
  }

  /** 分析完成（final_result / analysis_complete） */
  finalize() {
    this._stopStaleTimer();
    this._setState('normal');
    this._renderProgress('完成');
    this._flushRender();
    setTimeout(() => this._renderProgress(null), 1000);
  }

  /** 从 REST /api/analyze/quick 渲染快速解读（选股时自动触发） */
  showQuickAnalysis(data) {
    if (!data) return;
    const name = data.name || (data.quote || {}).name || '';
    const code = data.code || (data.quote || {}).code || '';
    const price = data.price ?? (data.quote || {}).current_price ?? '—';
    const changePct = data.change_pct ?? (data.quote || {}).change_pct ?? 0;
    const scores = data.scores || {};
    const recommendation = data.recommendation || '观望';
    const reason = data.reason || '';
    const tech = data.technical || {};

    this.quickStream = [
      `### ${name}(${code}) 快速解读`,
      '',
      `当前价 **${price}** ${changePct >= 0 ? '+' : ''}${changePct?.toFixed?.(2) ?? changePct}%`,
      '',
      `- 当前操作：**${recommendation}**`,
      `- 推荐理由：${reason || '—'}`,
      `- 均线排列：${tech.ma_trend || '—'}`,
      `- RSI(14)：${tech.rsi ?? '—'}`,
      `- MACD：${tech.macd_signal || '—'}`,
      `- 量能：${tech.volume_status || '—'}`,
      '',
      `- 四维评分：技术 ${scores.technical_score ?? scores.technical ?? '—'} / 基本面 ${scores.fundamental_score ?? scores.fundamental ?? '—'} / 情绪 ${scores.sentiment_score ?? scores.sentiment ?? '—'} / 综合 ${scores.comprehensive_score ?? scores.composite ?? '—'}`,
      '',
      '> 这是基于真实行情、行业、资金和市场情绪的快速解读；点击"分析"可继续生成更完整的流式深度报告。',
    ].join('\n');

    this._hasQuickData = true;
    this._stopStaleTimer();
    this._setState('normal');
    this._renderProgress(null);
    this._showTabs();
    this._renderPanel('quick');
  }

  /** 从 SSE partial_result 渲染快速解读（点击分析后自动触发） */
  renderQuickFromSSE(data) {
    if (!data) return;
    const decision = data.decision || {};
    const advice = data.current_advice || {};
    const targetStop = data.target_and_stop || {};
    const cycles = data.cycles || {};
    const scores = data.scores || {};
    const rec = data.recommendation || {};
    const recAction = (rec.action || rec || '观望');
    const recReason = (rec.reason || data.reason || '');
    const priceInfo = data.price_info || {};

    const cycleLabels = { ultra_short: '超短期', short: '短期', mid: '中期', long: '长期' };
    let md = `### 快速解读（规则生成）\n\n`;
    md += `**操作评级**: ${recAction}\n\n`;
    if (recReason) md += `**核心理由**: ${recReason}\n\n`;
    if (data.market_state) md += `**市场状态**: ${data.market_state}\n\n`;

    md += `**四维评分**:`;
    md += ` 技术 ${scores.technical_score ?? '—'}`;
    md += ` / 基本面 ${scores.fundamental_score ?? '—'}`;
    md += ` / 情绪 ${scores.sentiment_score ?? '—'}`;
    md += ` / 综合 ${scores.comprehensive_score ?? '—'}\n\n`;

    md += `| 周期 | 信号 |\n|---|---|\n`;
    for (const [key, label] of Object.entries(cycleLabels)) {
      const c = cycles[key] || {};
      md += `| ${label} | ${c.signal || '—'} (${c.score ?? ''}) |\n`;
    }

    if (advice.short_term) md += `\n**操作建议**: ${advice.short_term}\n`;
    if (targetStop.support) md += `\n- **支撑位**: ${targetStop.support}`;
    if (targetStop.target) md += `\n- **目标位**: ${targetStop.target}`;
    if (targetStop.stop_loss) md += `\n- **止损位**: ${targetStop.stop_loss}`;
    if (data.batch_operation) {
      md += `\n\n**分批计划**:\n${data.batch_operation}`;
    }

    this.quickStream = md;
    this._hasQuickData = true;
    this._showTabs();
    this._renderPanel('quick');

    // loading 态下更新状态文字
    if (this._currentState === 'loading') {
      this._updateLoadingStatus('数据就绪', '快速解读已生成，深度分析生成中…');
    }
  }

  /** 错误 */
  showError(message, code) {
    this._stopStaleTimer();
    this._setState('error');
    // 更新通用错误块的错误码（替换静态占位符）
    const codeEl = document.querySelector('[data-card="ai"] [data-state="error"] .code');
    if (codeEl) codeEl.textContent = this._esc(code || 'E_AI_UNKNOWN');
    // 如果已有快速解读，在 deep panel 底部追加错误消息
    if (this._hasQuickData && this._activeMode === 'deep') {
      const container = document.getElementById('ai-deep-content');
      if (container) {
        container.innerHTML = `<div class="error-block" role="alert" style="margin-top: 8px;">
          <div class="head">深度分析失败</div>
          <div class="code">${this._esc(code || 'E_AI_UNKNOWN')}</div>
        </div>`;
      }
    }
  }

  /** 重置（用户清空 / 切股票） */
  reset() {
    _finalized = false;
    this._stopStaleTimer();
    this._flushRender();
    this.stream = '';
    this.quickStream = '';
    this._truncated = false;
    this._firstChunkArrived = false;
    this._hasQuickData = false;
    this._hasDeepData = false;
    this._activeMode = 'quick';
    this._hideTabs();
    this._setState('empty');
    // 清空所有内容容器
    document.querySelectorAll('[data-ai-panel]').forEach(el => {
      el.innerHTML = '';
    });
  }

  // ── Tab 切换 ──

  _setActiveMode(mode) {
    this._activeMode = mode;
    const tabs = document.getElementById('ai-mode-tabs');
    if (tabs) {
      tabs.querySelectorAll('[data-ai-mode]').forEach(btn => {
        const isActive = btn.dataset.aiMode === mode;
        btn.classList.toggle('on', isActive);
        btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
    }
    document.querySelectorAll('[data-ai-panel]').forEach(el => {
      el.hidden = el.dataset.aiPanel !== mode;
    });
    const titleEl = document.getElementById('ai-card-title');
    if (titleEl) {
      titleEl.textContent = mode === 'quick' ? '快速解读' : 'AI 深度解读';
    }
  }

  _showTabs() {
    const tabs = document.getElementById('ai-mode-tabs');
    if (tabs) tabs.style.display = '';
  }

  _hideTabs() {
    const tabs = document.getElementById('ai-mode-tabs');
    if (tabs) tabs.style.display = 'none';
  }

  // ── 渲染 ──

  _renderPanel(panel) {
    const panelId = panel === 'quick' ? 'ai-quick-content' : 'ai-deep-content';
    const text = panel === 'quick' ? this.quickStream : this.stream;
    const containers = document.querySelectorAll(`#${panelId}`);

    containers.forEach(container => {
      if (!text) {
        if (panel === 'quick') {
          container.innerHTML = '';
        } else {
          container.innerHTML = this._currentState === 'loading'
            ? '<div class="empty-block" style="padding: 8px 0;">深度分析生成中…</div>'
            : '';
        }
        return;
      }
      this._renderMarkdown(container, text);
      // loading 态下追加光标（仅 deep 面板）
      if (panel === 'deep' && this._currentState === 'loading') {
        const cursor = document.createElement('span');
        cursor.className = 'cursor';
        cursor.textContent = '\u258C';
        container.appendChild(cursor);
        container.scrollTop = container.scrollHeight;
      }
    });
  }

  _renderMarkdown(container, text) {
    if (!container) return;
    if (this.marked && this.DOMPurify) {
      try {
        const dirty = this.marked.parse(text, { gfm: true, breaks: true });
        const clean = this.DOMPurify.sanitize(dirty, {
          ALLOWED_TAGS: ['h1','h2','h3','h4','p','br','ul','ol','li','strong','em','code','pre','blockquote','a','table','thead','tbody','tr','th','td'],
          ALLOWED_ATTR: ['href', 'title'],
          ALLOW_DATA_ATTR: false,
        });
        container.innerHTML = clean;
      } catch (e) {
        container.textContent = text;
      }
    } else {
      container.textContent = text;
    }
  }

  _scheduleRender() {
    if (this._renderTimer) return;
    this._renderTimer = setTimeout(() => {
      this._renderTimer = null;
      this._renderContent();
    }, RENDER_DEBOUNCE_MS);
  }

  _flushRender() {
    if (this._renderTimer) {
      clearTimeout(this._renderTimer);
      this._renderTimer = null;
    }
    this._renderContent();
  }

  /** 渲染深度面板（由 _scheduleRender 节流调用） */
  _renderContent() {
    this._renderPanel('deep');
  }

  _renderProgress(label) {
    const bar = document.getElementById('ai-progress');
    const text = document.getElementById('ai-progress-text');
    if (!bar || !text) return;
    if (label == null) {
      bar.style.width = '0%';
      text.textContent = '';
      bar.hidden = true;
    } else {
      bar.hidden = false;
      let pct = 50;
      if (label === '完成') pct = 100;
      bar.style.width = pct + '%';
      text.textContent = label;
    }
  }

  _setState(state) {
    this._currentState = state;
    const card = document.querySelector('[data-card="ai"]');
    const slot = card?.querySelector('[data-slot="body"]');
    if (!slot) return;
    slot.setAttribute('data-active-state', state);
    slot.querySelectorAll('[data-state]').forEach(el => {
      el.hidden = el.dataset.state !== state;
    });
  }

  _esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  // ── Stale 检测 ──
  _startStaleTimer() {
    this._stopStaleTimer();
    this._staleTimer = setInterval(() => {
      if (this._currentState === 'loading' &&
          Date.now() - this._lastChunkTs > STALE_TIMEOUT_MS) {
        logger.warn(`AI 流式超时（${STALE_TIMEOUT_MS / 1000}s 无新 chunk）`);
        this.showError('AI 响应超时，可能网络或服务异常', 'E_AI_TIMEOUT');
      }
    }, 30 * 1000);
  }

  _stopStaleTimer() {
    if (this._staleTimer) {
      clearInterval(this._staleTimer);
      this._staleTimer = null;
    }
  }
}

// 单例
export const ai = new AIPanel();

// ── 接 SSE 事件 ──
let _finalized = false;

sse.on('ai_stream', (data) => {
  if (_finalized) return;
  if (data && typeof data.chunk === 'string') {
    ai.appendChunk(data.chunk);
  } else if (data && data.content) {
    ai.appendChunk(data.content);
  }
});

sse.on('partial_result', (data) => {
  if (!data) return;
  ai.renderQuickFromSSE(data);
});

sse.on('final_result', (data) => {
  _finalized = true;
  const finalText = data?.ai_analysis || data?.data?.ai_analysis || '';
  if (finalText && finalText.length > ai.stream.length) {
    ai.stream = finalText;
    ai._hasDeepData = true;
  }
  ai.finalize();
});

sse.on('analysis_complete', () => {
  if (_finalized) return;
  ai.finalize();
});

sse.on('log', (data) => {
  if (!data) return;
  if (data.type === 'progress' && ai._currentState === 'loading') {
    ai.updateProgress(data.message);
  } else if (data.type === 'error') {
    logger.error(`AI分析错误: ${data.message}`);
    if (ai._currentState === 'loading') {
      ai.showError(data.message, 'E_AI_FAILED');
    }
  }
});

sse.on('error', (data) => {
  if (!data) return;
  const code = data.code || '';
  if (code.startsWith('E_AI') || data.message?.toLowerCase().includes('ai')) {
    ai.showError(data.message, code);
  }
});

// ── 初始化 ──
export function initAIPanel() {
  logger.info('ai panel init');
  ai.reset();
  // 绑定 tab 切换事件
  const tabs = document.getElementById('ai-mode-tabs');
  if (tabs) {
    tabs.querySelectorAll('[data-ai-mode]').forEach(btn => {
      btn.addEventListener('click', () => {
        const mode = btn.dataset.aiMode;
        if (!mode || mode === ai._activeMode) return;
        ai._setActiveMode(mode);
      });
    });
  }
}

if (typeof window !== 'undefined') {
  window.__ai = ai;
}
