# AGENTS.md — stock-scanner

## Project Overview

AI-enhanced stock analysis system (A-shares / HK / US) using Flask + AkShare + multi-LLM. Python 3.10+.

## Versioned Directory Layout

The repo is **not a monorepo** — numbered directories are separate version iterations:

| Dir | Status | Entry Points |
|---|---|---|
| `1.0/` | Archive (v1) | `gui.py`, `web_app.py` |
| `2.0 win app/` | Archive (v2 desktop) | `gui2.py`, `stock_analyzer.py` |
| `2.5 webapp/` | Archive (v2.5 web) | `flask_web_server.py` |
| `2.6 webapp（流式传输测试版）/` | Archive (v2.6 SSE) | `flask_web_server.py` |
| `3.0 webapp（支持港股美股）/` | **PRODUCTION** — current stable, demo runs this | `flask_web_server.py`, `web_stock_analyzer.py`, `desktop_gui_launcher.py` |
| `3.1 webapp/` | **WIP — do not use** (README says "还未完善请勿使用") | `enhanced_flask_server.py`, `enhanced_web_stock_analyzer.py` |
| `全部股票分析推荐1.py` | Root-level legacy script, standalone bulk analyzer | |

**Always work in `3.0 webapp（支持港股美股）/` unless explicitly told otherwise.**

## Developer Commands (run inside `3.0 webapp（支持港股美股）/`)

```bash
# Install deps (uses Tsinghua mirror in Docker, but pip default is fine locally)
pip install -r requirements.txt

# Web server (port 5000, 0.0.0.0)
python flask_web_server.py

# Desktop GUI launcher (manages web server + config editor)
python desktop_gui_launcher.py

# Docker
docker compose up -d --build
# With Nginx reverse proxy:
docker compose --profile with-nginx up -d --build

# Package as Windows EXE
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File ./build_exe.ps1
```

## Config

- Copy `"config - 示例.json"` → `config.json` (or the app auto-generates it on first start).
- `config-readme.md` has full field-by-field documentation.
- Minimum to start: fill one key in `api_keys` + matching `ai.model_preference`.
- Without any API key the app degrades to rule-based analysis (no LLM depth).

**Do NOT commit real API keys.** No `.gitignore` exists in the repo — create one for `config.json`, `*.log`, `__pycache__/`, `.env`.

## Architecture (v3.0)

- `flask_web_server.py` — Flask app, SSE endpoints, HTML template (inline, no separate frontend), auth middleware
- `web_stock_analyzer.py` — Core engine: market data via AkShare, technical/fundamental/sentiment scoring, LLM integration
- `desktop_gui_launcher.py` — PyQt6 launcher: start/stop web server, live log viewer, config center UI
- Thread pool: `max_workers=4`, Flask `threaded=True`

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/status` | Health check |
| GET | `/api/sse?client_id=xxx` | Open SSE channel |
| POST | `/api/analyze_stream` | Single stock streaming |
| POST | `/api/batch_analyze_stream` | Batch (max 10) streaming |
| POST | `/api/analyze` | Single stock sync (non-streaming) |
| POST | `/api/batch_analyze` | Batch sync (max 10) |
| GET | `/api/task_status/<code>` | Task status |
| GET | `/api/system_info` | System info |

SSE workflow: first connect `/api/sse?client_id=xxx`, then POST to analyze with the **same** `client_id`.

## Key Gotchas

- **SSE requires client_id match**: Connect first, then POST with identical `client_id` — otherwise "missing client ID" error.
- **429 on duplicate analysis**: Only one in-flight task per stock at a time.
- **NaN in JSON**: Analyzer strips NaN values before serialization (pandas common issue).
- **Chinese NLP prompts**: All analysis prompts are in Chinese. Be careful when editing them.
- **AkShare rate limits**: Endpoint cooldown is configurable via `cache.akshare_endpoint_cooldown_seconds` (default 90s).
- **Demo currently runs 2.6**, not 3.0 or 3.1 (README notes: "3.1出现大量bug，回退").

## Stock Code Formats

- A-shares: `600519`, `sh600519`, `600519.SH`
- HK: `00700`, `700`, `00700.HK`, `HK00700`
- US: `AAPL`, `MSFT`, `105.MSFT` (AkShare special format)

## No Tests / No Linting

This repo has no test suite, no linter config, no type checker. Run the server and test manually in a browser.


# OpenCode 项目规则 - Python 环境与依赖管理

此项目严格使用 **uv** 进行虚拟环境和包管理。

## 强制执行规则（必须严格遵守）

- **禁止使用**：pip、pip install、python -m pip、conda、poetry、pipenv 等传统工具。
- **安装/添加依赖**：必须使用 `uv add <package>`  
  示例：
  - `uv add requests pandas numpy`
  - `uv add --dev ruff pytest mypy`

- **同步环境**：始终使用 `uv sync` 来安装或更新依赖。

- **运行任何 Python 命令**：必须通过 `uv run` 执行，**禁止** 直接运行 `python`、`python3` 或 `python main.py`。
  正确示例：
  - `uv run python main.py`
  - `uv run pytest`
  - `uv run ruff check .`
  - `uv run streamlit run app.py`

- **虚拟环境位置**：项目使用 `.venv` 目录（uv 默认创建）。
- **无需手动激活**：不要执行 `source .venv/bin/activate` 或 Windows 下的 activate 脚本。直接使用 `uv run` 即可，uv 会自动处理环境。

- **重建环境**：如需重置，可删除 `.venv` 文件夹后执行 `uv sync`。

## 附加要求
- 项目必须包含 `pyproject.toml` 和 `uv.lock` 文件。
- 如果发现环境不一致，请先执行 `uv sync` 再进行后续操作。
- 所有代码执行和测试都必须在 uv 管理的环境中进行。