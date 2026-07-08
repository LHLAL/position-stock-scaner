"""股票分析引擎模块

封装股票分析逻辑，调用数据源获取行情数据，进行技术面/基本面/情绪面分析
"""
from __future__ import annotations
from datetime import datetime, timedelta
import re
import time
import pandas as pd
import numpy as np
import logging
from typing import Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from src.repository.stock_repo import stock_repo
from src.core.strategy_generator import StrategyGenerator
from src.core.chanlun import analyze_chanlun
from src.core import indicators as ind  # v1.3: 拆分技术指标纯函数


logger = logging.getLogger(__name__)


class StockAnalyzer:

    def __init__(self, registry=None):
        self._clear_proxy()

        self.weights = {
            'technical': 0.4,
            'fundamental': 0.4,
            'sentiment': 0.2
        }

    @staticmethod
    def _clear_proxy():
        """清除代理设置，避免akshare走代理连不上"""
        import os
        for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
            os.environ.pop(key, None)
        os.environ['no_proxy'] = '*'
        os.environ['NO_PROXY'] = '*' 

    @staticmethod
    def normalize_stock_code(code: str) -> tuple:
        """标准化股票代码，返回 (normalized_code, market, display_code)。

        v1.3: 仅支持 A 股（SH/SZ），港美股已停支持。
        """
        c = code.strip().upper()
        if c.startswith('SH') or c.startswith('SZ'):
            market = c[:2]
            raw = c[2:]
            return (raw, market, c)
        if '.SS' in c or '.SH' in c or '.SZ' in c:
            parts = c.split('.')
            market = 'SH' if parts[1] in ('SS', 'SH') else 'SZ'
            return (parts[0], market, c)
        if re.match(r'^6\d{5}$', c):
            return (c, 'SH', c)
        if re.match(r'^(0|3)\d{5}$', c):
            return (c, 'SZ', c)
        # 非 6 位 A 股数字代码 → 拒绝（v1.3 不再 fallback 为 HK/US）
        return (c, 'SH', c)


    def get_stock_name(self, code: str) -> str:
        # v1.3: \u8d70 stock_repo\uff08SQLite \u4f18\u5148\uff09\uff0c\u4e0d\u518d import akshare
        from src.repository.stock_repo import stock_repo
        code_norm, _, _ = self.normalize_stock_code(code)
        return stock_repo.get_name(code_norm)

    def get_stock_data(self, code: str, market: str = "SH", days: int = 365):
        """获取历史K线数据 —— v1.3: 走 stock_repo（SQLite 优先），miss 走 akshare 兜底"""
        from src.repository.stock_repo import stock_repo
        code_norm, _, _ = self.normalize_stock_code(code)
        df = stock_repo.get_history(code_norm, days)
        if df is None or df.empty:
            return pd.DataFrame()
        # 兼容旧调用方：统一返回中文列名
        rename_map = {
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量',
        }
        df = df.rename(columns=rename_map)
        # 确保列顺序
        for col in ['日期', '开盘', '收盘', '最高', '最低', '成交量']:
            if col not in df.columns:
                df[col] = 0
        return df[['日期', '开盘', '收盘', '最高', '最低', '成交量']]

    def get_minute_data(self, code: str, market: str = "SH", period: str = "5") -> pd.DataFrame:
        # v1.3: 走 stock_repo（data/sina_kline 下沉）
        from src.repository.stock_repo import stock_repo
        df = stock_repo.get_minute_kline(code, market, period)
        if df is None or df.empty:
            return pd.DataFrame()
        # 兼容旧调用方：返回中文列名
        rename_map = {
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量',
        }
        df = df.rename(columns=rename_map)
        for col in ['日期', '开盘', '收盘', '最高', '最低', '成交量']:
            if col not in df.columns:
                df[col] = 0
        return df[['日期', '开盘', '收盘', '最高', '最低', '成交量']]

    def get_price_info(self, price_data) -> dict:
        """从历史数据提取价格信息"""
        if price_data.empty:
            return {}
        last = price_data.iloc[-1]
        close = float(last.get('\u6536\u76d8', 0))
        open_p = float(last.get('\u5f00\u76d8', 0))
        high = float(last.get('\u6700\u9ad8', 0))
        low = float(last.get('\u6700\u4f4e', 0))
        volume = int(last.get('\u6210\u4ea4\u91cf', 0))
        change_pct = ((close - open_p) / open_p * 100) if open_p else 0
        if len(price_data) > 1:
            prev_close = float(price_data.iloc[-2].get('\u6536\u76d8', close))
            change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0
        return {
            'current_price': close, 'open': open_p, 'high': high, 'low': low,
            'volume': volume, 'change_percent': round(change_pct, 2),
            'amplitude': round((high-low)/open_p*100 if open_p else 0, 2),
            'turnover': int(last.get('\u6210\u4ea4\u989d', 0)),
        }

    def analyze_stock(self, code: str, market: str = "SH") -> dict[str, Any]:
        timestamp = datetime.now().isoformat()

        price_data = self.get_stock_data(code, market)
        price_info = self.get_price_info(price_data)
        quote = stock_repo.get_quote(code, market)
        stock_name = self.get_stock_name(code)

        technical = self.calculate_technical_indicators(code, market)
        fundamental = self.calculate_fundamental_indicators(code, market)
        sentiment = self._calculate_sentiment(code, market)
        chanlun = analyze_chanlun(price_data)

        technical_score = self._score_technical(technical)
        fundamental_score = self._score_fundamental(fundamental)
        sentiment_score = self._score_sentiment(sentiment)

        comprehensive_score = (
            technical_score * self.weights['technical'] +
            fundamental_score * self.weights['fundamental'] +
            sentiment_score * self.weights['sentiment']
        )

        signals = self.generate_signals(code, market, tech=technical)
        scores_dict = {
            'technical': technical_score,
            'fundamental': fundamental_score,
            'sentiment': sentiment_score,
            'comprehensive': comprehensive_score,
            'chanlun': chanlun.get('chanlun_score', 0.0),
        }

        recommendation, reason = self._generate_recommendation(
            comprehensive_score, technical_score, fundamental_score, sentiment_score
        )
        sg = StrategyGenerator(
            scores={
                'technical_score': technical_score,
                'fundamental_score': fundamental_score,
                'sentiment_score': sentiment_score,
                'comprehensive_score': comprehensive_score,
            },
            technical=technical,
            fundamental=fundamental,
            sentiment=sentiment,
            quote=quote,
            price_info=price_info,
            chanlun=chanlun,
        )
        strategy = sg.generate()

        return {
            "code": code,
            "name": stock_name,
            "market": market,
            "timestamp": timestamp,
            "quote": quote.to_dict() if quote else {},
            "price_info": price_info,
            "technical": technical,
            "fundamental": fundamental,
            "chanlun": chanlun,
            "sentiment": sentiment,
            "signals": signals,
            "scores": {
                "technical_score": round(technical_score, 1),
                "fundamental_score": round(fundamental_score, 1),
                "sentiment_score": round(sentiment_score, 1),
                "comprehensive_score": round(comprehensive_score, 1)
            },
            "recommendation": recommendation,
            "reason": reason,
            "strategy": strategy,
        }

    def calculate_technical_indicators(self, code: str, market: str = "SH") -> dict[str, Any]:
        price_data = self.get_stock_data(code, market)
        if price_data.empty or len(price_data) < 20:
            return self._default_technical()

        closes = price_data['收盘'].values.astype(float)
        highs = price_data['最高'].values.astype(float)
        lows = price_data['最低'].values.astype(float)

        ma5 = self._sma(closes, 5)
        ma10 = self._sma(closes, 10)
        ma20 = self._sma(closes, 20)

        lc = closes[-1]; m5 = ma5[-1]; m10 = ma10[-1]; m20 = ma20[-1]
        if lc > m5 > m10 > m20:
            ma_trend = "多头排列"
        elif lc < m5 < m10 < m20:
            ma_trend = "空头排列"
        else:
            ma_trend = "震荡整理"

        rsi_arr = self._calc_rsi(closes)
        macd_line, signal_line, hist = self._calc_macd(closes)
        cm = macd_line[-1]; cs = signal_line[-1]
        pm = macd_line[-2]; ps = signal_line[-2]
        macd_signal = "横盘整理"
        if pm <= ps and cm > cs:
            macd_signal = "金叉"
        elif pm >= ps and cm < cs:
            macd_signal = "死叉"

        k_val, d_val, j_val = self._calc_kdj(highs, lows, closes)
        bb_pos = self._calc_bollinger_position(closes, ma20)

        volumes = price_data['成交量'].values.astype(float)
        avg_vol = np.mean(volumes[-20:])
        cur_vol = volumes[-1]
        vol_ratio = cur_vol / avg_vol if avg_vol else 1.0
        vol_status = "放量" if vol_ratio > 1.5 else ("缩量" if vol_ratio < 0.5 else "量能平稳")

        vr = self._calc_vr(closes, volumes)
        cci = self._calc_cci(highs, lows, closes)
        atr = self._calc_atr(highs, lows, closes)
        obv = self._calc_obv(closes, volumes)

        # MyTT 扩展指标（取最近 180 天，快速 numpy 实现）
        _mytt_values = {}
        try:
            _n = min(len(closes), 180)
            _c = closes[-_n:]; _h = highs[-_n:]; _l = lows[-_n:]
            _mytt_values = _compute_mytt_fast(_c, _h, _l)
        except Exception as e:
            import logging as _lg; _lg.getLogger(__name__).warning(f"MyTT 扩展指标计算失败: {e}")

        result = {
            "price": round(float(closes[-1]), 2),
            "change_pct": round(float((closes[-1] - closes[-2]) / closes[-2] * 100), 2) if len(closes) > 1 else 0,
            "volume": int(cur_vol),
            "ma5": round(float(m5), 2), "ma10": round(float(m10), 2), "ma20": round(float(m20), 2),
            "ma_trend": ma_trend,
            "rsi": round(float(rsi_arr[-1]), 2),
            "macd_line": round(float(cm), 4), "macd_signal_line": round(float(cs), 4),
            "macd_histogram": round(float(hist[-1]), 4), "macd_signal": macd_signal,
            "kdj": {"k": round(k_val, 2), "d": round(d_val, 2), "j": round(j_val, 2)},
            "bollinger_position": round(bb_pos, 2),
            "volume_ratio": round(vol_ratio, 2), "volume_status": vol_status,
            "vr": round(vr, 2), "cci": round(cci, 2), "atr": round(atr, 4),
            "obv": round(obv, 2),
            "obv_signal": self._calc_obv_signal(closes, volumes),
            "price_data_dates": len(price_data),
        }
        result.update(_mytt_values)

        min_data = self.get_minute_data(code, market, "5")
        if not min_data.empty and len(min_data) >= 20:
            mc = min_data['收盘'].values.astype(float)
            mh = min_data['最高'].values.astype(float)
            ml = min_data['最低'].values.astype(float)
            mv = min_data['成交量'].values.astype(float)

            m_rsi = self._calc_rsi(mc)
            m_k, m_d, m_j = self._calc_kdj(mh, ml, mc)
            m_macd_line, m_signal, m_hist = self._calc_macd(mc)
            m_atr = self._calc_atr(mh, ml, mc)

            result["intraday"] = {
                "period": "5min",
                "data_points": len(min_data),
                "rsi": round(float(m_rsi[-1]), 2),
                "kdj_k": round(float(m_k), 2),
                "kdj_d": round(float(m_d), 2),
                "kdj_j": round(float(m_j), 2),
                "macd_histogram": round(float(m_hist[-1]), 4),
                "atr": round(float(m_atr), 4),
            }

        return result

    def calculate_fundamental_indicators(self, code: str, market: str = "SH") -> dict[str, Any]:
        # v1.3: 拆分到 core/fundamental.py
        from src.core import fundamental
        return fundamental.calculate(code, market)

    def _default_fundamental(self) -> dict:
        from src.core import fundamental
        return fundamental.default_result()

    def generate_signals(self, code: str, market: str = "SH", tech: dict = None) -> list[dict[str, str]]:
        tech = tech if tech is not None else self.calculate_technical_indicators(code, market)
        signals = []
        change_pct = tech.get('change_pct', 0)
        if change_pct > 5:
            signals.append({"type": "涨幅较大", "signal": "sell", "description": f"涨幅 {change_pct:.2f}%，注意回调风险"})
        elif change_pct < -5:
            signals.append({"type": "跌幅较大", "signal": "buy", "description": f"跌幅 {change_pct:.2f}%，关注反弹机会"})

        rsi_val = tech.get('rsi', 50)
        if rsi_val is not None and rsi_val < 30:
            signals.append({"type": "RSI超卖", "signal": "buy", "description": f"RSI={rsi_val:.1f}，超卖状态"})
        elif rsi_val is not None and rsi_val > 70:
            signals.append({"type": "RSI超买", "signal": "sell", "description": f"RSI={rsi_val:.1f}，超买状态"})

        macd_sig = tech.get('macd_signal', '')
        if '金叉' in macd_sig:
            signals.append({"type": "MACD金叉", "signal": "buy", "description": "MACD金叉，上涨信号"})
        elif '死叉' in macd_sig:
            signals.append({"type": "MACD死叉", "signal": "sell", "description": "MACD死叉，下跌信号"})

        vol_ratio = tech.get('volume_ratio', 1)
        if vol_ratio > 2:
            signals.append({"type": "成交量放大", "signal": "neutral", "description": f"量比={vol_ratio:.2f}，明显放量"})

        bb_pos = tech.get('bollinger_position', 0.5)
        if bb_pos > 0.9:
            signals.append({"type": "布林带上轨", "signal": "sell", "description": "价格触及布林带上轨"})
        elif bb_pos < 0.1:
            signals.append({"type": "布林带下轨", "signal": "buy", "description": "价格触及布林带下轨"})

        if not signals:
            signals.append({"type": "无明显信号", "signal": "neutral", "description": "当前无明显交易信号"})
        return signals

    def _default_technical(self) -> dict[str, Any]:
        return ind.default_technical()

    @staticmethod
    def _sma(data, window):
        return ind.sma(data, window)

    @staticmethod
    def _ema(data, window):
        return ind.ema(data, window)

    @staticmethod
    def _calc_rsi(closes, period=14):
        return ind.calc_rsi(closes, period)

    @staticmethod
    def _calc_macd(closes, fast=12, slow=26, signal=9):
        return ind.calc_macd(closes, fast, slow, signal)

    @staticmethod
    def _calc_kdj(highs, lows, closes, period=9):
        return ind.calc_kdj(highs, lows, closes, period)

    @staticmethod
    def _calc_bollinger_position(closes, ma20, std_mult=2):
        return ind.calc_bollinger_position(closes, ma20, std_mult)

    @staticmethod
    def _calc_vr(closes, volumes, period=26):
        return ind.calc_vr(closes, volumes, period)

    @staticmethod
    def _calc_cci(highs, lows, closes, period=20):
        return ind.calc_cci(highs, lows, closes, period)

    @staticmethod
    def _calc_obv(closes, volumes):
        return ind.calc_obv(closes, volumes)

    @staticmethod
    def _calc_obv_signal(closes, volumes, period=20):
        return ind.calc_obv_signal(closes, volumes, period)

    @staticmethod
    def _calc_atr(highs, lows, closes, period=14):
        return ind.calc_atr(highs, lows, closes, period)

    @staticmethod
    def _calc_adx(highs, lows, closes, period=14):
        return ind.calc_adx(highs, lows, closes, period)

    @staticmethod
    def _calc_cmf(closes, highs, lows, volumes, period=20):
        return ind.calc_cmf(closes, highs, lows, volumes, period)

    @staticmethod
    def _calc_williams_r(highs, lows, closes, period=14):
        return ind.calc_williams_r(highs, lows, closes, period)

    def _judge_ma_trend(self, price: float, ma5: float, ma10: float, ma20: float) -> str:
        return ind.judge_ma_trend(price, ma5, ma10, ma20)

    def _judge_volume(self, volume: int, avg_volume: int) -> str:
        return ind.judge_volume(volume, avg_volume)

    @staticmethod
    def _calc_ma_biass(closes, period=5):
        return ind.calc_ma_biass(closes, period)

    @staticmethod
    def _calc_histogram_slope(histogram, n=5):
        return ind.calc_histogram_slope(histogram, n)

    def _calculate_sentiment(self, code: str, market: str) -> dict[str, Any]:
        """计算市场情绪（基于财联社新闻）"""
        try:
            news_agg = stock_repo.get_news_aggregator()

            # 获取股票名称和板块信息
            stock_name = self.get_stock_name(code)
            sector = ""

            # 获取个股相关新闻（匹配代码、名称、板块）
            stock_news = news_agg.get_stock_news(code, stock_name, sector, max_items=30)

            # 获取市场整体情绪（大盘热点新闻）
            market_news = news_agg.get_market_news(max_items=30)

            # 合并：个股新闻权重更高
            news_list = stock_news + market_news

            if not news_list:
                return {
                    "overall_sentiment": 0.0,
                    "sentiment_trend": "相对中性",
                    "confidence_score": 0.3,
                    "total_analyzed": 0,
                    "positive_ratio": 0.5,
                    "negative_ratio": 0.5,
                    "key_points": [],
                    "risk_points": [],
                    "opportunity_points": [],
                    "catalysts": [],
                    "news_sources": []
                }

            # 简单情绪分析：统计正负面关键词
            positive_keywords = ['涨', '利好', '突破', '增长', '创新高', '业绩', '盈利', '增长', '看多', '买入', '推荐', '景气', '复苏', '爆发']
            negative_keywords = ['跌', '利空', '风险', '亏损', '预警', '减持', '泡沫', '压力', '看空', '卖出', '警告', '低迷', '衰退']

            positive_count = 0
            negative_count = 0
            key_points = []

            for news in news_list[:30]:
                title = news.get('title', '')
                for kw in positive_keywords:
                    if kw in title:
                        positive_count += 1
                        key_points.append(f"【利好】{title[:30]}...")
                        break
                for kw in negative_keywords:
                    if kw in title:
                        negative_count += 1
                        key_points.append(f"【利空】{title[:30]}...")
                        break

            total = positive_count + negative_count
            if total > 0:
                positive_ratio = positive_count / total
                negative_ratio = negative_count / total
            else:
                positive_ratio = 0.5
                negative_ratio = 0.5

            # 计算整体情绪分 (-1 到 1)
            overall_sentiment = (positive_ratio - negative_ratio)

            # 判断情绪趋势
            if overall_sentiment > 0.3:
                sentiment_trend = "偏正面"
            elif overall_sentiment < -0.3:
                sentiment_trend = "偏负面"
            else:
                sentiment_trend = "相对中性"

            # 置信度：基于新闻数量
            confidence_score = min(0.9, 0.3 + len(news_list) * 0.01)

            return {
                "overall_sentiment": overall_sentiment,
                "sentiment_trend": sentiment_trend,
                "confidence_score": confidence_score,
                "total_analyzed": len(news_list),
                "positive_ratio": positive_ratio,
                "negative_ratio": negative_ratio,
                "key_points": key_points[:5],
                "risk_points": [],
                "opportunity_points": [],
                "catalysts": [],
                "news_sources": [s.name for s in news_agg.sources if news_agg.health_check().get(s.name)]
            }
        except Exception as e:
            logger.warning(f"情绪分析失败: {e}")
            return {
                "overall_sentiment": 0.0,
                "sentiment_trend": "相对中性",
                "confidence_score": 0.3,
                "total_analyzed": 0,
                "positive_ratio": 0.5,
                "negative_ratio": 0.5,
                "key_points": [],
                "risk_points": [],
                "opportunity_points": [],
                "catalysts": []
            }

    def _score_technical(self, technical: dict[str, Any]) -> float:
        score = 50.0

        ma_trend = technical.get("ma_trend", "震荡整理")
        if ma_trend == "多头排列":
            score += 20
        elif ma_trend == "空头排列":
            score -= 20

        rsi = technical.get("rsi", 50.0)
        if 30 <= rsi <= 70:
            score += 10
        elif rsi < 30:
            score += 5
        elif rsi > 70:
            score -= 5

        macd = technical.get("macd_signal", "横盘整理")
        if "金叉" in macd:
            score += 15
        elif "死叉" in macd:
            score -= 15

        vol_status = technical.get("volume_status", "量能平稳")
        vol_ratio = technical.get("volume_ratio", 1)
        change_pct = technical.get("change_pct", 0)
        if "放量" in vol_status and change_pct > 0:
            score += 10
        elif "放量" in vol_status and change_pct < 0:
            score -= 10

        return max(0.0, min(100.0, score))

    def _score_fundamental(self, fundamental: dict[str, Any]) -> float:
        score = 50.0

        indicators = fundamental.get("financial_indicators", {})
        if fundamental.get("data_unavailable"):
            return score

        if len(indicators) >= 15:
            score += 20

            roe = indicators.get("净资产收益率", 0)
            if roe > 15:
                score += 10
            elif roe > 10:
                score += 5
            elif roe < 5:
                score -= 5

            debt_ratio = indicators.get("资产负债率", 50)
            if debt_ratio < 30:
                score += 5
            elif debt_ratio > 70:
                score -= 10

            revenue_growth = indicators.get("营收同比增长率", 0)
            if revenue_growth > 20:
                score += 10
            elif revenue_growth > 10:
                score += 5
            elif revenue_growth < -10:
                score -= 10

        return max(0.0, min(100.0, score))

    def _score_sentiment(self, sentiment: dict[str, Any]) -> float:
        overall = sentiment.get("overall_sentiment", 0.0)
        confidence = sentiment.get("confidence_score", 0.5)

        base_score = (overall + 1) * 50
        confidence_adj = confidence * 10

        score = base_score + confidence_adj
        return max(0.0, min(100.0, score))

    def _generate_recommendation(
        self,
        comprehensive: float,
        technical: float,
        fundamental: float,
        sentiment: float
    ) -> tuple[str, str]:
        if comprehensive >= 82 and technical >= 70 and fundamental >= 70:
            return "分批买入", "多项指标表现优异，技术面、基本面、情绪面共振，建议分批建仓"
        elif comprehensive >= 70:
            return "偏多持有", "综合得分较高，整体趋势向好，建议持有或逢低加仓"
        elif comprehensive >= 55 and sentiment >= 50:
            return "轻仓试探", "综合表现良好但有一定不确定性，建议轻仓试探"
        elif comprehensive >= 40:
            return "持有观望", "综合表现一般，建议谨慎持有，等待更好时机"
        elif comprehensive >= 28:
            return "减仓防守", "多项指标转弱，建议减仓控制风险"
        return "回避为主", "综合得分较低，建议回避或减仓至最低仓位"

    def generate_strategy_plan(self, scores: dict, technical=None, sentiment=None, price_info=None) -> str:
        """根据评分生成策略计划"""
        cs = scores.get('comprehensive', 50)
        ts = scores.get('technical', 50)
        fs = scores.get('fundamental', 50)
        ss = scores.get('sentiment', 50)
        
        if cs >= 82:
            return (f"综合评分{cs:.0f}分，各维度表现优异。"
                    f"建议仓位：60-80%。可分批建仓，逢低加仓。"
                    f"止损位：建议设置在近期低点下方3-5%。"
                    f"目标位：结合技术面上方压力位分批止盈。")
        elif cs >= 70:
            return (f"综合评分{cs:.0f}分，整体向好。"
                    f"建议仓位：40-60%。可逢低适当加仓。"
                    f"关注技术面是否持续走强，情绪面是否配合。")
        elif cs >= 55:
            return (f"综合评分{cs:.0f}分，中性偏多。"
                    f"建议仓位：20-40%。轻仓试探，注意风险控制。"
                    f"待趋势明确后再考虑加仓。")
        elif cs >= 40:
            return (f"综合评分{cs:.0f}分，表现一般。"
                    f"建议仓位：10-20%。持有为主，减少操作。"
                    f"关注基本面变化，等待更好时机。")
        elif cs >= 28:
            return (f"综合评分{cs:.0f}分，多项指标偏弱。"
                    f"建议仓位：0-10%。减仓防守，控制风险。"
                    f"不建议在此位置加仓。")
        return (f"综合评分{cs:.0f}分，风险较高。"
                f"建议仓位：0%。回避为主，观望为宜。"
                f"建议寻找其他更优质的投资标的。")



    def calculate_signals_l0123(self, code: str, market: str = "SH", position_price: float = None) -> dict:
        """
        计算四层量化信号（L0/L1/L2/L3）
        L0 超短期: 1分钟K线(100根) + 盘口
        L1 短期: 日K(120根) + 分时 + 资金流
        L2 中期: 周K(52周) + 行业动量
        L3 长期: TTM财报 + PE/PB分位

        Returns: {
            'L0': {'score': float, 'indicators': dict, 'available': bool},
            'L1': {'score': float, 'indicators': dict, 'available': bool},
            'L2': {'score': float, 'indicators': dict, 'available': bool},
            'L3': {'score': float, 'indicators': dict, 'available': bool},
            'composite': float,
            'warnings': list
        }
        """
        import warnings
        warnings.filterwarnings('ignore')

        result = {
            'L0': {'score': 0.0, 'indicators': {}, 'available': False},
            'L1': {'score': 0.0, 'indicators': {}, 'available': False},
            'L2': {'score': 0.0, 'indicators': {}, 'available': False},
            'L3': {'score': 0.0, 'indicators': {}, 'available': False},
            'composite': 0.0,
            'warnings': []
        }

        # L1: 日K数据（所有市场都需要，最基础）
        l1_data = self.get_stock_data(code, market)
        if not l1_data.empty and len(l1_data) >= 20:
            try:
                closes = l1_data['收盘'].values.astype(float)
                highs = l1_data['最高'].values.astype(float)
                lows = l1_data['最低'].values.astype(float)
                volumes = l1_data['成交量'].values.astype(float)

                ma5 = self._sma(closes, 5)
                ma10 = self._sma(closes, 10)
                ma20 = self._sma(closes, 20)
                rsi = self._calc_rsi(closes)
                macd_line, signal_line, hist = self._calc_macd(closes)
                k_val, d_val, j_val = self._calc_kdj(highs, lows, closes)
                atr = self._calc_atr(highs, lows, closes)
                obv_signal = self._calc_obv_signal(closes, volumes)
                adx = self._calc_adx(highs, lows, closes)
                cmf = self._calc_cmf(closes, highs, lows, volumes)
                wr = self._calc_williams_r(highs, lows, closes)
                biass5 = self._calc_ma_biass(closes, 5)
                hist_slope = self._calc_histogram_slope(hist)

                # 均线排列
                if closes[-1] > ma5[-1] > ma10[-1] > ma20[-1]:
                    ma排列 = "多头"
                elif closes[-1] < ma5[-1] < ma10[-1] < ma20[-1]:
                    ma排列 = "空头"
                else:
                    ma排列 = "中性"

                # MACD信号
                pm = macd_line[-2]; ps = signal_line[-2]; cm = macd_line[-1]; cs = signal_line[-1]
                if pm <= ps and cm > cs:
                    macd_state = "金叉"
                elif pm >= ps and cm < cs:
                    macd_state = "死叉"
                else:
                    macd_state = "中性"

                # KDJ
                kdjj = "超买" if k_val > 80 else ("超卖" if k_val < 20 else "中性")
                kdj_high_dead = k_val > 80 and d_val > 70 and cm < cs

                # 乖离率（偏离5日线过大=见顶风险）
                biass5_state = "偏离过大" if biass5 > 8 else ("严重超卖" if biass5 < -8 else "正常")

                # MACD红柱缩短（多头动能衰退）
                hist_positive = hist[-1] > 0
                hist_shortening = hist_positive and hist_slope < -0.15

                # ADX趋势强度
                adx_strong = adx > 25

                # CMF资金流向（>0 净流入，<0 净流出）
                cmf_signal = "净流入" if cmf > 0 else "净流出"

                # 威廉%R超买超卖
                wr_state = "超卖" if wr < -80 else ("超买" if wr > -20 else "中性")

                # 信号计算（短线三大纪律增强版）
                l1_score = 0.0
                if ma排列 == "多头": l1_score += 0.3
                elif ma排列 == "空头": l1_score -= 0.3
                if "金叉" in macd_state: l1_score += 0.3
                elif "死叉" in macd_state: l1_score -= 0.3
                if kdjj == "超卖": l1_score += 0.2
                elif kdjj == "超买": l1_score -= 0.2
                if obv_signal == "底背离": l1_score += 0.2
                elif obv_signal == "顶背离": l1_score -= 0.2
                if adx_strong:
                    if "金叉" in macd_state or ma排列 == "多头": l1_score += 0.2
                    elif "死叉" in macd_state or ma排列 == "空头": l1_score -= 0.2
                if cmf > 0.05: l1_score += 0.2
                elif cmf < -0.05: l1_score -= 0.2
                if wr < -80: l1_score += 0.15
                elif wr > -20: l1_score -= 0.15
                # 乖离率惩罚（价格偏离均线过大=追高风险）
                if biass5 > 8: l1_score -= 0.4
                elif biass5 < -8: l1_score += 0.3
                # 日线KDJ高位死叉（强烈见顶信号）
                if kdj_high_dead: l1_score -= 0.5
                # MACD红柱缩短（多头动能衰退）
                if hist_shortening: l1_score -= 0.3

                l1_score = max(-2.0, min(2.0, l1_score))

                result['L1'] = {
                    'score': round(l1_score, 2),
                    'indicators': {
                        'ma排列': ma排列,
                        'macd': macd_state,
                        'kdj': kdjj,
                        'kdj_k': round(k_val, 1),
                        'kdj_d': round(d_val, 1),
                        'kdj_high_dead': kdj_high_dead,
                        'rsi': round(float(rsi[-1]), 1),
                        'biass5': round(biass5, 1),
                        'biass5_state': biass5_state,
                        'hist_slope': round(hist_slope, 3),
                        'hist_shortening': hist_shortening,
                        'obv背离': obv_signal,
                        'atr': round(float(atr), 4),
                        'adx': round(float(adx), 1),
                        'adx_strong': adx_strong,
                        'cmf': round(float(cmf), 3),
                        'cmf_signal': cmf_signal,
                        'williams_r': round(float(wr), 1),
                        'wr_state': wr_state,
                    },
                    'available': True
                }
            except Exception as e:
                result['warnings'].append(f"L1计算异常: {str(e)[:50]}")
        else:
            result['warnings'].append("L1数据不足")

        # L0: 5分钟K线（A股日内超短期）+ 60分钟辅助看长做短
        if market in ("SH", "SZ"):
            try:
                min_data = self.get_minute_data(code, market, "5")
                h60_data = self.get_minute_data(code, market, "60")
                if not min_data.empty and len(min_data) >= 40:
                    mc = min_data['收盘'].values.astype(float)
                    mh = min_data['最高'].values.astype(float)
                    ml = min_data['最低'].values.astype(float)
                    mv = min_data['成交量'].values.astype(float)

                    ma5_m = self._sma(mc, 5)
                    ma10_m = self._sma(mc, 10)
                    ma40_m = self._sma(mc, 40)
                    m_rsi = self._calc_rsi(mc)
                    m_macd_line, m_signal, m_hist = self._calc_macd(mc)
                    m_atr = self._calc_atr(mh, ml, mc)

                    # 5日线乖离率
                    biass5_m = self._calc_ma_biass(mc, 5)
                    biass5_m_state = "偏离过大" if biass5_m > 6 else ("严重超卖" if biass5_m < -6 else "正常")

                    # MACD红柱缩短（5分钟多头动能）
                    m_hist_positive = m_hist[-1] > 0
                    m_hist_slope = self._calc_histogram_slope(m_hist)
                    m_hist_shortening = m_hist_positive and m_hist_slope < -0.15

                    # MA交叉
                    if ma10_m[-1] > ma40_m[-1]:
                        ma_cross = "golden"
                    else:
                        ma_cross = "dead"

                    # 支撑阻力（最近15根高低点）
                    recent_high = float(np.max(mh[-15:]))
                    recent_low = float(np.min(ml[-15:]))
                    cur_price = mc[-1]
                    support = round(recent_low, 2)
                    resistance = round(recent_high, 2)

                    # ATR 归一化（用于调整量比阈值，高波动股票阈值相应提高）
                    atr_ratio = float(m_atr) / (float(m_atr) + float(mc[-1]) / 100)
                    vol_threshold_high = 1.5 + atr_ratio * 1.5
                    vol_threshold_low = 0.6 - atr_ratio * 0.2

                    # 量比（ATR 自适应阈值）
                    avg_vol = np.mean(mv[-20:]) if len(mv) >= 20 else mv[-1]
                    vol_ratio_m = float(mv[-1] / avg_vol) if avg_vol > 0 else 1.0

                    # 威廉 %R（5 分钟极值捕捉）
                    wr_5m = self._calc_williams_r(mh, ml, mc, period=14)
                    wr5m_state = "超卖" if wr_5m < -80 else ("超买" if wr_5m > -20 else "中性")

                    # RSI状态
                    rsi_m = float(m_rsi[-1])
                    if rsi_m > 70:
                        rsi_state = "超买"
                    elif rsi_m < 30:
                        rsi_state = "超卖"
                    else:
                        rsi_state = "中性"

                    # 60分钟KDJ（看长做短）
                    h60_k, h60_d, _ = (50.0, 50.0, 50.0)
                    h60_kdj_high_dead = False
                    if not h60_data.empty and len(h60_data) >= 20:
                        hc = h60_data['收盘'].values.astype(float)
                        hh = h60_data['最高'].values.astype(float)
                        hl = h60_data['最低'].values.astype(float)
                        h60_k, h60_d, _ = self._calc_kdj(hh, hl, hc)
                        h60_macd, h60_sig, h60_hist = self._calc_macd(hc)
                        h60_pm = h60_macd[-2]; h60_ps = h60_sig[-2]
                        h60_cm = h60_macd[-1]; h60_cs = h60_sig[-1]
                        h60_kdj_high_dead = h60_k > 80 and h60_d > 70 and h60_cm < h60_cs

                    # 信号计算（短线三大纪律增强版）
                    l0_score = 0.0
                    if ma_cross == "golden": l0_score += 0.3
                    else: l0_score -= 0.3
                    if vol_ratio_m > vol_threshold_high and mc[-1] > ma5_m[-1]: l0_score += 0.3
                    elif vol_ratio_m < vol_threshold_low: l0_score -= 0.2
                    if rsi_m > 70: l0_score -= 0.3
                    elif rsi_m < 30: l0_score += 0.3
                    if wr_5m < -80: l0_score += 0.2
                    elif wr_5m > -20: l0_score -= 0.2
                    # 5日线乖离率（守住趋势，不破均线则持有）
                    if mc[-1] > ma5_m[-1]: l0_score += 0.2
                    elif mc[-1] < ma5_m[-1]: l0_score -= 0.3
                    if biass5_m > 6: l0_score -= 0.3
                    elif biass5_m < -6: l0_score += 0.2
                    # 5分钟MACD红柱缩短
                    if m_hist_shortening: l0_score -= 0.25
                    # 60分钟KDJ高位死叉（看长做短，见顶信号）
                    if h60_kdj_high_dead: l0_score -= 0.5

                    l0_score = max(-2.0, min(2.0, l0_score))

                    result['L0'] = {
                        'score': round(l0_score, 2),
                        'indicators': {
                            'ma_cross': ma_cross,
                            'ma5_price': round(float(ma5_m[-1]), 2),
                            'rsi': round(rsi_m, 1),
                            'rsi_state': rsi_state,
                            'atr': round(float(m_atr), 4),
                            'atr_ratio': round(atr_ratio, 3),
                            'support': support,
                            'resistance': resistance,
                            'vol_ratio': round(vol_ratio_m, 2),
                            'vol_thresh_high': round(vol_threshold_high, 2),
                            'ma10': round(float(ma10_m[-1]), 2),
                            'ma40': round(float(ma40_m[-1]), 2),
                            'williams_r_5m': round(float(wr_5m), 1),
                            'wr5m_state': wr5m_state,
                            'biass5': round(biass5_m, 1),
                            'biass5_state': biass5_m_state,
                            'hist_slope': round(m_hist_slope, 3),
                            'hist_shortening': m_hist_shortening,
                            'h60_k': round(float(h60_k), 1),
                            'h60_d': round(float(h60_d), 1),
                            'h60_kdj_high_dead': h60_kdj_high_dead,
                        },
                        'available': True
                    }
                else:
                    result['warnings'].append("L0数据不足（5分钟K线不足40根）")
            except Exception as e:
                result['warnings'].append(f"L0计算异常: {str(e)[:50]}")

        # L2: 周K数据（A股中期）—— v1.3: 走 stock_repo.get_weekly_kline
        weekly_df = pd.DataFrame()
        if market in ("SH", "SZ"):
            try:
                from src.repository.stock_repo import stock_repo
                weekly_df = stock_repo.get_weekly_kline(code, weeks=60) or pd.DataFrame()
            except Exception as e:
                result.setdefault('warnings', []).append(f"L2周K异常: {str(e)[:50]}")
            if not weekly_df.empty and len(weekly_df) >= 10:
                    wc = weekly_df['收盘'].values.astype(float)
                    wh = weekly_df['最高'].values.astype(float)
                    wl = weekly_df['最低'].values.astype(float)

                    w_ma10 = self._sma(wc, 10)
                    w_ma20 = self._sma(wc, 20)
                    w_macd_line, w_signal, w_hist = self._calc_macd(wc)

                    # 26周动量（vs 市场均值作为行业RPS代理）
                    half_year_n = min(26, len(wc))
                    stock_return = (wc[-1] - wc[-half_year_n]) / wc[-half_year_n] * 100 if wc[-half_year_n] != 0 else 0
                    market_return_proxy = (np.mean(wc[-half_year_n:]) - np.mean(wc[max(0, -half_year_n*2):-half_year_n])) / (np.mean(wc[max(0, -half_year_n*2):-half_year_n]) + 1e-9) * 100
                    rps = stock_return - market_return_proxy

                    # 周线均线排列
                    if wc[-1] > w_ma10[-1] > w_ma20[-1]:
                        w_ma_trend = "多头"
                    elif wc[-1] < w_ma10[-1] < w_ma20[-1]:
                        w_ma_trend = "空头"
                    else:
                        w_ma_trend = "中性"

                    # 周线MACD
                    wpm = w_macd_line[-2]; wps = w_signal[-2]
                    wcm = w_macd_line[-1]; wcs = w_signal[-1]
                    if wpm <= wps and wcm > wcs:
                        w_macd_state = "金叉"
                    elif wpm >= wps and wcm < wcs:
                        w_macd_state = "死叉"
                    else:
                        w_macd_state = "中性"

                    l2_score = 0.0
                    if w_ma_trend == "多头": l2_score += 0.6
                    elif w_ma_trend == "空头": l2_score -= 0.6
                    if "金叉" in w_macd_state: l2_score += 0.4
                    elif "死叉" in w_macd_state: l2_score -= 0.4
                    if wc[-1] > w_ma10[-1]: l2_score += 0.2
                    else: l2_score -= 0.2
                    # RPS动量加成（每10%超额收益 +0.2，上限 +0.6）
                    if rps > 0:
                        l2_score += min(rps / 10 * 0.2, 0.6)
                    else:
                        l2_score += max(rps / 10 * 0.2, -0.4)

                    l2_score = max(-2.0, min(2.0, l2_score))

                    result['L2'] = {
                        'score': round(l2_score, 2),
                        'indicators': {
                            'weekly_ma': w_ma_trend,
                            'weekly_macd': w_macd_state,
                            'weekly_ma10': round(float(w_ma10[-1]), 2),
                            'weekly_close': round(float(wc[-1]), 2),
                            'weekly_rsi': round(float(self._calc_rsi(wc)[-1]), 1),
                            'rps_26w': round(rps, 1),
                        },
                        'available': True
                    }
            else:
                result['warnings'].append("L2数据不足（周K不足10根）")

        # L3: 财报数据（长期）
        if market in ("SH", "SZ"):
            try:
                fundamental = self.calculate_fundamental_indicators(code, market)
                fi = fundamental.get('financial_indicators', {}) if isinstance(fundamental, dict) else {}
                if not fi:
                    fi = {}
                roe = fi.get('净资产收益率', fi.get('净资产收益率(ROE)', 0))
                pe = fi.get('市盈率', 0)
                pb = fi.get('市净率', 0)
                rev_growth = fi.get('营收同比增长率', 0)
                profit_growth = fi.get('净利润同比增长率', 0)
                div_yield = fi.get('股息率', 0)

                l3_score = 0.0
                industry_pe_high = 25
                industry_roe_high = 12
                industry_roe_low = 5
                if isinstance(roe, (int, float)) and roe > 0:
                    if roe > industry_roe_high: l3_score += 0.5
                    elif roe < industry_roe_low: l3_score -= 0.5
                    else:
                        l3_score += (roe - industry_roe_low) / (industry_roe_high - industry_roe_low) * 0.5 - 0.25
                if isinstance(pe, (int, float)) and pe > 0:
                    if pe < 15: l3_score += 0.3
                    elif pe > 50: l3_score -= 0.4
                    elif pe > industry_pe_high:
                        l3_score += max(-0.2, -(pe - industry_pe_high) / 30 * 0.4)
                if isinstance(pb, (int, float)) and pb > 0:
                    if pb < 1.5: l3_score += 0.2
                    elif pb > 5: l3_score -= 0.3
                    elif pb > 3:
                        l3_score -= (pb - 3) / 2 * 0.2
                if isinstance(rev_growth, (int, float)):
                    if rev_growth > 20: l3_score += 0.3
                    elif rev_growth < 0: l3_score -= 0.3
                    else:
                        l3_score += min(max(rev_growth, -0.3) / 20 * 0.3, 0.3)
                if isinstance(profit_growth, (int, float)) and profit_growth > 20: l3_score += 0.2
                if isinstance(div_yield, (int, float)) and div_yield > 3: l3_score += 0.3

                l3_score = max(-2.0, min(2.0, l3_score))

                result['L3'] = {
                    'score': round(l3_score, 2),
                    'indicators': {
                        'roe': round(float(roe), 2) if isinstance(roe, (int, float)) else None,
                        'pe': round(float(pe), 2) if isinstance(pe, (int, float)) else None,
                        'pb': round(float(pb), 2) if isinstance(pb, (int, float)) else None,
                        'revenue_growth': round(float(rev_growth), 2) if isinstance(rev_growth, (int, float)) else None,
                        'profit_growth': round(float(profit_growth), 2) if isinstance(profit_growth, (int, float)) else None,
                        'dividend_yield': round(float(div_yield), 2) if isinstance(div_yield, (int, float)) else None,
                        'financial_data_points': len(fi),
                    },
                    'available': True
                }
            except Exception as e:
                result['warnings'].append(f"L3计算异常: {str(e)[:50]}")

        # 综合信号
        w = {'L0': 0.2, 'L1': 0.3, 'L2': 0.25, 'L3': 0.25}
        composite = 0.0
        active_weight = 0.0
        for key, weight in w.items():
            if result[key]['available']:
                composite += result[key]['score'] * weight
                active_weight += weight
        if active_weight > 0:
            result['composite'] = round(composite / active_weight * sum(w.values()), 3)
        else:
            result['composite'] = 0.0
        return result

    def generate_strategy_recommendation(self, position_info: dict, signals: dict, price_info: dict = None) -> str:
        """
        基于四层信号生成策略建议文本（同步，无LLM调用时返回量化文本）
        """
        code = position_info.get('code', '')
        position_price = position_info.get('cost_price', 0)
        position_quantity = position_info.get('shares', 0)
        current_price = position_info.get('current_price', price_info.get('current_price', 0) if price_info else 0)
        position_amount = position_price * position_quantity
        profit_loss = (current_price - position_price) * position_quantity if current_price and position_price else 0
        profit_loss_pct = ((current_price / position_price - 1) * 100) if current_price and position_price else 0

        l0 = signals.get('L0', {})
        l1 = signals.get('L1', {})
        l2 = signals.get('L2', {})
        l3 = signals.get('L3', {})
        composite = signals.get('composite', 0)

        # 信号解读
        def signal_desc(s, label):
            if not s.get('available'): return f"{label}信号不可用"
            score = s.get('score', 0)
            if score >= 1.0: return f"{label}强烈看多({score:+.1f})"
            elif score >= 0.3: return f"{label}偏多({score:+.1f})"
            elif score > -0.3: return f"{label}中性({score:+.1f})"
            elif score >= -1.0: return f"{label}偏空({score:+.1f})"
            else: return f"{label}强烈看空({score:+.1f})"

        lines = []
        lines.append(f"📊 {code} 量化策略分析报告")
        lines.append(f"")
        lines.append(f"【持仓状态】")
        lines.append(f"• 持仓成本: ¥{position_price:.2f}  当前价: ¥{current_price:.2f}")
        lines.append(f"• 浮盈亏: {'+' if profit_loss >= 0 else ''}¥{profit_loss:.2f} ({'+' if profit_loss_pct >= 0 else ''}{profit_loss_pct:.2f}%)")
        lines.append(f"")

        lines.append(f"【四层信号解读】")
        lines.append(f"• {signal_desc(l0, 'L0超短期')}")
        lines.append(f"• {signal_desc(l1, 'L1短期')}")
        lines.append(f"• {signal_desc(l2, 'L2中期')}")
        lines.append(f"• {signal_desc(l3, 'L3长期')}")
        lines.append(f"• 综合评分: {composite:+.2f}")
        lines.append(f"")

        # 短线三大纪律检测
        l0_ind = l0.get('indicators', {}) if l0.get('available') else {}
        l1_ind = l1.get('indicators', {}) if l1.get('available') else {}
        stop_loss_price = None
        short_term_action = ""

        # 纪律一：持股监控（价格在5日线上+成交量健康+红柱未缩短）
        price_above_ma5 = l0_ind.get('ma5_price', 0) > 0 and current_price >= l0_ind.get('ma5_price', current_price)
        hist_not_shortening = not l0_ind.get('hist_shortening', False) and not l1_ind.get('hist_shortening', False)
        vol_healthy = l0_ind.get('vol_ratio', 1) >= l0_ind.get('vol_thresh_high', 2) * 0.7

        # 纪律三：止损检测（跌破5日线 或 成本-3%）
        broken_ma5 = current_price < l0_ind.get('ma5_price', current_price) if l0_ind.get('ma5_price', 0) > 0 else False
        stop_loss_triggered = (position_price > 0 and current_price > 0 and
                              (current_price < position_price * 0.97))

        # 纪律二：见顶卖出信号
        kdj_high_dead_daily = l1_ind.get('kdj_high_dead', False)
        kdj_high_dead_h60 = l0_ind.get('h60_kdj_high_dead', False)
        biass_too_high = l1_ind.get('biass5', 0) > 8 or l0_ind.get('biass5', 0) > 6
        top_signals = []
        if kdj_high_dead_daily: top_signals.append("日线KDJ高位死叉")
        if kdj_high_dead_h60: top_signals.append("60分钟KDJ高位死叉")
        if biass_too_high: top_signals.append("乖离率过大")
        if l0_ind.get('hist_shortening', False): top_signals.append("MACD红柱缩短")
        if l1_ind.get('hist_shortening', False): top_signals.append("日线MACD红柱缩短")

        if stop_loss_triggered:
            short_term_action = "⚠️ 触发止损（-3%）"
            stop_loss_price = current_price
        elif broken_ma5 and (kdj_high_dead_daily or kdj_high_dead_h60):
            short_term_action = "⚠️ 见顶信号强烈，建议清仓"
            stop_loss_price = current_price
        elif broken_ma5:
            short_term_action = "⚠️ 跌破5日线，建议减仓"
            stop_loss_price = l0_ind.get('ma5_price', current_price * 0.98)
        elif price_above_ma5 and hist_not_shortening and vol_healthy:
            short_term_action = "✅ 上升趋势健康，可继续持有"
        elif top_signals:
            short_term_action = f"⚠️ 见顶信号：{' + '.join(top_signals)}"
        else:
            short_term_action = "⏸️ 趋势不明，保持观望"

        # 操作建议
        if composite >= 1.5:
            action = "✅ 建议加仓/重仓持有"
            reason = "多周期共振看多，技术面、基本面、情绪面同步向好"
        elif composite >= 0.5:
            action = "✅ 持有观望，可逢低加仓"
            reason = "综合信号偏多，但需注意短线波动"
        elif composite >= -0.5:
            action = "⏸️ 控制仓位，等待趋势明朗"
            reason = "信号不强烈，建议减少操作频率"
        else:
            action = "⚠️ 建议减仓/清仓"
            reason = "多周期偏空，建议降低风险敞口"

        lines.append(f"【操作建议】{action}")
        lines.append(f"• {reason}")
        if short_term_action:
            lines.append(f"• 短线信号: {short_term_action}")
        lines.append(f"")

        # 关键指标
        if l1.get('available'):
            ind = l1.get('indicators', {})
            lines.append(f"【短期关键指标】")
            lines.append(f"• RSI(14): {ind.get('rsi', '-')}")
            lines.append(f"• 乖离率(5日): {ind.get('biass5', '-')}% ({ind.get('biass5_state', '-')})")
            lines.append(f"• 均线排列: {ind.get('ma排列', '-')}")
            lines.append(f"• MACD: {ind.get('macd', '-')} {'⚠️红柱缩短' if ind.get('hist_shortening') else ''}")
            lines.append(f"• KDJ: {ind.get('kdj', '-')} {'⚠️高位死叉' if ind.get('kdj_high_dead') else ''}")
            lines.append(f"• 威廉%R: {ind.get('williams_r', '-')}")
            lines.append(f"• ADX: {ind.get('adx', '-')} {'强趋势' if ind.get('adx_strong') else ''}")
            lines.append(f"")

        if l0.get('available'):
            ind = l0.get('indicators', {})
            lines.append(f"【日内关键指标】")
            lines.append(f"• 5日线乖离率: {ind.get('biass5', '-')}% ({ind.get('biass5_state', '-')})")
            lines.append(f"• 60分钟KDJ: K={ind.get('h60_k', '-')} D={ind.get('h60_d', '-')} {'⚠️高位死叉' if ind.get('h60_kdj_high_dead') else ''}")
            lines.append(f"• 量比: {ind.get('vol_ratio', '-')} (阈值>{ind.get('vol_thresh_high', '-')})")
            lines.append(f"• MACD红柱: {'缩短⚠️' if ind.get('hist_shortening') else '正常'}")
            lines.append(f"")

        # 风险提示（严格止损）
        if composite < 0 or stop_loss_triggered or (position_price > 0 and current_price > 0):
            lines.append(f"【严格止损纪律】")
            if position_price > 0 and current_price > 0:
                stop_5pct = round(position_price * 0.95, 2)
                stop_ma5 = round(l0_ind.get('ma5_price', current_price * 0.98), 2) if l0_ind.get('ma5_price', 0) > 0 else None
                loss_pct = (current_price / position_price - 1) * 100
                lines.append(f"• 成本价止损: ¥{stop_5pct:.2f}（-5%空间 ¥{position_price * 0.95:.2f}）")
                if stop_ma5:
                    lines.append(f"• 5日线止损: ¥{stop_ma5:.2f}")
                lines.append(f"• 当前已浮亏: {'+' if loss_pct >= 0 else ''}{loss_pct:.2f}%")
            lines.append(f"• 跌破5日线必须离场，不追高")
            lines.append(f"")

        return "\n".join(lines)

    def generate_ai_analysis(self, report: dict, stream_callback=None, position_data: dict = None) -> str:
        try:
            logger.info("[AI] 开始构建分析提示...")
            # 先推送初始消息，减少空白等待
            if stream_callback:
                stream_callback("⏳ AI 分析生成中，请稍候...\n\n")

            # v1.5: _build_ai_prompt 可能因数据源（东财/腾讯/新浪）卡住，
            # 用子线程 + 45s 超时保护。先通知用户正在获取额外数据。
            if stream_callback:
                stream_callback("📡 正在获取板块、资金流、新闻等辅助数据...\n\n")

            _prompt_pool = ThreadPoolExecutor(max_workers=1)
            try:
                _fut = _prompt_pool.submit(self._build_ai_prompt, report, position_data)
                try:
                    text = _fut.result(timeout=45)
                except FutureTimeoutError:
                    _fut.cancel()
                    raise TimeoutError("获取辅助数据超时（45s），请检查网络或数据源（东方财富/腾讯/新浪）状态")
            finally:
                # ⚠️ 不能用 `with ThreadPoolExecutor` — 超时后 shutdown(wait=True) 会
                # 等待挂起的线程完成，导致永远阻塞，异常无法传播到外层。
                _prompt_pool.shutdown(wait=False)

            logger.info(f"[AI] 提示词构建完成，长度: {len(text)} 字符")

            if stream_callback:
                stream_callback("✅ 辅助数据获取完成，正在请求 AI 模型...\n\n")

            # 使用真流式：边接收边推送，让用户实时看到生成进度。
            result = self._call_llm(text, stream_callback=stream_callback)

            # 流式结束后做一次离线校验（不影响已推送的内容）
            issues = self._validate_ai_report(result)
            if issues:
                logger.warning(f"[AI] 首次输出未达标（离线记录）: {issues}")
            logger.info(f"[AI] 分析完成，输出长度: {len(result)} 字符")
            return result
        except Exception as e:
            err = str(e)
            logger.error(f"[AI] generate_ai_analysis error: {err[:200]}", exc_info=True)
            return f"## AI 分析失败\n\n错误：{err[:200]}\n\n请检查 config.json 中 model_preference / api_key / api_base_url 是否正确。"

    def _validate_ai_report(self, text: str) -> list:
        """检查 AI 报告关键要素是否完备（精简版）。"""
        issues = []
        if not text or len(text.strip()) < 800:
            issues.append('输出过短')
        if '## 结论卡片' not in text:
            issues.append('缺少结论卡片')
        if text.count('|---') < 1:
            issues.append('缺少 Markdown 表格')
        action_words = ['买入', '持有', '减仓', '止损', '观察']
        if not any(w in text for w in action_words):
            issues.append(f'缺少操作动作（需含：{"、".join(action_words)}之一）')
        return issues[:5]

    def _build_ai_repair_prompt(self, original_prompt: str, bad_output: str, issues: list) -> str:
        return f"""下面是同一个股票分析任务。上一次输出不合格，必须完全重写。

【不合格原因】
{chr(10).join(f'- {x}' for x in issues)}

【上一次不合格输出，仅用于避免重复错误】
{bad_output[:2000]}

【强制要求】
1. 必须包含 `## 结论卡片` 表格（操作评级、核心理由、风险等级、时间因素、板块联动）。
2. 必须包含 `## 核心判断与风险机会`（2-3 个核心判断 + 风险/机会各 2-3 条）。
3. 必须包含 `## 操作计划`，含具体触发价位（根据实际持仓状态输出对应情景）。
4. 必须使用至少 1 个 Markdown 表格。
5. 必须包含“买入/持有/减仓/止损/观察”之一。
6. 如果数据不足，写“数据缺失”而不是编造。
7. 不少于 800 字。
8. 直接输出报告正文。

【原始任务和真实数据】
{original_prompt}"""

    def _replay_ai_stream(self, text: str, stream_callback) -> None:
        """把校验后的完整报告分块推送，保留前端流式体验。"""
        chunk_size = 96
        for i in range(0, len(text), chunk_size):
            stream_callback(text[i:i + chunk_size])

    def _build_ai_prompt(self, r: dict, position_data: dict = None) -> str:
        scores = r.get('scores', {})
        tech = r.get('technical', {})
        fund = r.get('fundamental', {})
        sent = r.get('sentiment', {})
        chanlun = r.get('chanlun', {})
        signals = r.get('signals', [])
        price_info = r.get('price_info', {})
        quote = r.get('quote', {})
        name = r.get('name', r.get('code', ''))
        code = r.get('code', '')

        # 注入四步定量信号（L0-L3）
        l0123_text = ''
        try:
            market = r.get('market', 'SH' if str(code).startswith(('6', '9')) else 'SZ')
            l0123 = self.calculate_signals_l0123(code, market)
            l_lines = []
            for level in ['L0', 'L1', 'L2', 'L3']:
                ld = l0123.get(level, {})
                if ld.get('available'):
                    l_lines.append(f"- {level}: {ld.get('score', 0):+.2f}")
            if l_lines:
                l0123_text = '\n'.join(l_lines)
        except Exception:
            l0123_text = ''

        # 缠论数据
        chanlun_text = ''
        if chanlun and chanlun.get('available'):
            score = chanlun.get('chanlun_score', 0.0)
            trend = chanlun.get('current_trend', 'N/A')
            strength = chanlun.get('trend_strength', '')
            ma_arr = chanlun.get('ma_arrangement', '')
            fenxing = chanlun.get('fenxing', '')
            beichi = chanlun.get('beichi_list', [])
            sr = chanlun.get('support_resistance', {})
            bs = chanlun.get('buy_sell_points', {})
            op_advice = bs.get('operation_advice', '')
            buy_pts = bs.get('buy_points', [])
            sell_pts = bs.get('sell_points', [])

            lines = [
                f"- 综合评分：{score:+.2f}（{trend}{' ' + strength if strength else ''}）",
                f"- 均线排列：{ma_arr}" if ma_arr else None,
                f"- 当前分型：{fenxing}" if fenxing else None,
                f"- 背驰次数：{len(beichi)}" if beichi else None,
                f"- 重要支撑：MA5={sr.get('ma5','—')} / MA10={sr.get('ma10','—')} / MA20={sr.get('ma20','—')} / 近低={sr.get('recent_low','—')} / 近高={sr.get('recent_high','—')}" if sr else None,
                f"- 买入信号：{', '.join(buy_pts[:3]) if buy_pts else '暂无'}",
                f"- 卖出信号：{', '.join(sell_pts[:3]) if sell_pts else '暂无'}",
                f"- 操作建议：{op_advice}" if op_advice else None,
            ]
            chanlun_text = '\n'.join(filter(None, lines))
        elif chanlun:
            chanlun_text = f"- 状态：{chanlun.get('summary', '数据不足')}"
        else:
            chanlun_text = '- 缠论数据暂不可用'

        position_context = ""
        if position_data:
            cost = position_data.get('cost')
            shares = position_data.get('shares', 0)
            if cost and cost > 0 and shares and shares > 0:
                current_price = quote.get('price') or price_info.get('current_price', 0) or tech.get('price', 0)
                if current_price and current_price > 0:
                    total_cost = cost * shares
                    current_value = current_price * shares
                    profit_loss = current_value - total_cost
                    profit_loss_pct = (profit_loss / total_cost * 100) if total_cost > 0 else 0
                    position_context = f"""
持仓信息：
- 成本价：¥{cost}
- 持仓数量：{shares}股
- 总成本：¥{total_cost:.2f}
- 当前市值：¥{current_value:.2f}
- 浮盈亏：{'+' if profit_loss >= 0 else ''}¥{profit_loss:.2f} ({'+' if profit_loss_pct >= 0 else ''}{profit_loss_pct:.2f}%)
"""

        sig_text = '; '.join([f"{s.get('type','')}:{s.get('signal','')}" for s in signals[:5]])

        indicators = fund.get('financial_indicators', {}) if fund else {}
        if fund and fund.get('data_unavailable'):
            fin_text = '财务数据暂不可用（当前数据源未能获取到该股票财务报表）'
        else:
            fin_list = []
            for k, v in list(indicators.items())[:15]:
                fin_list.append(f"{k}: {v}")
            fin_text = '\n'.join(fin_list) if fin_list else "数据暂缺"

        current_price = quote.get('price') or price_info.get('current_price', 0) or tech.get('price', 0)
        change_pct = quote.get('change_pct') or price_info.get('change_percent', 0) or tech.get('change_pct', 0)

        # 额外真实上下文：行业、市场情绪、资金流、个股新闻、估值/市值、持仓信息。
        # 失败时只写“未获取到”，不编造。
        extra = {
            'sector': '未获取到',
            'market_mood': '未获取到',
            'market_temp': '未获取到',
            'northbound': '未获取到',
            'main_flow_30m_yi': '未获取到',
            'stock_news': [],
            'sector_news': [],
            'market_cap_yi': '未获取到',
            'float_market_cap_yi': '未获取到',
            'pe': '未获取到',
            'pb': '未获取到',
            'turnover_pct': '未获取到',
            'political_sector_impact': [],
        }
        try:
            extra['sector'] = stock_repo.fetch_stock_sector(code)
            market = stock_repo.build_market_overview()
            extra['market_mood'] = market.get('mood', '未获取到')
            extra['market_temp'] = market.get('thermometer', '未获取到')
            extra['political_sector_impact'] = market.get('political_sector_impact') or []
            nb = market.get('northbound') or {}
            extra['northbound'] = nb.get('total_yi', '未获取到')
        except Exception:
            logger.warning("[AI] 获取板块/市场情绪/北向数据失败", exc_info=True)
        try:
            flow = stock_repo.get_fund_flow_minute(code)[-30:]
            if flow:
                extra['main_flow_30m_yi'] = round(sum(f.get('main_net', 0) for f in flow) / 1e8, 3)
        except Exception:
            logger.warning("[AI] 获取资金流数据失败", exc_info=True)
        try:
            news = stock_repo.get_news_bundle(code, name=name, sector=extra.get('sector', ''))
            extra['stock_news'] = [n.get('title', '')[:100] for n in (news.get('stock_news') or [])[:6] if n.get('title')]
            extra['sector_news'] = [n.get('title', '')[:100] for n in (news.get('sector_news') or [])[:6] if n.get('title')]
            extra['cls_news']    = [n.get('title', '')[:100] for n in (news.get('cls_news') or [])[:8] if n.get('title')]
        except Exception:
            logger.warning("[AI] 获取新闻数据失败", exc_info=True)
        try:
            from src.repository.stock_repo import stock_repo
            market_code = 'SH' if str(code).startswith(('6', '9')) else 'SZ'
            ext = stock_repo.get_quote_extended(code, market_code)
            if ext and ext.get('turnover_pct') is not None:
                extra['turnover_pct'] = ext['turnover_pct']
            extra['pe'] = ext.get('pe', extra['pe'])
            extra['float_market_cap_yi'] = ext.get('float_market_cap_yi', extra['float_market_cap_yi'])
            extra['market_cap_yi'] = ext.get('market_cap_yi', extra['market_cap_yi'])
            extra['pb'] = ext.get('pb', extra['pb'])
        except Exception:
            logger.warning("[AI] 获取扩展行情数据失败", exc_info=True)

        stock_news_text = '\n'.join([f"- {t}" for t in extra['stock_news']]) or '- 未获取到个股新闻'
        sector_news_text = '\n'.join([f"- {t}" for t in extra['sector_news']]) or '- 未获取到板块/政策新闻'
        cls_news_text = '\n'.join([f"- {t}" for t in extra.get('cls_news', [])]) or '- 未获取到财联社电报'
        political_impact_text = '\n'.join([
            f"- {x.get('sector')}: {x.get('impact')}（分数 {x.get('score')}, 置信 {x.get('confidence')}%）；关键词：{'/'.join(x.get('keywords', [])[:5])}；依据：" +
            '；'.join([h.get('title','') for h in (x.get('headlines') or [])[:2]])
            for x in (extra.get('political_sector_impact') or [])[:6]
        ]) or '- 未获取到可归因的时政/政策板块影响'
        rec = r.get('recommendation', '')
        if isinstance(rec, dict):
            rec_text = rec.get('action', '') or str(rec)
        else:
            rec_text = str(rec)
        reason_text = r.get('reason', '') or (rec.get('reason', '') if isinstance(rec, dict) else '')

        # 获取交易日历信息
        try:
            from src.util.trading_calendar import build_calendar_analysis
            calendar_info = build_calendar_analysis(code, 'A股')
            calendar_summary = calendar_info.get('summary', '')
        except Exception:
            calendar_summary = '交易日历信息暂不可用'

        # v1.3: 不再调用 global_market（港美股已停支持），保留 A 股板块联动占位
        global_summary = '国内板块联动信息见相关产业链标的'

        # v1.4: 操作计划根据实际持仓状态二选一，不再同时输出两种情景
        if position_context:
            operation_plan_section = (
                f"""**当前持仓情景** — 持有/减仓/止损的条件、具体价位、仓位调整（无需考虑买入成本）\n"""
                f"""如果数据缺失，该处写"数据缺失，不能下结论"，不要编造。"""
            )
        else:
            operation_plan_section = (
                f"""**未持仓情景（考虑买入）** — 买入触发价、预期区间、止损价、仓位建议\n"""
                f"""如果数据缺失，该处写"数据缺失，不能下结论"，不要编造。"""
            )

        return f"""你是一位专注 A 股交易决策的股票分析师。根据下方的真实数据，输出一份聚焦现在该做什么的分析报告。

【核心原则】
- 基于真实数据，数据不足时写”数据缺失，不能下结论”
- 禁止泛泛而谈，每个判断必须引用具体数据
- 不编造任何价格、订单、客户、专利信息
- 直接输出报告正文，不要解释你将如何写

【当前股票真实上下文】
- 股票名称：{name}
- 股票代码：{code}
- 所属行业：{extra.get('sector')}
- 当前价格：¥{current_price}
- 今日涨跌幅：{change_pct}%
- 换手率：{extra.get('turnover_pct')}%
- PE：{extra.get('pe')}
- PB：{extra.get('pb')}
- 流通市值：{extra.get('float_market_cap_yi')} 亿
- 总市值：{extra.get('market_cap_yi')} 亿
{position_context}
【交易日历与时间因素】
{calendar_summary}

【全球市场联动数据】
{global_summary}

【市场/资金真实数据】
- 当前大盘情绪：{extra.get('market_mood')}（温度计 {extra.get('market_temp')}）
- 北向合计：{extra.get('northbound')} 亿
- 近 30 分钟主力资金净流入：{extra.get('main_flow_30m_yi')} 亿

【量化评分】
- 综合评分：{scores.get('comprehensive_score', 0)}/100
- 技术评分：{scores.get('technical_score', 0)}/100
- 基本面评分：{scores.get('fundamental_score', 0)}/100
- 情绪评分：{scores.get('sentiment_score', 0)}/100
{l0123_text}

【技术指标】
- RSI：{tech.get('rsi', 'N/A')}
- MA趋势：{tech.get('ma_trend', 'N/A')}
- MA5：{tech.get('ma5', 'N/A')} | MA10：{tech.get('ma10', 'N/A')} | MA20：{tech.get('ma20', 'N/A')}
- MACD：{tech.get('macd_signal', 'N/A')}
- KDJ：K={tech.get('kdj',{}).get('k','N/A')} D={tech.get('kdj',{}).get('d','N/A')} J={tech.get('kdj',{}).get('j','N/A')}
- 布林带位置：{tech.get('bollinger_position', 'N/A')}
- 布林带参考价位：中轨≈MA20={tech.get('ma20', 'N/A')}，上轨=中轨+2×标准差，下轨=中轨-2×标准差
- 成交量比：{tech.get('volume_ratio', 'N/A')}
- 成交量状态：{tech.get('volume_status', 'N/A')}
- 交易信号：{sig_text}
- CCI：{tech.get('cci', 'N/A')}（顺势指标，>100超买|<-100超卖，数值极端提示反转风险）
- ATR：{tech.get('atr', 'N/A')}（平均真实波幅，ATR越大波动越剧烈，止损应设越宽）
- OBV：{tech.get('obv', 'N/A')}（累积成交量，OBV领先价格为先行信号）| 信号：{tech.get('obv_signal', 'N/A')}
- ADX：{tech.get('adx', 'N/A')}（趋势强度指数，>25趋势强劲，<20震荡无趋势）
- BIAS(6)：{tech.get('bias6', 'N/A')}（偏离均线的百分比，>8%超买信号，<-8%超卖信号）

【缠论结构】（独立于上述指标的多空结构分析）
{chanlun_text}

【财务/估值补充】
{fin_text}

【个股新闻标题】
{stock_news_text}

【板块/政策/产业快讯标题】
{sector_news_text}

【财联社电报（优先参考）】
{cls_news_text}

【时政/政策/新闻情绪对板块影响】
{political_impact_text}

【系统初始建议】
- 建议：{rec_text}
- 理由：{reason_text}

【输出格式 — 必须是以下 3 个部分】

## 结论卡片
| 项目 | 结论 |
|---|---|
| 当前操作 | 在“可买 / 持有 / 减仓 / 止损 / 观察”中选一个 |
| 核心理由 | 用一句话概括，必须引用评分/价格/资金/消息之一 |
| 风险等级 | 低 / 中 / 高 |
| 时间因素 | 今天周几、明天是否开盘、是否临近周末/假期 |
| 板块联动影响 | 所属板块的政策/情绪影响（利好/利空/中性） |

## 核心判断与风险机会
3-5 条 bullet 直接回答：这只股的核心矛盾是什么、市场当前忽略了什么。
然后分别列出：
- **上行机会**（2-3 条，含触发条件）
- **下行风险**（2-3 条，含具体价位/条件）

## 操作计划
{operation_plan_section}


【输出要求】
- 不少于 800 字
- 必须包含 `## 结论卡片` 表格
- 必须使用 ✅/⚠️/❌ 标识利好、风险、否定
- 每个判断必须回到 {name}({code}) 的真实数据
- 禁止空话套话，禁止出现”作为AI””无法预测”等废话
- 直接输出报告正文，不要加额外的说明文字"""

    def _call_llm(self, prompt: str, stream_callback=None) -> str:
        """调用LLM API，支持任意OpenAI兼容提供商。通过配置文件切换模型。

        v1.5 改进：
        - 逐 chunk 超时保护（httpx read_timeout=90s），防止 LLM 中途卡死
        - 总超时 300s 硬限
        - 自动重试 1 次（仅对网络类异常），减少偶发失败
        """
        import json, os, logging
        logger = logging.getLogger(__name__)
        import httpx

        # 查找配置文件
        cfg = None
        for p in [os.path.join(os.path.dirname(__file__),'..','..','config.json'),
                  os.path.join(os.getcwd(),'config.json')]:
            if os.path.exists(p):
                with open(p) as f:
                    cfg = json.load(f)
                break
        if not cfg:
            return "(未找到config.json)"

        ai_cfg = cfg.get('ai', {})
        api_keys = cfg.get('api_keys', {})

        # 读取配置：model_preference 决定使用哪个提供商
        provider = ai_cfg.get('model_preference', 'openai')
        model = ai_cfg.get('models', {}).get(provider, 'gpt-4o-mini')
        api_key = api_keys.get(provider, '')
        base_url = ai_cfg.get('api_base_urls', {}).get(provider, 'https://api.openai.com/v1')

        if not api_key:
            logger.warning(f"[AI] 提供商 [{provider}] 未配置API密钥")
            # 遍历所有有API key的提供商作为备用（支持任意提供商名称）
            for fallback_provider, key in api_keys.items():
                if key and fallback_provider not in ('notes',):
                    provider = fallback_provider
                    api_key = key
                    model = ai_cfg.get('models', {}).get(provider, 'gpt-4o-mini')
                    base_url = ai_cfg.get('api_base_urls', {}).get(provider, 'https://api.openai.com/v1')
                    logger.info(f"[AI] 切换到备用提供商: {provider}")
                    break
            else:
                return "(未配置API密钥)"

        # 清理 base_url（去掉尾部空格/斜线）
        base_url = base_url.strip().rstrip('/')
        if not base_url.startswith('http'):
            base_url = 'https://' + base_url

        max_tokens = ai_cfg.get('max_tokens', 2000)
        temperature = ai_cfg.get('temperature', 0.7)

        system_prompt = """你是专注于A股交易决策的分析助手。
你的任务是根据真实市场数据，输出聚焦当前操作的简短分析报告。
必须包含：结论卡片（操作评级+核心理由）、核心判断与风险机会、操作计划（含具体触发价位）。
如果数据不足，写”数据缺失，不能下结论”，禁止编造价格、支撑位、订单、客户信息。
禁止泛泛而谈；每个判断都必须回到当前股票真实数据。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        from openai import OpenAI
        from openai import (
            APITimeoutError,
            APIConnectionError,
            RateLimitError,
            InternalServerError,
        )

        # v1.5: 精细超时控制 — read=90s 确保逐 chunk 卡住时快速失败
        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(300.0, connect=15.0, read=90.0),
        )

        # 可重试的网络异常列表
        _RETRYABLE = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)

        def _do_request():
            """执行一次 LLM 请求（流式或非流式），返回完整文本。"""
            if stream_callback:
                stream = client.chat.completions.create(
                    model=model, messages=messages,
                    max_tokens=max_tokens, temperature=temperature, stream=True,
                )
                full = ""
                deadline = time.monotonic() + 300  # 总超时 5min
                for chunk in stream:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"AI 流式响应总超时（300s），provider={provider}")
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta:
                        text = delta.content
                        if not text:
                            text = getattr(delta, 'reasoning', None) or getattr(delta, 'reasoning_content', None) or ''
                        if text:
                            full += text
                            stream_callback(text)
                if not full:
                    raise RuntimeError(f"[{provider}] empty stream")
                return full

            resp = client.chat.completions.create(
                model=model, messages=messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            if not (resp.choices and resp.choices[0].message and resp.choices[0].message.content):
                raise RuntimeError(f"[{provider}] empty response")
            return resp.choices[0].message.content

        # v1.5: 带 1 次重试的调用
        for attempt in range(1, 3):
            try:
                return _do_request()
            except _RETRYABLE as e:
                if attempt == 1:
                    logger.warning(f"[AI] {provider} 第 1 次失败（{type(e).__name__}），2s 后重试: {e}")
                    time.sleep(2)
                    continue
                raise
            except Exception:
                # 非重试异常（如空响应、超时等），直接抛
                raise


# ── 快速 MyTT 指标计算（纯 numpy，不用 pandas/pd.Series.rolling）──
def _compute_mytt_fast(closes, highs, lows):
    """纯 numpy 实现 DMI/BIAS/WR/MTM/ROC/PSY，用时 ~2s"""
    c = np.asarray(closes, dtype=float)
    h = np.asarray(highs, dtype=float)
    l = np.asarray(lows, dtype=float)
    n = len(c)

    # DMI - 纯 numpy 滚动窗口
    def _sum_over(arr, period):
        out = np.full_like(arr, np.nan)
        cum = np.cumsum(arr)
        out[period-1:] = (cum[period-1:] - np.concatenate([[0], cum[:-period]])) / period * period
        return out

    # TR
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    tr_pad = np.zeros(n)
    tr_pad[1:] = tr
    tr_sum = _sum_over(tr_pad, 14)

    # HD / LD
    hd = np.zeros(n); hd[1:] = h[1:] - h[:-1]
    ld = np.zeros(n); ld[1:] = l[:-1] - l[1:]

    dmp = np.where((hd > 0) & (hd > ld), hd, 0)
    dmm = np.where((ld > 0) & (ld > hd), ld, 0)
    dmp_sum = _sum_over(dmp, 14)
    dmm_sum = _sum_over(dmm, 14)

    pdi_arr = np.where(tr_sum > 0, dmp_sum * 100 / tr_sum, 0)
    mdi_arr = np.where(tr_sum > 0, dmm_sum * 100 / tr_sum, 0)
    dx = np.where((pdi_arr + mdi_arr) > 0, np.abs(mdi_arr - pdi_arr) / (pdi_arr + mdi_arr) * 100, 0)
    adx_arr = _sum_over(dx, 6)
    # 修正 ADX 滑动平均（MyTT 是 MA 不是 SUM）
    adx_ma = np.full_like(adx_arr, np.nan)
    for i in range(len(adx_arr)):
        if i >= 5: adx_ma[i] = np.mean(adx_arr[i-5:i+1]) if not np.isnan(adx_arr[i-5]) else adx_arr[i]
    adx_val = float(adx_ma[-1]) if not np.isnan(adx_ma[-1]) else 0

    pdi = float(pdi_arr[-1]) if not np.isnan(pdi_arr[-1]) else 0
    mdi = float(mdi_arr[-1]) if not np.isnan(mdi_arr[-1]) else 0

    # BIAS(6)
    ma6 = np.mean(c[-6:]) if n >= 6 else np.mean(c)
    bias6 = float((c[-1] - ma6) / ma6 * 100) if ma6 > 0 else 0

    # WR(10)
    if n >= 10:
        h10 = np.max(h[-10:])
        l10 = np.min(l[-10:])
        wr10 = float((h10 - c[-1]) / (h10 - l10) * -100) if (h10 - l10) > 0 else -50
    else:
        wr10 = -50

    # MTM(12)
    mtm = float(c[-1] - c[-13]) if n >= 13 else 0

    # ROC(12)
    roc = float((c[-1] - c[-13]) / c[-13] * 100) if n >= 13 and c[-13] > 0 else 0

    # PSY(12)
    if n >= 12:
        up_days = sum(1 for i in range(-11, 0) if c[i] > c[i-1]) if n >= 13 else 0
        psy = float(up_days / min(n-1, 12) * 100) if n > 1 else 50
    else:
        psy = 50

    return {
        "pdi": round(pdi, 2), "mdi": round(mdi, 2), "adx": round(adx_val, 2),
        "bias6": round(bias6, 2), "wr10": round(wr10, 2),
        "mtm": round(mtm, 2), "roc": round(roc, 2), "psy": round(psy, 2),
    }


__all__ = ['StockAnalyzer']