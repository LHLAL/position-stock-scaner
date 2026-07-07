"""
交易日历工具
判断今天是周几、是否开盘、假期、周末等信息，以及国际市场影响
"""
import datetime
from typing import Dict, List, Optional, Tuple, Set
import logging

logger = logging.getLogger(__name__)

WEEKDAYS_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

_HOLIDAYS_CACHE: Dict[int, Set[str]] = {}
_HOLIDAYS_CACHE_YEAR = 0


def _load_holidays(year: int) -> Set[str]:
    """用 akshare 动态获取当年交易日历，缓存。失败时返回空集合。"""
    global _HOLIDAYS_CACHE_YEAR
    if _HOLIDAYS_CACHE_YEAR == year and _HOLIDAYS_CACHE:
        return _HOLIDAYS_CACHE.get(year, set())
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            return set()
        all_dates = set()
        for _, row in df.iterrows():
            date_str = str(row['trade_date'])[:10]
            all_dates.add(date_str)
        # 所有非交易日的日期（交易所标注为不开盘的）
        # 更简单的方式：取全年所有日期，减去交易日 = 假期
        holidays = set()
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)
        d = start_date
        while d <= end_date:
            ds = d.isoformat()
            if ds not in all_dates:
                holidays.add(ds)
            d += datetime.timedelta(days=1)
        _HOLIDAYS_CACHE[year] = holidays
        _HOLIDAYS_CACHE_YEAR = year
        return holidays
    except Exception as e:
        logger.warning(f"动态获取交易日历失败 ({e})，使用硬编码补充")
        return set()


# v1.3: 港股已停支持，HK_HOLIDAYS 删除


def get_today_info() -> Dict:
    """获取今日交易日历信息（动态加载全年交易所休假日程）"""
    now = datetime.datetime.now()
    today = now.date()
    weekday = today.weekday()  # 0=周一, 6=周日
    year = today.year

    holidays = _load_holidays(year)

    is_weekend = weekday >= 5
    is_holiday = today.isoformat() in holidays

    # A股是否开盘（非周末且非假期）
    is_market_open_today = not is_weekend and not is_holiday

    # 明天是否开盘
    tomorrow = today + datetime.timedelta(days=1)
    tomorrow_weekday = tomorrow.weekday()
    tomorrow_is_weekend = tomorrow_weekday >= 5
    tomorrow_is_holiday = tomorrow.isoformat() in holidays
    is_market_open_tomorrow = not tomorrow_is_weekend and not tomorrow_is_holiday

    # 距离下一个交易日还有几天
    days_to_next_trading = 0
    next_trading_day = today
    while True:
        days_to_next_trading += 1
        next_trading_day = next_trading_day + datetime.timedelta(days=1)
        ntd_weekday = next_trading_day.weekday()
        ntd_is_weekend = ntd_weekday >= 5
        ntd_is_holiday = next_trading_day.isoformat() in holidays
        if not ntd_is_weekend and not ntd_is_holiday:
            break

    # 最近的交易日
    if is_market_open_today:
        last_trading_day = today
    else:
        last_trading_day = today
        while True:
            last_trading_day = last_trading_day - datetime.timedelta(days=1)
            ltd_weekday = last_trading_day.weekday()
            ltd_is_weekend = ltd_weekday >= 5
            ltd_is_holiday = last_trading_day.isoformat() in holidays
            if not ltd_is_weekend and not ltd_is_holiday:
                break

    # 是否是特殊日期
    is_monday = weekday == 0
    is_friday = weekday == 4
    is_month_end = (today + datetime.timedelta(days=7)).month != today.month
    is_quarter_end = today.month in [3, 6, 9, 12] and is_month_end

    # 计算周效应
    week_effect = '正常交易日'
    if is_monday:
        week_effect = '周一（注意周末消息面影响，市场波动可能较大）'
    elif is_friday:
        week_effect = '周五（周末前投资者通常偏谨慎，交易量可能下降）'
    elif weekday == 2:  # 周三
        week_effect = '周三（周中，市场方向可能明朗）'
    elif is_weekend:
        week_effect = '周末（休市，关注周末消息面）'

    # 假期前效应
    if days_to_next_trading == 3:  # 周五 + 周末 = 3天
        holiday_effect = '临近长周末，建议控制仓位'
    elif days_to_next_trading > 3:
        holiday_effect = f'临近假期，休市{days_to_next_trading}天，注意风险'
    else:
        holiday_effect = '无临近假期'

    return {
        'date': today.isoformat(),
        'datetime': now.isoformat(),
        'weekday': weekday + 1,  # 1-7
        'weekday_cn': WEEKDAYS_CN[weekday],
        'is_weekend': is_weekend,
        'is_holiday': is_holiday,
        'is_market_open_today': is_market_open_today,
        'is_market_open_tomorrow': is_market_open_tomorrow,
        'days_to_next_trading': days_to_next_trading,
        'last_trading_day': last_trading_day.isoformat(),
        'next_trading_day': next_trading_day.isoformat(),
        'is_monday': is_monday,
        'is_friday': is_friday,
        'is_month_end': is_month_end,
        'is_quarter_end': is_quarter_end,
        'week_effect': week_effect,
        'holiday_effect': holiday_effect,
    }


def get_global_market_status() -> Dict:
    """v1.3: 港美股已停支持，保留函数签名返回空状态。"""
    return {
        'hk_market_open_today': False,
        'note': '港美股已停支持，外部联动仅参考 A 股板块。',
    }


def build_calendar_analysis(code: str = None, market: str = 'A股') -> Dict:
    """构建完整的日历分析"""
    today_info = get_today_info()
    global_status = get_global_market_status()

    # 计算时间因子对分析的影响
    impact_factors = []

    # 周效应
    if today_info['is_monday']:
        impact_factors.append({
            'type': 'week_effect',
            'level': 'medium',
            'title': '周一效应',
            'description': '周一受周末消息面影响，波动可能加大，注意高开/低开风险',
        })

    if today_info['is_friday']:
        impact_factors.append({
            'type': 'week_effect',
            'level': 'low',
            'title': '周五效应',
            'description': '周五投资者偏谨慎，交易量可能下降，持仓需考虑周末消息面',
        })

    # 假期效应
    if today_info['days_to_next_trading'] > 2:
        impact_factors.append({
            'type': 'holiday_effect',
            'level': 'medium' if today_info['days_to_next_trading'] > 3 else 'low',
            'title': f'临近休市（{today_info["days_to_next_trading"]}天）',
            'description': f'距离下一个交易日还有{today_info["days_to_next_trading"]}天，长假期前建议控制仓位',
        })

    # 月末/季末效应
    if today_info['is_quarter_end']:
        impact_factors.append({
            'type': 'calendar_effect',
            'level': 'high',
            'title': '季末效应',
            'description': '季度末可能存在机构调仓、基金排名等因素，注意市场异动',
        })
    elif today_info['is_month_end']:
        impact_factors.append({
            'type': 'calendar_effect',
            'level': 'medium',
            'title': '月末效应',
            'description': '月末可能存在资金面紧张等因素，注意流动性风险',
        })

    # 休市状态
    if not today_info['is_market_open_today']:
        impact_factors.append({
            'type': 'market_status',
            'level': 'info',
            'title': '今日休市',
            'description': f'今日是{today_info["weekday_cn"]}{"（周末）" if today_info["is_weekend"] else "（假期）"}，A股休市。下一个交易日是{today_info["next_trading_day"]}。',
        })

    # v1.3: 港股联动已停支持，不再添加相关 impact_factors

    # 总结
    if market == 'A股':
        market_specific = {
            'trading_hours': '9:30-11:30, 13:00-15:00',
            'lunch_break': '11:30-13:00',
            't_plus_1': True,
        }
    else:
        market_specific = {}

    return {
        'today': today_info,
        'global_market': global_status,
        'impact_factors': impact_factors,
        'market_specific': market_specific,
        'summary': _build_calendar_summary(today_info, impact_factors),
    }


def _build_calendar_summary(today_info: Dict, impact_factors: List[Dict]) -> str:
    """构建日历摘要文本"""
    lines = []

    # 基础信息
    lines.append(f"【日期】{today_info['date']} {today_info['weekday_cn']}")

    # 市场状态
    if today_info['is_market_open_today']:
        lines.append("【市场状态】今日正常交易")
    else:
        lines.append(f"【市场状态】今日休市（{today_info['weekday_cn']}）")

    # 明天是否开盘
    if today_info['is_market_open_tomorrow']:
        lines.append("【明日】正常开盘")
    else:
        lines.append(f"【明日】休市，下一个交易日：{today_info['next_trading_day']}")

    # 影响因素
    if impact_factors:
        lines.append("\n【时间因素提示】")
        for factor in impact_factors:
            level_mark = {'high': '⚠️', 'medium': '•', 'low': '•', 'info': 'ℹ️'}
            lines.append(f"{level_mark.get(factor['level'], '')} {factor['title']}：{factor['description']}")

    return '\n'.join(lines)


if __name__ == '__main__':
    # 测试
    print(build_calendar_analysis()['summary'])
