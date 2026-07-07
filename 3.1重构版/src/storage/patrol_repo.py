"""持仓仓库"""
from typing import Dict, List, Optional
import sqlite3
from .sqlite_db import get_connection

class PatrolRepository:
    """持仓仓库"""

    def __init__(self, conn: sqlite3.Connection = None):
        self.conn = conn or get_connection()

    def get_all(self) -> List[Dict]:
        """获取所有持仓（按 project / code 排序 — 旧版默认排序，v1.2 改用 get_all_sorted）"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM patrol_positions ORDER BY project, code")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_all_sorted(self) -> List[Dict]:
        """v1.2: 按 sort_order 排序返回，供拖拽后保持顺序"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM patrol_positions ORDER BY sort_order ASC, id ASC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def reorder(self, ordered_ids: List[int]) -> int:
        """v1.2: 按 ordered_ids 顺序逐条写 sort_order；返回实际更新条数"""
        cursor = self.conn.cursor()
        n = 0
        try:
            for i, pid in enumerate(ordered_ids):
                cursor.execute(
                    "UPDATE patrol_positions SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (i, int(pid)),
                )
                n += cursor.rowcount
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return n

    def get_by_id(self, position_id: int) -> Optional[Dict]:
        """获取单个持仓"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM patrol_positions WHERE id = ?", (position_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_by_project(self, project: str) -> List[Dict]:
        """按项目获取持仓"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM patrol_positions WHERE project = ? ORDER BY code", (project,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def add(self, code: str, shares: float, cost_price: float, market: str, project: str = "", notes: str = "", name: str = "") -> Dict:
        cursor = self.conn.cursor()
        # v1.2: 新加的持仓排到末尾
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM patrol_positions")
        next_order = cursor.fetchone()[0]
        cursor.execute("""
            INSERT INTO patrol_positions (code, name, shares, cost_price, market, project, notes, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (code, name, shares, cost_price, market, project, notes, next_order))
        self.conn.commit()
        return self.get_by_id(cursor.lastrowid)

    def update(self, position_id: int, **kwargs) -> Optional[Dict]:
        if not kwargs:
            return self.get_by_id(position_id)

        fields = ', '.join(f"{k} = ?" for k in kwargs.keys())
        values = list(kwargs.values()) + [position_id]

        cursor = self.conn.cursor()
        cursor.execute(f"UPDATE patrol_positions SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", values)
        self.conn.commit()
        return self.get_by_id(position_id)

    def delete(self, position_id: int) -> bool:
        """删除持仓"""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM patrol_positions WHERE id = ?", (position_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def save_analysis_result(self, position_id: int, code: str, analysis_data: dict) -> None:
        import json
        cursor = self.conn.cursor()
        strategy_json = ''
        if analysis_data.get('strategy'):
            strategy_json = json.dumps(analysis_data.get('strategy'), ensure_ascii=False)
        cursor.execute("""
            INSERT OR REPLACE INTO patrol_analysis_results
            (position_id, code, ai_analysis, technical_score, fundamental_score,
             sentiment_score, comprehensive_score, recommendation, recommendation_reason, strategy, analyzed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            position_id,
            code,
            analysis_data.get('ai_analysis', ''),
            analysis_data.get('technical_score', 0),
            analysis_data.get('fundamental_score', 0),
            analysis_data.get('sentiment_score', 0),
            analysis_data.get('comprehensive_score', 0),
            analysis_data.get('recommendation', ''),
            analysis_data.get('recommendation_reason', ''),
            strategy_json,
        ))
        self.conn.commit()

    def get_analysis_result(self, position_id: int) -> Optional[Dict]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM patrol_analysis_results
            WHERE position_id = ?
            ORDER BY analyzed_at DESC
            LIMIT 1
        """, (position_id,))
        row = cursor.fetchone()
        return dict(row) if row else None