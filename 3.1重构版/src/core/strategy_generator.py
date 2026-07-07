from typing import Any


_WEIGHT_MATRIX = {
    "consolidation": {"ultra": 0.10, "short": 0.25, "mid": 0.35, "long": 0.30},
    "bull": {"ultra": 0.25, "short": 0.35, "mid": 0.25, "long": 0.15},
    "bear": {"ultra": 0.05, "short": 0.15, "mid": 0.30, "long": 0.50},
}

_DECISION_THRESHOLDS = [
    (1.5, "加仓/重仓持有", "多周期共振看多"),
    (0.5, "持有观望", "信号偏多但不强烈"),
    (-0.5, "减仓/轻仓", "多周期方向不一致"),
    (-999, "卖出/清仓", "多周期共振看空"),
]

_CYCLE_INDICATORS = {
    "ultra": ["rsi", "atr", "volume_ratio", "ma_trend", "macd_signal"],
    "short": ["rsi", "macd_signal", "kdj", "ma_trend", "volume_ratio"],
    "mid": ["ma_trend", "macd_signal", "kdj", "rsi"],
    "long": ["fundamental", "sentiment", "rsi"],
}


class StrategyGenerator:
    def __init__(self, scores: dict, technical: dict, fundamental: dict,
                 sentiment: dict, quote: dict, price_info: dict = None,
                 chanlun: dict = None):
        self.scores = scores
        self.tech = technical
        self.fund = fundamental
        self.sent = sentiment
        self.quote = quote or {}
        self.price_info = price_info or {}
        self.chanlun = chanlun or {}
        self._price = getattr(quote, 'price', None) or (price_info.get('current_price') if isinstance(price_info, dict) else 0) or 0
        self._change_pct = getattr(quote, 'change_pct', None) or 0

    def generate(self) -> dict:
        market_state = self._detect_market_state()
        weights = _WEIGHT_MATRIX[market_state]

        s_ultra = self._score_ultra_short()
        s_short = self._score_short()
        s_mid = self._score_mid()
        s_long = self._score_long()
        s_chanlun = self._score_chanlun()

        composite = (
            weights["ultra"] * s_ultra +
            weights["short"] * s_short +
            weights["mid"] * s_mid +
            weights["long"] * s_long +
            0.1 * s_chanlun
        )

        decision = self._composite_decision(composite)

        return {
            "cycles": {
                "ultra_short": self._cycle_label(s_ultra, "超短期"),
                "short": self._cycle_label(s_short, "短期"),
                "mid": self._cycle_label(s_mid, "中期"),
                "long": self._cycle_label(s_long, "长期"),
            },
            "market_state": market_state,
            "weights": weights,
            "composite_score": round(composite, 2),
            "decision": decision,
            "current_advice": self._generate_current_advice(s_short, s_mid, s_long),
            "target_and_stop": self._generate_target_and_stop(composite),
            "batch_operation": self._generate_batch_operation(composite),
            "time_cycle": self._generate_time_cycle(composite),
            "chanlun": {
                "score": round(s_chanlun, 2),
                "current_trend": self.chanlun.get('current_trend', 'N/A'),
                "trend_strength": self.chanlun.get('trend_strength', 'N/A'),
                "summary": self.chanlun.get('summary', ''),
                "buy_points": self.chanlun.get('buy_sell_points', {}).get('buy_points', []),
                "sell_points": self.chanlun.get('buy_sell_points', {}).get('sell_points', []),
                "operation_advice": self.chanlun.get('buy_sell_points', {}).get('operation_advice', ''),
            },
        }

    def _detect_market_state(self) -> str:
        change = self._change_pct
        rsi = self.tech.get("rsi", 50)
        ma_trend = self.tech.get("ma_trend", "震荡整理")
        vol_ratio = self.tech.get("volume_ratio", 1)

        if change > 3 or ma_trend == "多头排列":
            return "bull"
        elif change < -3 or ma_trend == "空头排列":
            return "bear"
        return "consolidation"

    def _score_ultra_short(self) -> float:
        price = self._price
        rsi = self.tech.get("rsi", 50)
        atr = self.tech.get("atr", price * 0.02 if price else 0.3)
        vol_ratio = self.tech.get("volume_ratio", 1)
        ma_trend = self.tech.get("ma_trend", "震荡整理")
        macd_sig = self.tech.get("macd_signal", "")
        kdj = self.tech.get("kdj", {}) or {}
        k_val = kdj.get("k", 50) if isinstance(kdj, dict) else 50

        score = 0.0

        if rsi > 70:
            score -= 0.5
        elif rsi < 30:
            score += 0.5
        elif 45 <= rsi <= 55:
            score += 0.2

        if atr > 0 and price > 0:
            daily_range_pct = (atr / price) * 100
            if daily_range_pct > 3:
                score += 0.3
            elif daily_range_pct < 1:
                score -= 0.1

        if vol_ratio > 1.5:
            score += 0.3
        elif vol_ratio < 0.5:
            score -= 0.2

        if ma_trend == "多头排列":
            score += 0.5
        elif ma_trend == "空头排列":
            score -= 0.5

        if "金叉" in macd_sig:
            score += 0.4
        elif "死叉" in macd_sig:
            score -= 0.4

        if k_val < 20:
            score += 0.4
        elif k_val > 80:
            score -= 0.4

        return max(-2.0, min(2.0, score))

    def _score_short(self) -> float:
        rsi = self.tech.get("rsi", 50)
        macd_sig = self.tech.get("macd_signal", "")
        kdj = self.tech.get("kdj", {}) or {}
        k_val = kdj.get("k", 50) if isinstance(kdj, dict) else 50
        d_val = kdj.get("d", 50) if isinstance(kdj, dict) else 50
        ma_trend = self.tech.get("ma_trend", "震荡整理")
        vol_ratio = self.tech.get("volume_ratio", 1)
        macd_hist = self.tech.get("macd_histogram", 0)
        obv_sig = self.tech.get("obv_signal", "")

        score = 0.0

        if rsi < 30:
            score += 0.5
        elif rsi > 70:
            score -= 0.3
        elif 35 <= rsi <= 45:
            score += 0.2

        if "金叉" in macd_sig:
            score += 0.5
            if macd_hist > 0:
                score += 0.2
        elif "死叉" in macd_sig:
            score -= 0.5
            if macd_hist < 0:
                score -= 0.2

        if k_val < 20 and d_val < 20:
            score += 0.5
        elif k_val > 80 and d_val > 80:
            score -= 0.3

        if ma_trend == "多头排列":
            score += 0.6
        elif ma_trend == "空头排列":
            score -= 0.6

        if obv_sig == "底背离":
            score += 0.5
        elif obv_sig == "顶背离":
            score -= 0.5

        if vol_ratio > 1.5:
            score += 0.2

        return max(-2.0, min(2.0, score))

    def _score_mid(self) -> float:
        ma_trend = self.tech.get("ma_trend", "震荡整理")
        rsi = self.tech.get("rsi", 50)
        macd_sig = self.tech.get("macd_signal", "")
        kdj = self.tech.get("kdj", {}) or {}
        k_val = kdj.get("k", 50) if isinstance(kdj, dict) else 50
        d_val = kdj.get("d", 50) if isinstance(kdj, dict) else 50

        score = 0.0

        if ma_trend == "多头排列":
            score += 0.8
        elif ma_trend == "空头排列":
            score -= 0.8

        if "金叉" in macd_sig:
            score += 0.4
        elif "死叉" in macd_sig:
            score -= 0.4

        if k_val > 80 and d_val > 80:
            score -= 0.3
        elif k_val < 30 and d_val < 30:
            score += 0.3

        if rsi > 70:
            score -= 0.2
        elif rsi < 40:
            score += 0.2

        fin = self.fund.get("financial_indicators", {}) or {}
        if isinstance(fin, dict):
            roe = fin.get("净资产收益率") or fin.get("净资产收益率(ROE)", 0)
            if isinstance(roe, (int, float)) and roe > 15:
                score += 0.3
            elif isinstance(roe, (int, float)) and roe < 5:
                score -= 0.3

        return max(-2.0, min(2.0, score))

    def _score_long(self) -> float:
        score = 0.0

        fin = self.fund.get("financial_indicators", {}) or {}
        if isinstance(fin, dict):
            roe = fin.get("净资产收益率") or fin.get("净资产收益率(ROE)", 0)
            pe = fin.get("市盈率", 0)
            pb = fin.get("市净率", 0)
            rev_growth = fin.get("营收同比增长率", 0)
            profit_growth = fin.get("净利润同比增长率", 0)
            div_yield = fin.get("股息收益率") or fin.get("股息率", 0)
            peg = fin.get("PEG比率", 0)
            op_cf = fin.get("每股经营现金流", 0)

            if isinstance(roe, (int, float)):
                if roe > 20:
                    score += 0.6
                elif roe > 15:
                    score += 0.3
                elif roe > 10:
                    score += 0.0
                else:
                    score -= 0.4

            if isinstance(pe, (int, float)) and pe > 0:
                if pe < 15:
                    score += 0.3
                elif pe > 50:
                    score -= 0.5

            if isinstance(pb, (int, float)) and pb > 0:
                if pb < 1.5:
                    score += 0.2
                elif pb > 5:
                    score -= 0.3

            if isinstance(peg, (int, float)) and peg > 0:
                if peg < 0.8:
                    score += 0.4
                elif peg < 1.0:
                    score += 0.2
                elif peg > 2.5:
                    score -= 0.4

            if isinstance(op_cf, (int, float)) and isinstance(roe, (int, float)) and roe > 0 and op_cf > 0:
                fcf_rate = (op_cf / (roe / 100)) if roe != 0 else 0
                if fcf_rate > 1.0:
                    score += 0.3
                elif fcf_rate < 0:
                    score -= 0.3

            if isinstance(rev_growth, (int, float)):
                if rev_growth > 20:
                    score += 0.3
                elif rev_growth < 0:
                    score -= 0.3

            if isinstance(profit_growth, (int, float)):
                if profit_growth > 20:
                    score += 0.2
                elif profit_growth < -10:
                    score -= 0.3

            if isinstance(div_yield, (int, float)) and div_yield > 3:
                score += 0.3

        sent_score = self.scores.get("sentiment_score", 50)
        if sent_score >= 65:
            score += 0.3
        elif sent_score <= 35:
            score -= 0.3

        return max(-2.0, min(2.0, score))

    def _score_chanlun(self) -> float:
        """Score based on 缠论 analysis (-2.0 to 2.0)"""
        if not self.chanlun.get('available'):
            return 0.0

        score = self.chanlun.get('chanlun_score', 0.0)

        # 背驰加分/减分
        beichi_list = self.chanlun.get('beichi_list', [])
        for bc in beichi_list:
            if bc['type'] == '底背驰':
                score += 0.4
            elif bc['type'] == '顶背驰':
                score -= 0.4

        # 三类买卖点加成
        bs = self.chanlun.get('buy_sell_points', {})
        if bs.get('buy_points'):
            score += 0.3
        if bs.get('sell_points'):
            score -= 0.3

        return max(-2.0, min(2.0, score))

    def _cycle_label(self, score: float, label: str) -> dict:
        if score >= 1.0:
            signal = "强烈看多"
        elif score >= 0.3:
            signal = "偏多"
        elif score > -0.3:
            signal = "中性"
        elif score >= -1.0:
            signal = "偏空"
        else:
            signal = "强烈看空"
        return {"score": round(score, 2), "signal": signal, "label": label}

    def _composite_decision(self, composite: float) -> dict:
        label_map = {
            "加仓/重仓持有": ("多周期共振看多", "#6fcf97"),
            "持有观望": ("信号偏多但不强烈", "#ffd93d"),
            "减仓/轻仓": ("多周期方向不一致", "#f57c00"),
            "卖出/清仓": ("多周期共振看空", "#eb5757"),
        }
        for threshold, action, reason in _DECISION_THRESHOLDS:
            if composite >= threshold:
                desc, color = label_map[action]
                return {"action": action, "reason": reason, "color": color}
        return {"action": "持有观望", "reason": "信号偏多但不强烈", "color": "#ffd93d"}

    def _generate_current_advice(self, s_short: float, s_mid: float, s_long: float) -> dict:
        composite = self._weighted_composite()
        rsi = self.tech.get("rsi", 50)
        ma_trend = self.tech.get("ma_trend", "震荡整理")
        change = self._change_pct
        market_state = self._detect_market_state()

        if composite >= 1.5:
            short = "多周期共振看多，建议分批建仓或加仓，短线顺势持有"
            mid = "中期趋势向好，基本面支撑强劲，持有为主"
        elif composite >= 0.5:
            short = "综合评分偏多，短线可持有或逢低加仓，注意RSI是否超买"
            mid = "中期方向偏多，等待技术回调确认后可加仓"
        elif composite >= -0.5:
            short = "信号不强烈，短线控制仓位，等趋势明朗再操作"
            mid = "中期趋势不明朗，减少操作频率，等待数据确认"
        else:
            short = "多周期偏空，短线降低仓位或清仓，不逆势加仓"
            mid = "中期趋势较弱，基本面若无改善建议保持谨慎"

        if change > 5 and rsi > 65:
            short = f"股价高位({change:+.1f}%)+RSI={rsi:.0f}超买，短线追涨需谨慎，{short}"
        elif change > 8:
            short = f"短期涨幅较大({change:+.1f}%)，注意锁定收益，{short}"
        elif change < -5 and rsi < 35:
            short = f"股价低位({change:+.1f}%)+RSI={rsi:.0f}超卖，超跌反弹可小仓试探，{short}"

        # 缠论趋势补充
        chanlun_trend = self.chanlun.get('current_trend', '')
        if chanlun_trend:
            short = f"{short} | 缠论:{chanlun_trend}"

        return {"short_term": short, "mid_term": mid}

    def _weighted_composite(self) -> float:
        market_state = self._detect_market_state()
        weights = _WEIGHT_MATRIX[market_state]
        s_ultra = self._score_ultra_short()
        s_short = self._score_short()
        s_mid = self._score_mid()
        s_long = self._score_long()
        return weights["ultra"] * s_ultra + weights["short"] * s_short + weights["mid"] * s_mid + weights["long"] * s_long

    def _generate_target_and_stop(self, composite: float) -> dict:
        price = self._price
        change = self._change_pct
        atr = self.tech.get("atr") or (price * 0.02 if price else 0)

        if price <= 0:
            return {"support": "暂无价格数据", "target": "暂无价格数据", "stop_loss": "暂无价格数据"}

        stop_distance = max(atr * 2, price * 0.03)
        stop_loss_price = price - stop_distance
        stop_loss_pct = (stop_distance / price) * 100
        target_distance = stop_distance * 2
        target_low = price + target_distance
        target_high = price + target_distance * 1.2
        support_price = price * 0.95

        if composite >= 1.5:
            target = f"{target_low:.2f}～{target_high:.2f}元（技术突破后分批止盈）"
        elif composite >= 0.5:
            target = f"{target_low:.2f}～{target_high:.2f}元（结合压力位分批离场）"
        elif composite >= -0.5:
            target = f"{target_low:.2f}元附近（注意上方压力）"
        else:
            target = "趋势偏空，不设目标价，以止损为参考"

        if change < 0:
            support = f"短期支撑：{support_price:.2f}元（跌幅{abs(change):.1f}%，注意是否破位）"
        else:
            support = f"关键支撑：{support_price:.2f}元，若跌破考虑减仓"

        if stop_loss_pct > 5:
            stop_loss = f"止损位：{stop_loss_price:.2f}元（{stop_loss_pct:.1f}%空间），跌破果断离场"
        else:
            stop_loss = f"止损位：{stop_loss_price:.2f}元（{stop_loss_pct:.1f}%空间）"

        return {"support": support, "target": target, "stop_loss": stop_loss}

    def _generate_batch_operation(self, composite: float) -> dict:
        rsi = self.tech.get("rsi", 50)
        if composite >= 1.5:
            lines = [
                "• 首仓：当前价格建立20%仓位，试单确认方向",
                "• 加仓1：技术回调至5日线不破，加仓20%",
                "• 加仓2：回调至10日线或RSI<40确认支撑，加仓20%",
                "• 满仓：放量突破前高或压力位确认，加仓至40%上限",
                "• 止盈：分3批，每涨5-8%了结一部分",
            ]
        elif composite >= 0.5:
            lines = [
                "• 首仓：当前价格建立15%仓位，试单为主",
                "• 加仓：技术回踩5日线企稳后加仓15%，最多不超过30%",
                "• 止损：总浮亏超5%坚决离场，不扛单",
                "• 止盈：目标价附近分批了结，不贪最后一波",
            ]
        elif composite >= -0.5:
            lines = [
                "• 首仓：轻仓试探10%，严格止损",
                "• 确认：若RSI从超卖区反弹且站稳5日线，再加仓10%",
                "• 上限：最大仓位不超过20%，趋势不确认前不重仓",
                "• 关键：跌破支撑位直接减仓，不犹豫",
            ]
        else:
            lines = [
                "• 建议0-10%轻仓观望，不追加",
                "• 若想操作：超跌反弹RSI<35时小仓5%介入，快进快出",
                "• 原则：亏损绝不加仓摊平，及时止损",
            ]

        # 缠论操作建议
        if self.chanlun.get('available'):
            operation = self.chanlun.get('buy_sell_points', {}).get('operation_advice', '')
            if operation:
                lines.append(f"• 缠论信号: {operation}")

        return '\n'.join(lines)

    def _generate_time_cycle(self, composite: float) -> dict:
        market_state = self._detect_market_state()
        if composite >= 1.5:
            short, mid, long_ = "1-5个交易日确认突破有效性", "1-3个月中期行情", "3个月以上"
            horizon = "中短期为主（1周-3个月）"
        elif composite >= 0.5:
            short, mid, long_ = "1-5个交易日短线操作", "2-8周波段操作", "若季报超预期可延长"
            horizon = "短期波段（1-4周）"
        elif composite >= -0.5:
            short, mid, long_ = "1-3个交易日快进快出", "2-4周观察趋势", "等待数据确认后再评估"
            horizon = "超短期至短期（1天-2周）"
        else:
            short, mid, long_ = "日内可考虑平仓离场", "中期偏空等超跌后评估", "长期需等环境转好"
            horizon = "防守期（1个月内）"
        return {"short": short, "mid": mid, "long": long_, "horizon": horizon}
