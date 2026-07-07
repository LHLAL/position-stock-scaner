"""SQLite连接管理"""
import sqlite3
from pathlib import Path

_db_path = None

def set_db_path(path: str) -> None:
    global _db_path
    _db_path = path

def get_connection() -> sqlite3.Connection:
    global _db_path

    if _db_path is None:
        base_dir = Path(__file__).parent.parent
        db_dir = base_dir / "data"
        db_dir.mkdir(exist_ok=True)
        _db_path = db_dir / "patrol.db"

    conn = sqlite3.connect(str(_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patrol_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT,
            shares REAL DEFAULT 0,
            cost_price REAL DEFAULT 0,
            market TEXT DEFAULT 'SH',
            project TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patrol_analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            ai_analysis TEXT,
            technical_score REAL,
            fundamental_score REAL,
            sentiment_score REAL,
            comprehensive_score REAL,
            recommendation TEXT,
            recommendation_reason TEXT,
            strategy TEXT,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (position_id) REFERENCES patrol_positions(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_position_single_analysis
        ON patrol_analysis_results(position_id)
    """)
    # v1.2 自选股表（替代 v1_routes._WATCHLIST 内存版）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # v1.2 加 project / group_color（与 patrol_positions 一致，支持分组拖拽）
    cursor.execute("PRAGMA table_info(watchlist)")
    wl_cols = {row[1] for row in cursor.fetchall()}
    if 'project' not in wl_cols:
        cursor.execute("ALTER TABLE watchlist ADD COLUMN project TEXT NOT NULL DEFAULT '默认'")
    if 'group_color' not in wl_cols:
        cursor.execute("ALTER TABLE watchlist ADD COLUMN group_color TEXT DEFAULT ''")
    # v1.2 持仓表加 sort_order（拖拽排序持久化）
    cursor.execute("PRAGMA table_info(patrol_positions)")
    cols = {row[1] for row in cursor.fetchall()}
    if 'sort_order' not in cols:
        cursor.execute("ALTER TABLE patrol_positions ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
    if 'group_color' not in cols:
        cursor.execute("ALTER TABLE patrol_positions ADD COLUMN group_color TEXT DEFAULT ''")
    # v1.2 选股快照表（scanner 历史对比）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scanner_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL DEFAULT '',
            strategy TEXT NOT NULL,
            params TEXT NOT NULL DEFAULT '{}',
            codes TEXT NOT NULL,            -- JSON 数组
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scanner_strategy_created ON scanner_snapshots(strategy, created_at DESC)")

    # v1.3 股票基础信息表（启动时一次同步，~5000 行）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_basics (
            code TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            industry TEXT,
            market TEXT NOT NULL,
            list_date TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # v1.3 K 线缓存表（按 code+date 主键，~30 万行 = 25MB）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_kline (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL,
            volume INTEGER,
            PRIMARY KEY (code, date)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_code_date ON stock_kline(code, date DESC)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_weekly_kline (
            code TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume INTEGER,
            PRIMARY KEY (code, date)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_weekly_code_date ON stock_weekly_kline(code, date DESC)")

    conn.commit()
    conn.close()