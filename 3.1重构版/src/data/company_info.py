"""公司基本信息/违规记录 —— 巨潮 cninfo"""
from __future__ import annotations
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# 简化的"问题股"风险关键词（轻量缓存层，绕开 akshare 网络依赖）
PROBLEM_KEYWORDS = ['ST', '*ST', 'S*ST', 'SST', '退', 'PT']


def quick_problem_check(name: str) -> Optional[str]:
    """基于股票名称快速判定风险股（O(1) 字符串扫描）

    Returns: 风险描述字符串，非问题股返回 None
    """
    if not name:
        return None
    name_upper = name.upper()
    for kw in PROBLEM_KEYWORDS:
        if kw in name_upper:
            return f"名称含{kw}风险标记"
    return None


def cninfo_problem_check(code: str) -> Optional[str]:
    """通过 akshare 查巨潮 cninfo 违规记录（仅在名称检查通过后再调）

    Returns: 违规描述字符串，无违规返回 None
    """
    try:
        import os
        for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            os.environ.pop(k, None)
        os.environ['no_proxy'] = '*'
        import akshare as ak
        df = ak.stock_info_mdpd_cninfo(symbol=code)
        if df is None or df.empty:
            return None
        for _, row in df.iterrows():
            reason = str(row.get('整改类型', '')) + str(row.get('违规类型', ''))
            for x in ['财务造假', '欺诈', '违规披露', '大股东占用', '资金占用']:
                if x in reason:
                    return f"涉嫌{reason[:20]}"
        return None
    except Exception as e:
        logger.debug(f"cninfo 违规查询失败 {code}: {e}")
        return None
