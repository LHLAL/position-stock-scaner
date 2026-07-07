"""技术指标 + 4 维评分的「含义 + 当前推荐操作」生成器

为前端展示提供:
  explain_score(dim, value) -> {level, meaning, action}
  explain_indicator(label, value, ctx) -> {level, meaning, action}

`level`  ∈ { strong, pos, neutral, neg, strong_neg }
`meaning` 1-2 句通俗解释
`action`  推荐操作
"""

from typing import Dict, Optional


# ── 4 维评分 含义 + 操作 ─────────────────────
SCORE_DIMS = {
    "technical": {
        "name": "技术面",
        "weight": 0.40,
        "desc": "K 线/均线/MACD/RSI 等技术指标综合得分（0-100）",
    },
    "fundamental": {
        "name": "基本面",
        "weight": 0.30,
        "desc": "PE/PB/ROE/盈利等估值与盈利能力（0-100）",
    },
    "sentiment": {
        "name": "情绪面",
        "weight": 0.20,
        "desc": "新闻/北向/主力资金等市场情绪（0-100）",
    },
    "composite": {
        "name": "综合",
        "weight": 0.10,
        "desc": "技术 40% + 基本面 30% + 情绪 20% + 大盘 10%",
    },
}


def _bucket(value: float) -> str:
    """0-100 分桶"""
    if value >= 75:
        return "strong"
    if value >= 55:
        return "pos"
    if value >= 45:
        return "neutral"
    if value >= 30:
        return "neg"
    return "strong_neg"


SCORE_ACTIONS = {
    "technical": {
        "strong":     {"level": "strong",     "meaning": "技术面强势：均线多头 + 趋势确认",     "action": "可继续持有，沿 MA5/MA10 低吸为主"},
        "pos":        {"level": "pos",        "meaning": "技术面偏多：趋势向上但有背离可能",     "action": "持有，警惕高位放量滞涨信号"},
        "neutral":    {"level": "neutral",    "meaning": "技术面中性：震荡无明确方向",           "action": "观望，等待放量突破或跌破"},
        "neg":        {"level": "neg",        "meaning": "技术面偏空：均线压制、量能不足",       "action": "减仓，跌破止损位出局"},
        "strong_neg": {"level": "strong_neg", "meaning": "技术面弱势：空头排列 + 趋势确认",     "action": "建议止损或空仓"},
    },
    "fundamental": {
        "strong":     {"level": "strong",     "meaning": "基本面优秀：低估值 + 高盈利",         "action": "适合中长期建仓"},
        "pos":        {"level": "pos",        "meaning": "基本面稳健：估值合理、盈利稳定",     "action": "可分批配置"},
        "neutral":    {"level": "neutral",    "meaning": "基本面一般：财务指标中规中矩",       "action": "关注盈利改善信号"},
        "neg":        {"level": "neg",        "meaning": "基本面偏弱：估值偏高或盈利下滑",     "action": "谨慎，避免重仓"},
        "strong_neg": {"level": "strong_neg", "meaning": "基本面差：财务风险/亏损",             "action": "建议规避"},
    },
    "sentiment": {
        "strong":     {"level": "strong",     "meaning": "情绪亢奋：主力资金大幅流入、新闻看多", "action": "警惕追高，等回调"},
        "pos":        {"level": "pos",        "meaning": "情绪偏多：北向/主力温和流入",         "action": "可持有"},
        "neutral":    {"level": "neutral",    "meaning": "情绪中性：观望为主",                 "action": "持仓观望"},
        "neg":        {"level": "neg",        "meaning": "情绪偏空：资金流出/消息面利空",     "action": "考虑减仓"},
        "strong_neg": {"level": "strong_neg", "meaning": "情绪恐慌：踩踏式卖出",              "action": "等待情绪企稳再介入"},
    },
    "composite": {
        "strong":     {"level": "strong",     "meaning": "综合强势：多维度共振走强",           "action": "可加仓持有"},
        "pos":        {"level": "pos",        "meaning": "综合偏多：整体偏正向",               "action": "持有为主"},
        "neutral":    {"level": "neutral",    "meaning": "综合中性：缺乏方向",                 "action": "观望"},
        "neg":        {"level": "neg",        "meaning": "综合偏空：多维度转弱",               "action": "减仓"},
        "strong_neg": {"level": "strong_neg", "meaning": "综合弱势：共振走弱",                 "action": "建议离场"},
    },
}


def explain_score(dim: str, value: Optional[float]) -> dict:
    """4 维评分解释"""
    if value is None:
        return {"level": "neutral", "meaning": "数据不足", "action": "—"}
    bucket = _bucket(value)
    return {
        **SCORE_ACTIONS.get(dim, {}).get(bucket, {}),
        "value": round(value, 1),
    }


# ── 技术指标 含义 + 操作 ─────────────────────
def _rsi_action(val: float) -> dict:
    if val < 20:
        return {"level": "strong",     "meaning": "RSI 严重超卖（<20），可能存在反弹机会", "action": "关注右侧放量确认，谨慎抄底"}
    if val < 30:
        return {"level": "pos",        "meaning": "RSI 超卖区（<30）",                   "action": "等待金叉/放量，可轻仓试多"}
    if val > 80:
        return {"level": "strong_neg", "meaning": "RSI 严重超买（>80），短期回调风险大",   "action": "建议减仓，止盈部分仓位"}
    if val > 70:
        return {"level": "neg",        "meaning": "RSI 超买区（>70）",                   "action": "谨慎追高，设定止盈"}
    if 45 <= val <= 55:
        return {"level": "neutral",    "meaning": "RSI 中性（45-55），趋势不明",         "action": "观望"}
    if val < 45:
        return {"level": "pos",        "meaning": "RSI 偏弱，但未超卖",                  "action": "不抄底，等企稳"}
    return {"level": "neg",           "meaning": "RSI 偏强，但未超买",                  "action": "可持有，警惕背离"}


def _macd_action(line: float, signal: float, hist: float) -> dict:
    if hist > 0 and line > signal:
        return {"level": "pos",    "meaning": "MACD 金叉且柱状为正，多头动能", "action": "可继续持有"}
    if hist < 0 and line < signal:
        return {"level": "neg",    "meaning": "MACD 死叉且柱状为负，空头动能", "action": "减仓或离场"}
    if hist > 0:
        return {"level": "pos",    "meaning": "MACD 柱状转正，趋势转暖",     "action": "关注是否金叉确认"}
    if hist < 0:
        return {"level": "neg",    "meaning": "MACD 柱状为负，趋势偏弱",     "action": "不抄底"}
    return {"level": "neutral",    "meaning": "MACD 接近零轴，无明确方向",   "action": "观望"}


def _kdj_action(k: float, d: float, j: float) -> dict:
    if j < 0:
        return {"level": "pos",     "meaning": "KDJ J 值<0，严重超卖",       "action": "关注反弹信号"}
    if j > 100:
        return {"level": "neg",     "meaning": "KDJ J 值>100，严重超买",     "action": "警惕回调，减仓"}
    if k > d and j > k:
        return {"level": "pos",     "meaning": "KDJ 金叉向上",               "action": "可继续持有"}
    if k < d and j < k:
        return {"level": "neg",     "meaning": "KDJ 死叉向下",               "action": "建议减仓"}
    if k > 80 and d > 80:
        return {"level": "neg",     "meaning": "KDJ 双线超买（>80）",        "action": "减仓"}
    if k < 20 and d < 20:
        return {"level": "pos",     "meaning": "KDJ 双线超卖（<20）",        "action": "等待金叉确认"}
    return {"level": "neutral",     "meaning": "KDJ 区间内震荡",             "action": "观望"}


def _bb_action(bb_pct: float) -> dict:
    """%B: 0-1 表示在布林带中的位置"""
    if bb_pct > 1.0:
        return {"level": "strong_neg", "meaning": "%B>1.0 突破上轨，强势超买", "action": "警惕回调"}
    if bb_pct > 0.8:
        return {"level": "neg",        "meaning": "%B 0.8-1.0 接近上轨",      "action": "不追高"}
    if bb_pct < 0.0:
        return {"level": "strong",     "meaning": "%B<0.0 跌破下轨，强势超卖", "action": "关注反弹"}
    if bb_pct < 0.2:
        return {"level": "pos",        "meaning": "%B 0.0-0.2 接近下轨",      "action": "等待反转信号"}
    return {"level": "neutral",        "meaning": "%B 0.2-0.8 中轨区间",       "action": "观望"}


def explain_indicator(label: str, value, ctx: Optional[dict] = None) -> dict:
    """根据 label 派发解释器"""
    ctx = ctx or {}
    try:
        # 1) RSI
        if "RSI" in label:
            v = float(value)
            return _rsi_action(v)
        # 2) MACD DIF/DEA/柱
        if "MACD" in label:
            if "DIF" in label or "DEA" in label or "柱" in label:
                line = float(ctx.get("macd_line", 0) or 0)
                sig = float(ctx.get("macd_signal_line", 0) or 0)
                hist = float(ctx.get("macd_histogram", 0) or 0)
                return _macd_action(line, sig, hist)
        # 3) KDJ
        if "KDJ" in label:
            k = float(ctx.get("kdj_k", 50) or 50)
            d = float(ctx.get("kdj_d", 50) or 50)
            j = float(ctx.get("kdj_j", 50) or 50)
            return _kdj_action(k, d, j)
        # 4) 布林
        if "布林" in label or label == "%B":
            if label == "%B":
                bb = float(value)
                return _bb_action(bb)
            # 上下轨/中轨：固定提示
            if "上轨" in label:
                return {"level": "neg",    "meaning": "布林上轨：价格压力位",     "action": "触及减仓"}
            if "下轨" in label:
                return {"level": "pos",    "meaning": "布林下轨：价格支撑位",     "action": "触及可关注"}
            if "中轨" in label:
                return {"level": "neutral","meaning": "布林中轨：强弱分水岭",     "action": "站稳中轨偏多"}
        # 5) 形态
        if label == "形态":
            v = str(value)
            if v == "金叉":
                return {"level": "pos",    "meaning": "MACD 金叉，买入信号",      "action": "可跟进"}
            if v == "死叉":
                return {"level": "neg",    "meaning": "MACD 死叉，卖出信号",      "action": "建议减仓"}
            if "箱体" in v or "震荡" in v:
                return {"level": "neutral","meaning": "箱体震荡，区间操作",        "action": "高抛低吸"}
            if v in ("上升", "多头排列", "上升趋势"):
                return {"level": "pos",    "meaning": "上升趋势/多头排列",        "action": "可继续持有"}
            if v in ("下降", "空头排列", "下降趋势"):
                return {"level": "neg",    "meaning": "下降趋势/空头排列",        "action": "减仓或止损"}
            return {"level": "neutral",    "meaning": f"形态：{v}",                "action": "观察后续"}
        # 6) 形态置信度
        if "置信度" in label:
            try:
                pct = float(str(value).rstrip("%"))
            except (ValueError, TypeError):
                pct = 50
            if pct >= 75:
                return {"level": "pos",      "meaning": f"形态置信度 {pct}%，信号强",     "action": "可作为决策依据"}
            if pct >= 55:
                return {"level": "neutral",  "meaning": f"形态置信度 {pct}%，信号中等",   "action": "结合其他指标"}
            return {"level": "neg",         "meaning": f"形态置信度 {pct}%，信号弱",     "action": "仅作参考"}
        # 7) 缠论
        if "缠论" in label or "中枢" in label:
            return {"level": "neutral", "meaning": f"缠论结构：{value}（中枢震荡/趋势判别）", "action": "关注中枢突破方向"}
        # 8) 趋势
        if "趋势" in label:
            v = str(value)
            if v == "上升":
                return {"level": "pos",     "meaning": "均线多头排列，上升趋势",  "action": "可继续持有"}
            if v == "下降":
                return {"level": "neg",     "meaning": "均线空头排列，下降趋势",  "action": "减仓或止损"}
            return {"level": "neutral",     "meaning": "均线粘合，横盘整理",      "action": "等待方向"}
        # 9) 量能
        if "量能" in label:
            v = str(value)
            if "放量" in v:
                return {"level": "pos",     "meaning": "成交量明显放大",          "action": "关注方向选择"}
            if "缩量" in v:
                return {"level": "neg",     "meaning": "成交量萎缩",              "action": "动能不足，谨慎"}
            return {"level": "neutral",     "meaning": "量能平稳",                "action": "震荡格局"}
    except Exception:
        pass
    # fallback
    return {"level": "neutral", "meaning": f"指标 {label} = {value}", "action": "—"}
