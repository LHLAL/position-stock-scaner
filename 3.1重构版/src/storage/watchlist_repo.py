"""自选股仓库 · v1.2 · 2026-06-14
单表 watchlist (code PRIMARY KEY) —— 替代 v1_routes._WATCHLIST 内存版

v1.2 增加 project / group_color 字段支持分组 + 跨组拖拽
"""
from typing import Dict, List, Optional
import sqlite3
from .sqlite_db import get_connection


DEFAULT_PROJECT = '默认'


class WatchlistRepository:
    """自选股仓库（按 project, sort_order, code 排序）"""

    def __init__(self, conn: sqlite3.Connection = None):
        self.conn = conn or get_connection()

    def get_all(self) -> List[Dict]:
        """返回所有自选股，按 project 字典序、sort_order 升序、code 升序"""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT code, name, project, group_color, sort_order "
            "FROM watchlist "
            "ORDER BY project ASC, sort_order ASC, code ASC"
        )
        return [dict(row) for row in cursor.fetchall()]

    def exists(self, code: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM watchlist WHERE code = ?", (code,))
        return cursor.fetchone() is not None

    def add(self, code: str, name: str = "", project: str = DEFAULT_PROJECT,
            group_color: str = "") -> Optional[Dict]:
        """加自选；已存在返回 None（让上层返回 409）。"""
        if self.exists(code):
            return None
        project = (project or DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
        cursor = self.conn.cursor()
        # 末尾 = 当前 project 内最大 sort_order + 1（实现"加到组底"）
        cursor.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM watchlist WHERE project = ?",
            (project,),
        )
        next_order = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO watchlist (code, name, project, group_color, sort_order) "
            "VALUES (?, ?, ?, ?, ?)",
            (code, name or code, project, group_color, next_order),
        )
        self.conn.commit()
        return {
            "code": code,
            "name": name or code,
            "project": project,
            "group_color": group_color,
            "sort_order": next_order,
        }

    def remove(self, code: str) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM watchlist WHERE code = ?", (code,))
        self.conn.commit()
        return cursor.rowcount > 0

    def rename_project(self, old: str, new: str) -> int:
        """v1.2 改组名：old -> new；new 为空字符串则不改"""
        new = (new or '').strip()
        if not new or new == old:
            return 0
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE watchlist SET project = ? WHERE project = ?",
            (new, old),
        )
        self.conn.commit()
        return cursor.rowcount

    def reorder(self, ordered: List[Dict]) -> int:
        """v1.2 一次写回：每个元素形如 {code, project, sort_order}

        用途：组内拖拽重排 / 跨组拖拽换 project / 多条批量更新。
        走单事务，全部成功才提交。
        """
        if not ordered:
            return 0
        cursor = self.conn.cursor()
        n = 0
        for i, item in enumerate(ordered):
            code = item.get('code')
            if not code:
                continue
            project = (item.get('project') or DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
            # 没传 sort_order 就用列表下标
            sort_order = item.get('sort_order', i)
            cursor.execute(
                "UPDATE watchlist SET project = ?, sort_order = ? WHERE code = ?",
                (project, int(sort_order), code),
            )
            n += cursor.rowcount
        self.conn.commit()
        return n


def get_repo() -> WatchlistRepository:
    return WatchlistRepository()
