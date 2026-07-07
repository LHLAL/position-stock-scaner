"""周 K 线仓库（持久化层）"""
from __future__ import annotations
import logging
import pandas as pd
from datetime import date, timedelta
from typing import Optional

from .sqlite_db import get_connection

logger = logging.getLogger(__name__)


class WeeklyKLineRepo:
    """周 K 线缓存（按 (code, date) 主键）"""

    def get(self, code: str, weeks: int) -> Optional[pd.DataFrame]:
        start_date = (date.today() - timedelta(weeks=weeks)).isoformat()
        conn = get_connection()
        try:
            df = pd.read_sql_query(
                """SELECT date, open, high, low, close, volume
                FROM stock_weekly_kline WHERE code = ? AND date >= ?
                ORDER BY date ASC""",
                conn, params=(code, start_date),
            )
            return df if not df.empty else None
        finally:
            conn.close()

    def upsert(self, code: str, df: pd.DataFrame) -> int:
        if df is None or df.empty:
            return 0
        rows, skipped = [], 0
        for _, row in df.iterrows():
            try:
                o = float(row.get('open', 0) or 0)
                h = float(row.get('high', 0) or 0)
                l = float(row.get('low', 0) or 0)
                c = float(row.get('close', 0) or 0)
                v = int(float(row.get('volume', 0) or 0))
            except (TypeError, ValueError):
                skipped += 1; continue
            if c <= 0 or o <= 0 or h <= 0 or l <= 0 or v < 0 or h < max(o, c) or l > min(o, c):
                skipped += 1; continue
            d = str(row.get('date', ''))[:10]
            if not d or d == 'NaT':
                skipped += 1; continue
            rows.append((code, d, o, h, l, c, v))
        if skipped:
            logger.warning(f'weekly upsert {code} 跳过 {skipped} 行')
        if not rows:
            return 0
        conn = get_connection()
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO stock_weekly_kline (code,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
                rows)
            conn.commit()
            return len(rows)
        finally:
            conn.close()


weekly_kline_repo = WeeklyKLineRepo()
