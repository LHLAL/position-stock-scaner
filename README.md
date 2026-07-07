# 🚀 AI增强股票分析系统 (Enhanced AI Stock Analysis System)

## 📋 项目简介

AI 增强的股票分析系统，支持 **A股 / 港股 / 美股**，集成多维度财务指标、技术指标、新闻情绪分析与 AI 深度解读。系统支持多种 AI 模型（OpenAI GPT、Claude、SiliconFlow 等），提供 Web 界面和桌面 GUI，具备 SSE 实时流式推送功能。

> ⚠️ **版本说明**：当前生产版本为 `3.0 webapp（支持港股美股）/`。其他目录为历史存档。

## 💰 请我喝奶茶

如果这个项目对您有帮助，欢迎支持：
🔗 [https://juanzen.linzefeng.top/](https://juanzen.linzefeng.top/)

## ✨ 核心特性

### 🎯 多维度分析
- **25项核心财务指标**：盈利能力、偿债能力、营运能力、发展能力、市场表现
- **技术面分析**：移动平均线、RSI、MACD、布林带、成交量分析
- **市场情绪分析**：新闻、公告、研报情绪挖掘，支持100+条新闻分析
- **AI智能解读**：多模型深度分析，提供专业投资建议

### 🤖 AI能力支持
- **多模型兼容**：OpenAI GPT、Claude、智谱AI、SiliconFlow（OpenAI 兼容）
- **智能切换**：主备API自动切换，确保服务可用性
- **流式推理**：实时AI分析过程展示，支持Server-Sent Events
- **规则降级**：AI不可用时自动降级到高级规则分析

### 🌐 多端支持
- **Web版本**：Flask + SSE，支持多用户并发，实时流式推送
- **桌面版GUI**：PyQt6 启动器，可视化配置管理，一键打包 EXE
- **批量分析**：支持多股票并发分析，线程池优化
- **Docker部署**：容器化部署，支持一键启动（含 Nginx 反向代理）

### 🔐 企业级特性
- **密码鉴权**：Web版支持密码保护和会话管理
- **高并发**：线程池 + 异步处理 + 任务队列优化
- **缓存机制**：智能数据缓存，减少API调用
- **错误处理**：完善的异常处理和重试机制

## 🏗️ 版本目录

| 目录 | 状态 | 说明 |
|---|---|---|
| `3.0 webapp（支持港股美股）/` | **PRODUCTION** | 当前稳定版本，支持港美股 |
| `3.1 webapp/` | **WIP** | 开发中，还未完善请勿使用 |
| `2.6 webapp（流式传输测试版）/` | 存档 | 历史版本 |
| `2.5 webapp/` | 存档 | 历史版本 |
| `2.0 win app/` | 存档 | 历史桌面版 |
| `1.0/` | 存档 | 历史版本 |

## 🚀 快速开始（3.0 生产版）

### 1. 进入目录

```bash
cd "3.0 webapp（支持港股美股）/"
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 准备配置文件

```bash
cp "config - 示例.json" config.json
```

编辑 `config.json`，至少填写：
- `api_keys`：你的 API Key
- `ai.model_preference`：主模型（如 `openai` / `siliconflow`）
- `ai.models`：模型名称

详细说明见 `config-readme.md`。

### 4. 启动服务

**Web 版：**
```bash
python flask_web_server.py
# 访问 http://localhost:5000
```

**桌面 GUI（推荐）：**
```bash
python desktop_gui_launcher.py
```
提供启动/停止服务、实时日志、配置中心、一键打开分析页面。

**Docker 部署：**
```bash
docker compose up -d --build
```

**Windows EXE 打包：**
```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

## 📊 股票代码格式

## 📁 子项目与分支
- `3.1 重构版/` – 采用模块化重构版本，功能仍在开发中。请参见 `3.1重构版/README.md`。
- `stock_ai_analyst_v4/` – 后端分析器，支持多源数据和策略生成。
- `tests/` – 单元与集成测试。
- 其余文件夹为历史版本、文档或工具。

### **Python 虚拟环境**

> 本项目在根目录下预置了一个名为 `env/` 的 Python 虚拟环境，用于隔离依赖。请在安装任何包前先激活该环境：
>
> ```bash
> source env/bin/activate   # macOS / Linux
> ```
>
> 或者
>
> ```bash
> .\env\Scripts\activate   # Windows
> ```
>
> **激活后**，所有 `pip install` 操作都会在此环境中执行，确保在不同机器或 CI 上的一致性。

系统自动识别市场：
- A股：`600519` / `sh600519` / `600519.SH`
- 港股：`00700` / `700` / `00700.HK` / `HK00700`
- 美股：`AAPL` / `MSFT` / `105.MSFT`（AkShare 特殊格式）
