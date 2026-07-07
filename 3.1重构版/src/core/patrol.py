"""持仓巡检模块"""
import logging
from typing import Dict, List, Optional

from src.repository.stock_repo import stock_repo


logger = logging.getLogger(__name__)


class PatrolManager:
    """持仓巡检管理器"""

    def __init__(self):
        self.repo = stock_repo.get_patrol_repo()

    def get_all_positions(self) -> List[Dict]:
        """v1.2: 按 sort_order 排序返回（拖拽后顺序）"""
        positions = self.repo.get_all_sorted()
        for p in positions:
            if not p.get('name') or p.get('name') == p.get('code'):
                p['name'] = self.resolve_stock_name(p['code'], p.get('market', 'SH'))
                if p['name']:
                    self.repo.update(p['id'], name=p['name'])
            p['current_price'] = None
            p['profit_loss'] = 0
            p['profit_loss_pct'] = 0
        return positions

    def get_position(self, position_id: int) -> Optional[Dict]:
        """获取单个持仓"""
        return self.repo.get_by_id(position_id)

    def resolve_stock_name(self, code: str, market: str = "SH") -> str:
        """v1.3: 走 stock_repo（SQLite 优先），不再直接调腾讯/akshare"""
        from src.repository.stock_repo import stock_repo
        code = (code or '').strip().upper()
        if not code:
            return ''
        return stock_repo.get_name(code) or ''

    def add_position(self, code: str, shares: float, cost_price: float, market: str = "SH",
                     project: str = "", notes: str = "") -> Dict:
        code = (code or '').strip().upper()
        detected = stock_repo.infer_market(code)
        if market != detected:
            market = detected
        name = self.resolve_stock_name(code, market)
        return self.repo.add(
            code=code, name=name, shares=shares, cost_price=cost_price,
            market=market, project=project, notes=notes,
        )

    def update_position(self, position_id: int, **kwargs) -> Optional[Dict]:
        """更新持仓（v1.2 扩字段：project / group_color）"""
        if kwargs.get('code') and not kwargs.get('name'):
            code = str(kwargs['code']).strip().upper()
            kwargs['code'] = code
            kwargs['name'] = self.resolve_stock_name(code, stock_repo.infer_market(code))
        return self.repo.update(position_id, **kwargs)

    def reorder_positions(self, ordered_ids: List[int]) -> int:
        """v1.2 拖拽排序：按 ordered_ids 顺序给每条写 sort_order"""
        return self.repo.reorder(ordered_ids)

    def delete_position(self, position_id: int) -> bool:
        """删除持仓"""
        return self.repo.delete(position_id)

    def get_quotes(self) -> List[Dict]:
        """获取所有持仓的实时报价

        v1.2: 用 registry.get_batch_quotes_v2 一次拉全市场快照，避免 N 次网络往返。
        6 只持仓的报价请求从 ~6s 降到 ~3s（全市场 5000 只快照拉一次）。
        """
        positions = self.get_all_positions()

        if not positions:
            return positions

        # 先统一更新 market 字段（一次提交）
        for p in positions:
            market = stock_repo.infer_market(p['code'])
            if market != p.get('market', 'SH'):
                self.repo.update(p['id'], market=market)

        # 批量拉报价：优先腾讯真实行情（不使用 AkShare）
        codes = [p['code'] for p in positions]
        quote_map = {}
        try:
            quote_map = stock_repo.get_batch_quotes(codes) or {}
        except Exception:
            logger.exception('batch quotes failed, fallback per-code')
            quote_map = {c: stock_repo.get_quote(c, stock_repo.infer_market(c)) for c in codes}

        # 兜底：腾讯没返回的 code，用注册表里其他源逐个补
        for code in codes:
            if quote_map.get(code) is None:
                q = stock_repo.get_quote(code, stock_repo.infer_market(code))
                if q is not None:
                    quote_map[code] = q

        for p in positions:
            quote = quote_map.get(p['code'])
            if quote:
                p['current_price'] = quote.price
                p['change_pct'] = quote.change_pct
                p['profit_loss'] = (quote.price - p['cost_price']) * p['shares']
                p['profit_loss_pct'] = (quote.price / p['cost_price'] - 1) * 100
            else:
                p['current_price'] = p['cost_price']
                p['change_pct'] = 0
                p['profit_loss'] = 0
                p['profit_loss_pct'] = 0

        return positions

    def calculate_profit_loss(self, position_id: int) -> Optional[Dict]:
        position = self.repo.get_by_id(position_id)
        if not position:
            return None

        market = stock_repo.infer_market(position['code'])
        quote = stock_repo.get_quote(position['code'], market)
        if quote:
            position['current_price'] = quote.price
            position['profit_loss'] = (quote.price - position['cost_price']) * position['shares']
            position['profit_loss_pct'] = (quote.price / position['cost_price'] - 1) * 100
        else:
            position['current_price'] = position['cost_price']
            position['profit_loss'] = 0
            position['profit_loss_pct'] = 0

        return position