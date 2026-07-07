"""K 线仓库（持久化层）"""
from __future__ import annotations
import logging
import pandas as pd
from datetime import date, timedelta
from typing import Optional

from .sqlite_db import get_connection

logger = logging.getLogger(__name__)


class KLineRepo:
    """60/180/365 天 K 线缓存（按 (code, date) 主键）"""

    def get(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """读 K 线，没有返回 None（让调用方决定要不要拉）"""
        start_date = (date.today() - timedelta(days=days)).isoformat()
        conn = get_connection()
        try:
            df = pd.read_sql_query(
                """
                SELECT date, open, high, low, close, volume
                FROM stock_kline
                WHERE code = ? AND date >= ?
                ORDER BY date ASC
                """,
                conn,
                params=(code, start_date),
            )
            return df if not df.empty else None
        finally:
            conn.close()

    def upsert(self, code: str, df: pd.DataFrame) -> int:
        """写 K 线（用 INSERT OR REPLACE 覆盖同一天数据）

        v3.1-fix: 加硬错误护栏，拒绝明显非法的行（NaN/负值/OHLC 关系倒置）。
        不做软校验（z-score 等）—— 真实数据短期波动可能很大，软校验会误伤。
        """
        if df is None or df.empty:
            return 0
        rows = []
        skipped = 0
        for _, row in df.iterrows():
            try:
                o = float(row.get('open', 0) or 0)
                h = float(row.get('high', 0) or 0)
                l = float(row.get('low', 0) or 0)
                c = float(row.get('close', 0) or 0)
                v = int(float(row.get('volume', 0) or 0))
            except (TypeError, ValueError):
                skipped += 1
                continue
            # 硬错误：负值 / 0 close / OHLC 关系倒置
            if c <= 0 or o <= 0 or h <= 0 or l <= 0 or v < 0:
                skipped += 1
                continue
            if h < max(o, c) or l > min(o, c):
                skipped += 1
                continue
            date = str(row.get('date', ''))[:10]
            if not date or date == 'NaT':
                skipped += 1
                continue
            rows.append((code, date, o, h, l, c, v))
        if skipped:
            logger.warning(f'upsert {code} 跳过 {skipped} 行非法数据')
        if not rows:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO stock_kline
                (code, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
            return len(rows)
        finally:
            conn.close()

    def count(self) -> int:
        conn = get_connection()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM stock_kline").fetchone()
            return row['n'] if row else 0
        finally:
            conn.close()


# 全局单例
kline_repo = KLineRepo()
