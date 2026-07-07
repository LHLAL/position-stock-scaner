"""股票基础信息仓库（持久化层）"""
from __future__ import annotations
import sqlite3
import logging
from typing import List, Optional, Dict
from dataclasses import dataclass

from .sqlite_db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class StockBasic:
    """股票基础信息（启动时同步一次，变化极少）"""
    code: str
    name: str
    industry: str = ''
    market: str = 'SH'
    list_date: str = ''
    updated_at: str = ''


class StockBasicRepo:
    """A 股基础信息仓库：code/name/industry 持久化到 SQLite"""

    def upsert_many(self, stocks: List[StockBasic]) -> int:
        """批量写入（启动时同步全市场 5000+ 只用）"""
        if not stocks:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO stock_basics
                (code, name, industry, market, list_date, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [(s.code, s.name, s.industry, s.market, s.list_date) for s in stocks],
            )
            conn.commit()
            return len(stocks)
        finally:
            conn.close()

    def get(self, code: str) -> Optional[StockBasic]:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM stock_basics WHERE code = ?", (code,)
            ).fetchone()
            return self._row_to_basic(row) if row else None
        finally:
            conn.close()

    def get_name(self, code: str) -> Optional[str]:
        """高频快捷方法：只取 name（单只查询 < 1ms）"""
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT name FROM stock_basics WHERE code = ?", (code,)
            ).fetchone()
            return row['name'] if row else None
        finally:
            conn.close()

    def get_names_batch(self, codes: List[str]) -> Dict[str, str]:
        """批量取 name（扫盘 N 只股票 → 1 次查询）"""
        if not codes:
            return {}
        conn = get_connection()
        try:
            placeholders = ','.join('?' * len(codes))
            rows = conn.execute(
                f"SELECT code, name FROM stock_basics WHERE code IN ({placeholders})",
                codes,
            ).fetchall()
            return {r['code']: r['name'] for r in rows}
        finally:
            conn.close()

    def count(self) -> int:
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM stock_basics").fetchone()
            return row['n'] if row else 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_basic(row) -> StockBasic:
        return StockBasic(
            code=row['code'],
            name=row['name'],
            industry=row['industry'] or '',
            market=row['market'] or 'SH',
            list_date=row['list_date'] or '',
            updated_at=row['updated_at'] or '',
        )


# 全局单例
stock_basic_repo = StockBasicRepo()
