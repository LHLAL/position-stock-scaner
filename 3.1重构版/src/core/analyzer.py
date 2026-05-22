"""股票分析引擎模块

封装股票分析逻辑，调用数据源获取行情数据，进行技术面/基本面/情绪面分析
"""
from datetime import datetime, timedelta
import re
import pandas as pd
import numpy as np
from typing import Any

from src.data.registry import DataSourceRegistry, registry
from src.core.strategy_generator import StrategyGenerator
from src.core.chanlun import analyze_chanlun


class StockAnalyzer:

    def __init__(self, data_registry: DataSourceRegistry | None = None):
        self.registry = data_registry or registry
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
        """标准化股票代码，返回 (normalized_code, market, display_code)"""
        c = code.strip().upper()
        if c.startswith('SH') or c.startswith('SZ'):
            market = c[:2]
            raw = c[2:]
            return (raw, market, c)
        if c.startswith('HK'):
            return (c[2:], 'HK', c)
        if '.HK' in c:
            raw = c.replace('.HK', '')
            return (raw, 'HK', c)
        if '.SS' in c or '.SZ' in c:
            parts = c.split('.')
            market = 'SH' if parts[1] == 'SS' else 'SZ'
            return (parts[0], market, c)
        if re.match(r'^6\d{5}$', c):
            return (c, 'SH', c)
        if re.match(r'^(0|3)\d{5}$', c):
            return (c, 'SZ', c)
        if re.match(r'^\d{5}$', c):
            return (c, 'HK', c)
        if c.isalpha():
            return (c, 'US', c)
        return (c, 'SH', c)


    def get_stock_name(self, code: str) -> str:
        import akshare as ak
        code_norm, market, _ = self.normalize_stock_code(code)
        quote = self.registry.get_quote(code_norm, market)
        if quote and quote.name:
            return quote.name
        try:
            df = ak.stock_zh_a_spot_em()
            row = df[df['\u4ee3\u7801'] == code_norm]
            if not row.empty:
                return str(row.iloc[0].get('\u540d\u79f0', code_norm))
        except:
            pass
        return code

    def get_stock_data(self, code: str, market: str = "SH", days: int = 365):
        """获取历史K线数据: sina -> yfinance"""
        import warnings
        warnings.filterwarnings('ignore')

        # 1. sina finance
        try:
            import requests
            prefix = {'SH': 'sh', 'SZ': 'sz', 'HK': 'hk'}.get(market, 'sh')
            url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=5&datalen=200")
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200 and resp.text.strip():
                import json
                data = json.loads(resp.text)
                if data and len(data) > 20:
                    records = []
                    for item in data:
                        records.append({
                            '日期': item.get('day', '')[:10],
                            '开盘': float(item.get('open', 0)),
                            '收盘': float(item.get('close', 0)),
                            '最高': float(item.get('high', 0)),
                            '最低': float(item.get('low', 0)),
                            '成交量': int(float(item.get('volume', 0))),
                        })
                    return pd.DataFrame(records)
        except:
            pass

        # 2. yfinance
        try:
            import yfinance as yf
            yahoo_code = code
            if market == "SH":
                yahoo_code = f"{code}.SS"
            elif market == "SZ":
                yahoo_code = f"{code}.SZ"
            elif market == "HK":
                yahoo_code = f"{code}.HK"
            start = (datetime.now()-timedelta(days=days)).strftime("%Y-%m-%d")
            end = (datetime.now()+timedelta(days=1)).strftime("%Y-%m-%d")
            ticker = yf.Ticker(yahoo_code)
            hist = ticker.history(start=start, end=end)
            if hist is not None and not hist.empty:
                df = pd.DataFrame({
                    'date': hist.index.strftime('%Y-%m-%d'),
                    'open': hist['Open'].round(2).values,
                    'close': hist['Close'].round(2).values,
                    'high': hist['High'].round(2).values,
                    'low': hist['Low'].round(2).values,
                    'volume': hist['Volume'].astype(int).values,
                })
                df.columns = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
                return df
        except:
            pass

        return pd.DataFrame()

    def get_minute_data(self, code: str, market: str = "SH", period: str = "5") -> pd.DataFrame:
        scale_map = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}
        scale = scale_map.get(period, 5)
        prefix = {'SH': 'sh', 'SZ': 'sz'}.get(market, 'sh')

        try:
            import requests
            url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                   f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale={scale}&ma=5&datalen=200")
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200 and resp.text.strip():
                import json
                data = json.loads(resp.text)
                if data and len(data) >= 20:
                    records = [{
                        '日期': item.get('day', '')[:16],
                        '开盘': float(item.get('open', 0)),
                        '收盘': float(item.get('close', 0)),
                        '最高': float(item.get('high', 0)),
                        '最低': float(item.get('low', 0)),
                        '成交量': int(float(item.get('volume', 0))),
                    } for item in data]
                    return pd.DataFrame(records)
        except Exception as e:
            print(f"[Analyzer] get_minute_data failed {market}:{code} period={period} - {e}")
        return pd.DataFrame()

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

    def _default_technical(self) -> dict:
        """\u7f3a\u7701\u503c\u6280\u672f\u6307\u6807"""
        return {
            "ma_trend": "\u6570\u636e\u4e0d\u8db3", "rsi": 50.0,
            "macd_signal": "\u6570\u636e\u4e0d\u8db3", "volume_status": "\u6570\u636e\u4e0d\u8db3",
            "kdj": {"k": 50.0, "d": 50.0, "j": 50.0}, "bollinger_position": 0.5,
            "vr": 100.0, "cci": 0.0, "trix": 0.0, "atr": 0.0
        }

    def analyze_stock(self, code: str, market: str = "SH") -> dict[str, Any]:
        timestamp = datetime.now().isoformat()

        price_data = self.get_stock_data(code, market)
        price_info = self.get_price_info(price_data)
        quote = self.registry.get_quote(code, market)
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
        elif lc < m5 < m10 > m20:
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
        """获取25项真实财务指标，失败时返回占位值"""
        if market not in ("SH", "SZ"):
            return self._default_fundamental()
        
        indicators = {}
        valuation = {}
        forecasts = []
        dividends = []
        industry = {}
        
        # 获取财务数据（使用快速版akshare接口）
        try:
            import akshare as ak, warnings
            warnings.filterwarnings('ignore')
            fin_df = ak.stock_financial_abstract(symbol=code)
            if fin_df is not None and not fin_df.empty and '指标' in fin_df.columns:
                data_col = fin_df.columns[2]
                row_index = {r: r for r in fin_df['指标'].unique()}
                row_map = {
                    '归母净利润': '归母净利润', '营业总收入': '营业总收入', '净利润': '净利润',
                    '基本每股收益': '基本每股收益', '每股净资产': '每股净资产',
                    '每股经营现金流': '每股经营现金流',
                    '净资产收益率(ROE)': '净资产收益率(ROE)',
                    '总资产报酬率(ROA)': '总资产报酬率(ROA)',
                    '毛利率': '毛利率', '销售净利率': '销售净利率',
                    '资产负债率': '资产负债率',
                    '净利润同比增长率': '归属母公司净利润增长率',
                    '营收同比增长率': '营业总收入增长率',
                }
                for cn_name, row_name in row_map.items():
                    match = fin_df[fin_df['指标'] == row_name]
                    if not match.empty and data_col in match.columns:
                        val = match[data_col].iloc[0]
                        if val is not None:
                            import math
                            if isinstance(val, (int, float)) and not math.isnan(val):
                                indicators[cn_name] = round(float(val), 2)
                # 腾讯PE/PB
                try:
                    import requests as _req
                    prefix = 'sh' if market == 'SH' else 'sz'
                    resp = _req.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=3)
                    fields = resp.text.split('~')
                    if len(fields) > 39 and fields[39]:
                        indicators['市盈率'] = round(float(fields[39]), 2)
                    if len(fields) > 46 and fields[46]:
                        indicators['市净率'] = round(float(fields[46]), 2)
                except:
                    pass
        except:
            pass

        if not indicators:
            indicators = {
                "净利润率": 10.0, "净资产收益率": 12.0, "总资产收益率": 8.0,
                "毛利率": 25.0, "营业利润率": 12.0,
                "流动比率": 2.0, "速动比率": 1.5, "资产负债率": 45.0, "产权比率": 0.8, "利息保障倍数": 5.0,
                "总资产周转率": 0.8, "存货周转率": 4.5, "应收账款周转率": 5.0,
                "流动资产周转率": 1.5, "固定资产周转率": 2.0,
                "营收同比增长率": 15.0, "净利润同比增长率": 12.0,
                "总资产增长率": 8.0, "净资产增长率": 10.0, "经营现金流增长率": 10.0,
                "市盈率": 20.0, "市净率": 2.5, "市销率": 3.0, "PEG比率": 1.2, "股息收益率": 2.0
            }
        else:
            pe = indicators.get('市盈率', 0)
            profit_growth = indicators.get('净利润同比增长率', 0)
            if isinstance(pe, (int, float)) and isinstance(profit_growth, (int, float)) and pe > 0 and profit_growth > 0:
                indicators['PEG比率'] = round(pe / profit_growth, 2)
            rev_growth = indicators.get('营收同比增长率', 0)
            if isinstance(pe, (int, float)) and isinstance(rev_growth, (int, float)) and pe > 0 and rev_growth > 0:
                peg_from_rev = pe / rev_growth
                if 'PEG比率' not in indicators:
                    indicators['PEG比率'] = round(peg_from_rev, 2)

        return {
            "basic_info": {"股票代码": code, "市场": market, "股票名称": code},
            "financial_indicators": indicators,
            "valuation": valuation,
            "performance_forecast": forecasts,
            "dividend_info": dividends,
            "industry_analysis": industry
        }

    def _default_fundamental(self) -> dict:
        """默认基本面数据"""
        return {
            "basic_info": {}, "financial_indicators": {},
            "valuation": {}, "performance_forecast": [],
            "dividend_info": [], "industry_analysis": {}
        }

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
        return {
            "ma_trend": "数据不足",
            "rsi": 50.0,
            "macd_signal": "数据不足",
            "volume_status": "数据不足",
            "kdj": {"k": 50.0, "d": 50.0, "j": 50.0},
            "bollinger_position": 0.5,
            "vr": 100.0,
            "cci": 0.0,
            "trix": 0.0,
            "atr": 0.0,
            "obv": 0.0,
            "obv_signal": "数据不足",
        }

    @staticmethod
    def _sma(data, window):
        arr = np.array(data, dtype=float)
        result = np.full_like(arr, np.nan)
        for i in range(len(arr)):
            if i >= window - 1:
                result[i] = np.mean(arr[i - window + 1:i + 1])
        return result

    @staticmethod
    def _ema(data, window):
        arr = np.array(data, dtype=float)
        result = np.full_like(arr, np.nan)
        multiplier = 2 / (window + 1)
        result[0] = arr[0]
        for i in range(1, len(arr)):
            result[i] = (arr[i] - result[i - 1]) * multiplier + result[i - 1]
        return result

    @staticmethod
    def _calc_rsi(closes, period=14):
        arr = np.array(closes, dtype=float)
        deltas = np.diff(arr)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        rsi = np.full_like(arr, 50.0)
        avg_gain = np.mean(gains[:period]) if len(gains) >= period else 0
        avg_loss = np.mean(losses[:period]) if len(losses) >= period else 0.001
        rs = avg_gain / avg_loss if avg_loss else 1
        rsi[period] = 100 - (100 / (1 + rs))
        for i in range(period + 1, len(arr)):
            avg_gain = ((avg_gain * (period - 1)) + gains[i - 1]) / period
            avg_loss = ((avg_loss * (period - 1)) + losses[i - 1]) / period
            rs = avg_gain / avg_loss if avg_loss else 1
            rsi[i] = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def _calc_macd(closes, fast=12, slow=26, signal=9):
        arr = np.array(closes, dtype=float)
        ema_fast = StockAnalyzer._ema(arr, fast)
        ema_slow = StockAnalyzer._ema(arr, slow)
        macd_line = ema_fast - ema_slow
        signal_line = StockAnalyzer._ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def _calc_kdj(highs, lows, closes, period=9):
        h = np.array(highs, dtype=float)
        l = np.array(lows, dtype=float)
        c = np.array(closes, dtype=float)
        hn = np.full_like(c, np.nan)
        ln = np.full_like(c, np.nan)
        for i in range(len(c)):
            start = max(0, i - period + 1)
            hn[i] = np.max(h[start:i + 1])
            ln[i] = np.min(l[start:i + 1])
        rsv = np.where((hn - ln) != 0, (c - ln) / (hn - ln) * 100, 50)
        k = np.full_like(c, 50.0)
        d = np.full_like(c, 50.0)
        for i in range(1, len(c)):
            k[i] = 2 / 3 * k[i - 1] + 1 / 3 * rsv[i]
            d[i] = 2 / 3 * d[i - 1] + 1 / 3 * k[i]
        j = 3 * k - 2 * d
        return float(k[-1]), float(d[-1]), float(j[-1])

    @staticmethod
    def _calc_bollinger_position(closes, ma20, std_mult=2):
        c = np.array(closes, dtype=float)
        m20 = np.array(ma20, dtype=float)
        std = np.full_like(c, np.nan)
        for i in range(len(c)):
            if i >= 19:
                std[i] = np.std(c[i - 19:i + 1])
        if np.isnan(std[-1]) or m20[-1] == 0:
            return 0.5
        upper = m20[-1] + std_mult * std[-1]
        lower = m20[-1] - std_mult * std[-1]
        if upper == lower:
            return 0.5
        return (c[-1] - lower) / (upper - lower)

    @staticmethod
    def _calc_vr(closes, volumes, period=26):
        if len(closes) < period:
            return 100.0
        c = np.array(closes[-period:], dtype=float)
        v = np.array(volumes[-period:], dtype=float)
        if len(c) < 2:
            return 100.0
        deltas = np.diff(c)
        up_vol = np.sum(v[1:][deltas >= 0])
        down_vol = np.sum(v[1:][deltas < 0])
        if down_vol == 0:
            return 200.0
        return up_vol / down_vol * 100

    @staticmethod
    def _calc_cci(highs, lows, closes, period=20):
        if len(closes) < period:
            return 0.0
        h = np.array(highs[-period:], dtype=float)
        l = np.array(lows[-period:], dtype=float)
        c = np.array(closes[-period:], dtype=float)
        tp = (h + l + c) / 3
        ma_tp = np.mean(tp)
        md = np.mean(np.abs(tp - ma_tp))
        if md == 0:
            return 0.0
        return (tp[-1] - ma_tp) / (0.015 * md)

    @staticmethod
    def _calc_obv(closes, volumes):
        c = np.array(closes, dtype=float)
        v = np.array(volumes, dtype=float)
        if len(c) < 2:
            return 0.0
        obv = np.zeros(len(c))
        obv[0] = v[0]
        deltas = np.diff(c)
        for i in range(1, len(c)):
            if deltas[i - 1] > 0:
                obv[i] = obv[i - 1] + v[i]
            elif deltas[i - 1] < 0:
                obv[i] = obv[i - 1] - v[i]
            else:
                obv[i] = obv[i - 1]
        return float(obv[-1])

    @staticmethod
    def _calc_obv_signal(closes, volumes, period=20):
        c = np.array(closes, dtype=float)
        v = np.array(volumes, dtype=float)
        if len(c) < period + 1:
            return "数据不足"
        obv_vals = np.zeros(len(c))
        obv_vals[0] = v[0]
        deltas = np.diff(c)
        for i in range(1, len(c)):
            if deltas[i - 1] > 0:
                obv_vals[i] = obv_vals[i - 1] + v[i]
            elif deltas[i - 1] < 0:
                obv_vals[i] = obv_vals[i - 1] - v[i]
            else:
                obv_vals[i] = obv_vals[i - 1]
        ma_obv = np.convolve(obv_vals, np.ones(period) / period, mode='valid')
        if len(ma_obv) < 2:
            return "数据不足"
        cur_obv = obv_vals[-1]
        cur_ma = ma_obv[-1]
        prev_ma = ma_obv[-2] if len(ma_obv) > 1 else cur_ma
        price_cur = c[-1]
        price_prev = c[-period] if len(c) > period else c[0]
        if cur_obv > cur_ma and price_cur <= price_prev:
            return "顶背离"
        elif cur_obv < cur_ma and price_cur >= price_prev:
            return "底背离"
        elif cur_obv > cur_ma:
            return "量价配合"
        else:
            return "中性"

    @staticmethod
    def _calc_atr(highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.0
        h = np.array(highs[-(period + 1):], dtype=float)
        l = np.array(lows[-(period + 1):], dtype=float)
        c = np.array(closes[-(period + 1):], dtype=float)
        tr = np.maximum(h[1:] - l[1:],
                        np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        return float(np.mean(tr))

    @staticmethod
    def _calc_adx(highs, lows, closes, period=14):
        h = np.array(highs, dtype=float)
        l = np.array(lows, dtype=float)
        c = np.array(closes, dtype=float)
        if len(c) < period + 1:
            return 0.0
        up_move = h[1:] - h[:-1]
        down_move = l[:-1] - l[1:]
        plus_dm = np.where(up_move > down_move, up_move, 0.0)
        minus_dm = np.where(down_move > up_move, down_move, 0.0)
        tr_list = np.maximum(h[1:] - l[1:], np.abs(c[1:] - c[:-1]))
        if len(tr_list) < period:
            return 0.0
        atr_smooth = float(np.mean(tr_list[:period]))
        plus_dm_smooth = float(np.mean(plus_dm[:period]))
        minus_dm_smooth = float(np.mean(minus_dm[:period]))
        for i in range(period, len(tr_list)):
            atr_smooth = (atr_smooth * (period - 1) + tr_list[i]) / period
            plus_dm_smooth = (plus_dm_smooth * (period - 1) + plus_dm[i]) / period
            minus_dm_smooth = (minus_dm_smooth * (period - 1) + minus_dm[i]) / period
        plus_di = (plus_dm_smooth / atr_smooth * 100) if atr_smooth > 0 else 0
        minus_di = (minus_dm_smooth / atr_smooth * 100) if atr_smooth > 0 else 0
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di) * 100) if (plus_di + minus_di) > 0 else 0
        adx_vals = [dx] * period
        return float(np.mean(adx_vals))

    @staticmethod
    def _calc_cmf(closes, highs, lows, volumes, period=20):
        c = np.array(closes, dtype=float)
        h = np.array(highs, dtype=float)
        l = np.array(lows, dtype=float)
        v = np.array(volumes, dtype=float)
        if len(c) < period + 1:
            return 0.0
        hl_diff = h - l
        mf_multiplier = np.where(hl_diff != 0, ((c - l) - (h - c)) / hl_diff, 0.0)
        mf_volume = mf_multiplier * v
        cmf = np.sum(mf_volume[-period:]) / np.sum(v[-period:]) if np.sum(v[-period:]) > 0 else 0.0
        return float(cmf)

    @staticmethod
    def _calc_williams_r(highs, lows, closes, period=14):
        h = np.array(highs, dtype=float)
        l = np.array(lows, dtype=float)
        c = np.array(closes, dtype=float)
        if len(c) < period:
            return -50.0
        period_high = np.max(h[-(period):])
        period_low = np.min(l[-(period):])
        if period_high == period_low:
            return -50.0
        wr = (period_high - c[-1]) / (period_high - period_low) * -100
        return float(wr)

    def _judge_ma_trend(self, price: float, ma5: float, ma10: float, ma20: float) -> str:
        if price > ma5 > ma10 > ma20:
            return "多头排列"
        elif price < ma5 < ma10 < ma20:
            return "空头排列"
        return "震荡整理"

    def _judge_volume(self, volume: int, avg_volume: int) -> str:
        if volume > avg_volume * 1.5:
            return "放量"
        elif volume < avg_volume * 0.5:
            return "缩量"
        return "量能平稳"

    @staticmethod
    def _calc_ma_biass(closes, period=5):
        c = np.array(closes, dtype=float)
        if len(c) < period:
            return 0.0
        ma = np.mean(c[-period:])
        if ma == 0:
            return 0.0
        return float((c[-1] - ma) / ma * 100)

    @staticmethod
    def _calc_histogram_slope(histogram, n=5):
        h = np.array(histogram, dtype=float)
        if len(h) < n + 1:
            return 0.0
        recent = h[-n:]
        earlier = h[-n*2:-n]
        if len(earlier) == 0:
            return 0.0
        slope = (np.mean(recent) - np.mean(earlier)) / (np.abs(np.mean(earlier)) + 1e-9)
        return float(slope)

    def _calculate_sentiment(self, code: str, market: str) -> dict[str, Any]:
        """计算市场情绪（基于财联社新闻）"""
        try:
            from src.data.news import NewsAggregator

            news_agg = NewsAggregator()
            news_list = news_agg.get_hot_news(max_items=50)

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
        if "放量上涨" in vol_status:
            score += 10
        elif "放量下跌" in vol_status:
            score -= 10

        return max(0.0, min(100.0, score))

    def _score_fundamental(self, fundamental: dict[str, Any]) -> float:
        score = 50.0

        indicators = fundamental.get("financial_indicators", {})
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

        # L2: 周K数据（A股中期，从新浪日K resample 避免 AkShare/East Money 依赖）
        if market in ("SH", "SZ"):
            try:
                prefix = 'sh' if market == 'SH' else 'sz'
                import requests
                url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                       f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=5&datalen=400")
                resp = requests.get(url, timeout=10)
                weekly_df = pd.DataFrame()
                if resp.status_code == 200 and resp.text.strip():
                    import json
                    daily_data = json.loads(resp.text)
                    if daily_data and len(daily_data) >= 50:
                        df = pd.DataFrame([{
                            '日期': item.get('day', '')[:10],
                            '开盘': float(item.get('open', 0)),
                            '收盘': float(item.get('close', 0)),
                            '最高': float(item.get('high', 0)),
                            '最低': float(item.get('low', 0)),
                            '成交量': int(float(item.get('volume', 0))),
                        } for item in daily_data])
                        df['日期'] = pd.to_datetime(df['日期'])
                        weekly_df = df.set_index('日期').resample('W').agg({
                            '开盘': 'first', '收盘': 'last',
                            '最高': 'max', '最低': 'min',
                            '成交量': 'sum'
                        }).dropna()
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
            except Exception as e:
                result['warnings'].append(f"L2计算异常: {str(e)[:50]}")

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
            text = self._build_ai_prompt(report, position_data)
            return self._call_llm(text, stream_callback=stream_callback)
        except Exception as e:
            print(f"[AI] generate_ai_analysis error: {e}")
            return "(AI分析异常)"

    def _build_ai_prompt(self, r: dict, position_data: dict = None) -> str:
        scores = r.get('scores', {})
        tech = r.get('technical', {})
        fund = r.get('fundamental', {})
        sent = r.get('sentiment', {})
        signals = r.get('signals', [])
        price_info = r.get('price_info', {})
        quote = r.get('quote', {})
        name = r.get('name', r.get('code', ''))
        code = r.get('code', '')

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
        fin_list = []
        for k, v in list(indicators.items())[:15]:
            fin_list.append(f"{k}: {v}")
        fin_text = '\n'.join(fin_list) if fin_list else "数据暂缺"

        current_price = quote.get('price') or price_info.get('current_price', 0) or tech.get('price', 0)
        change_pct = quote.get('change_pct') or price_info.get('change_percent', 0) or tech.get('change_pct', 0)

        return f"""你是一位专业的A股股票分析师。请基于以下数据生成一份完整的股票分析报告，格式参考给出的示例。

股票信息：
- 股票名称：{name}
- 股票代码：{code}
- 当前价格：¥{current_price}
- 涨跌幅：{change_pct}%

{position_context}综合评分：{scores.get('comprehensive_score', 0)}/100
技术评分：{scores.get('technical_score', 0)}/100
基本面评分：{scores.get('fundamental_score', 0)}/100
情绪评分：{scores.get('sentiment_score', 0)}/100

技术指标：
- RSI：{tech.get('rsi', 'N/A')}
- MA趋势：{tech.get('ma_trend', 'N/A')}
- MACD：{tech.get('macd_signal', 'N/A')}
- KDJ：K={tech.get('kdj',{}).get('k','N/A')} D={tech.get('kdj',{}).get('d','N/A')} J={tech.get('kdj',{}).get('j','N/A')}
- 布林带位置：{tech.get('bollinger_position', 'N/A')}
- 成交量比：{tech.get('volume_ratio', 'N/A')}
- 成交量状态：{tech.get('volume_status', 'N/A')}

财务指标（部分）：
{fin_text}

市场情绪：
- 情绪趋势：{sent.get('sentiment_trend', 'N/A')}
- 新闻数量：{sent.get('total_analyzed', 0)}条
- 正面/负面：{sent.get('positive_ratio', 0):.0%}/{sent.get('negative_ratio', 0):.0%}
- 数据来源：{', '.join(sent.get('news_sources', ['未知']))}
- 置信度：{(sent.get('confidence_score', 0) * 100):.0f}%

交易信号：
{sig_text}

建议：{r.get('recommendation', '')}。理由：{r.get('reason', '')}

请生成以下格式的完整分析报告（不少于800字）：

### 一、财务健康度深度解读
[内容]

### 二、技术面精准分析
[内容]

### 三、市场情绪深度挖掘
[内容]

### 四、基本面价值判断
[内容]

### 五、综合投资策略
[内容]

### 六、风险与机会识别
[内容]

### 结论总结
[内容]"""

    def _call_llm(self, prompt: str, stream_callback=None) -> str:
        """调用LLM API，支持任意OpenAI兼容提供商。通过配置文件切换模型。"""
        import json, os, logging
        logger = logging.getLogger(__name__)

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

        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)

            if stream_callback:
                stream = client.chat.completions.create(
                    model=model,
                    messages=[{"role":"user","content":prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True
                )
                full = ""
                for chunk in stream:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        content = delta.content
                        full += content
                        stream_callback(content)
                return full
            else:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role":"user","content":prompt}],
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                return resp.choices[0].message.content
        except Exception as e:
            err_msg = str(e)
            logger.error(f"[AI] [{provider}] 调用失败: {err_msg[:100]}")
            # 认证失败时尝试其他有key的提供商
            # MiniMax: 旧版端点不支持OpenAI格式，用原生请求
            if 'minimax' in provider.lower() and ('401' in err_msg or '404' in err_msg):
                logger.info("[AI] MiniMax OpenAI端点失败，尝试旧版API")
                try:
                    import requests as _req
                    legacy_url = base_url.rstrip('/v1').rstrip('/') + '/v1/text/chatcompletion'
                    payload = {
                        "model": model,
                        "messages": [{"sender_type":"USER","sender_name":"user","text": prompt}],
                        "tokens_to_generate": max_tokens,
                        "temperature": temperature,
                    }
                    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
                    resp = _req.post(legacy_url, json=payload, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        result = resp.json()
                        reply = result.get('reply', '') or result.get('choices',[{}])[0].get('text','') or result.get('data',{}).get('reply','')
                        return reply
                except Exception as mini_err:
                    logger.error(f"[AI] MiniMax旧版API也失败: {mini_err}")

            # 认证失败时尝试其他有key的提供商
            if '401' in err_msg or 'Authentication' in err_msg or 'auth' in err_msg.lower():
                for fallback_provider, key in api_keys.items():
                    if key and key != api_key and fallback_provider not in ('notes',):
                        logger.info(f"[AI] [{provider}] 认证失败，切换到 {fallback_provider}")
                        provider = fallback_provider
                        api_key = key
                        model = ai_cfg.get('models', {}).get(provider, 'gpt-4o-mini')
                        base_url = ai_cfg.get('api_base_urls', {}).get(provider, 'https://api.openai.com/v1')
                        base_url = base_url.strip().rstrip('/')
                        if not base_url.startswith('http'):
                            base_url = 'https://' + base_url
                        try:
                            client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)
                            resp = client.chat.completions.create(
                                model=model, messages=[{"role":"user","content":prompt}],
                                max_tokens=max_tokens, temperature=temperature)
                            return resp.choices[0].message.content
                        except:
                            continue
            return f"(AI分析暂时不可用: {err_msg[:60]})"

__all__ = ['StockAnalyzer']