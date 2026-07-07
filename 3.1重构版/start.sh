#!/usr/bin/env bash
# 启动 3.1 重构版 Stock Scanner
#
# 用法:
#   ./start.sh                # 默认前台运行（推荐开发调试）
#   ./start.sh --bg           # 后台运行，日志写入 server.log
#   ./start.sh --port 5050    # 自定义端口
#   ./start.sh --bg --port 5050
#
# 依赖:
#   - Python 3.10+ (由 uv 自动管理)
#   - uv 包管理器 (https://docs.astral.sh/uv/)
#
# 首次运行会自动:
#   1. 同步依赖 (uv sync)
#   2. 初始化 SQLite 数据库 (patrol.db)
#   3. 启动 Flask 服务（默认 0.0.0.0:5000）

set -e

# 切到脚本所在目录，保证相对路径稳定
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 参数解析 ------------------------------------------------------------
HOST="0.0.0.0"
PORT="5000"
BACKGROUND="false"
LOG_FILE="$SCRIPT_DIR/server.log"
PID_FILE="$SCRIPT_DIR/.server.pid"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bg|-d|--daemon)
            BACKGROUND="true"
            shift
            ;;
        --port|-p)
            PORT="$2"
            shift 2
            ;;
        --host|-H)
            HOST="$2"
            shift 2
            ;;
        --stop)
            if [[ -f "$PID_FILE" ]]; then
                PID=$(cat "$PID_FILE" 2>/dev/null || true)
                if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
                    echo "[stop] 结束 PID=$PID"
                    kill "$PID"
                    sleep 1
                fi
                rm -f "$PID_FILE"
            else
                echo "[stop] 未找到 $PID_FILE，没有后台进程需要结束"
            fi
            exit 0
            ;;
        --help|-h)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "未知参数: $1" >&2
            echo "使用 --help 查看用法" >&2
            exit 1
            ;;
    esac
done

# --- 依赖自检 ------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "[错误] 未检测到 uv，请先安装：curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

# 第一次运行时同步依赖
if [[ ! -d ".venv" ]] || [[ ! -f "uv.lock" ]]; then
    echo "[setup] 首次运行，正在同步依赖 ..."
    uv sync
fi

# 停掉已占用端口的旧实例（避免端口冲突）
if command -v lsof >/dev/null 2>&1; then
    EXISTING_PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
    if [[ -n "$EXISTING_PIDS" ]]; then
        echo "[warn] 端口 $PORT 已被 PID($EXISTING_PIDS) 占用，正在结束旧进程 ..."
        kill $EXISTING_PIDS 2>/dev/null || true
        sleep 1
    fi
fi

# --- 启动 ---------------------------------------------------------------
# 端口/主机通过环境变量注入到 run.py
export STOCK_SCANNER_HOST="$HOST"
export STOCK_SCANNER_PORT="$PORT"

if [[ "$BACKGROUND" == "true" ]]; then
    echo "[startup] 后台启动 3.1 重构版 -> http://$HOST:$PORT  (日志: $LOG_FILE)"
    nohup uv run python src/run.py >"$LOG_FILE" 2>&1 &
    echo $! >"$PID_FILE"
    sleep 2
    if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
        echo "[ok] 进程已启动，PID=$(cat "$PID_FILE")"
        echo "     停止: kill \$(cat $PID_FILE)  或  ./start.sh --stop"
    else
        echo "[error] 启动失败，查看日志: $LOG_FILE" >&2
        tail -20 "$LOG_FILE" >&2 || true
        exit 1
    fi
else
    echo "[startup] 前台启动 3.1 重构版 -> http://$HOST:$PORT"
    exec uv run python src/run.py
fi
