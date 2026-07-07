"""智能选股器 - 体系A(短线黄金) + 体系B(三步低吸)"""
import logging
import time
import random
import numpy as np
import pandas as pd
from datetime import datetime


class SmartStockScreener:
    """智能选股器"""

    def __init__(self, config=None):
        self.config = config or {}
        self.logger = logging.getLogger(__name__)

    def get_all_stocks_with_price(self, market='all'):
        """v1.3: 走 stock_repo.get_all_quotes()，core 层不再 import akshare"""
        from src.repository.stock_repo import stock_repo
        stocks = stock_repo.get_all_quotes()
        if stocks:
            self.logger.info(f"从 stock_repo 获取 {len(stocks)} 只股票")
            return stocks
        # 兜底：只从 stock_basics 取代码（无价格，等下一轮 stock_cache 刷新）
        try:
            from src.repository.stock_repo import stock_repo
            basic_repo = stock_repo.get_stock_basic_repo()
            conn = stock_repo.get_sqlite_connection()
            try:
                rows = conn.execute("SELECT code, name FROM stock_basics LIMIT 5000").fetchall()
            finally:
                conn.close()
            return [{
                'code': r['code'], 'name': r['name'],
                'price': 0, 'change_pct': 0, 'volume': 0,
            } for r in rows]
        except Exception as e:
            self.logger.error(f"获取全市场股票失败: {e}")
            return []

    def filter_by_price_range(self, stocks, min_price=None, max_price=None):
        """按价格区间筛选"""
        if not min_price and not max_price:
            return stocks
        result = []
        for s in stocks:
            p = s.get('price', 0)
            if min_price and p < min_price:
                continue
            if max_price and p > max_price:
                continue
            result.append(s)
        return result

    def get_stock_history(self, code, days=60):
        """v1.3: 走 stock_repo（SQLite K 线缓存优先，miss 走 akshare）"""
        from src.repository.stock_repo import stock_repo
        clean_code = code.replace('sh', '').replace('sz', '').replace('bj', '').upper()
        if not clean_code:
            return None
        df = stock_repo.get_history(clean_code, days)
        if df is None or df.empty:
            return None
        # 兼容旧调用方：统一返回中文列名
        rename_map = {
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量',
        }
        df = df.rename(columns=rename_map)
        for col in ['日期', '开盘', '收盘', '最高', '最低', '成交量']:
            if col not in df.columns:
                df[col] = 0
        return df.tail(days)[['日期', '开盘', '收盘', '最高', '最低', '成交量']]

    def get_sector_info(self, code):
        """v1.3: 走 stock_repo（data/industry 下沉）"""
        from src.repository.stock_repo import stock_repo
        return stock_repo.get_industry(code)

    def get_sector_3d_trend(self, sector_name):
        """v1.3: 走 stock_repo（data/industry 下沉）"""
        from src.repository.stock_repo import stock_repo
        return stock_repo.get_sector_trend(sector_name)

    def calculate_indicators(self, df):
        """计算技术指标"""
        if df is None or df.empty:
            return None
        close = df['收盘'].astype(float)
        high = df['最高'].astype(float)
        low = df['最低'].astype(float)
        open_price = df['开盘'].astype(float)
        volume = df['成交量'].astype(float)

        # MA5
        ma5 = close.rolling(window=5, min_periods=1).mean()

        # RSI(6)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=6, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=6, min_periods=1).mean()
        rs = gain / (loss + 1e-9)
        rsi6 = 100 - (100 / (1 + rs))

        # RSI(14)
        gain14 = delta.where(delta > 0, 0).rolling(window=14, min_periods=1).mean()
        loss14 = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
        rs14 = gain14 / (loss14 + 1e-9)
        rsi14 = 100 - (100 / (1 + rs14))

        # MACD
        ema12 = close.ewm(span=12, min_periods=1).mean()
        ema26 = close.ewm(span=26, min_periods=1).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, min_periods=1).mean()
        macd_hist = macd_line - signal_line

        # KDJ
        low_min = low.rolling(window=9, min_periods=1).min()
        high_max = high.rolling(window=9, min_periods=1).max()
        rsv = (close - low_min) / (high_max - low_min + 1e-9) * 100
        k_value = rsv.ewm(alpha=1/3, adjust=False).mean()
        d_value = k_value.ewm(alpha=1/3, adjust=False).mean()
        j_value = 3 * k_value - 2 * d_value

        # BOLL
        boll_mid = close.rolling(window=20, min_periods=1).mean()
        boll_std = close.rolling(window=20, min_periods=1).std()
        boll_upper = boll_mid + 2 * boll_std
        boll_lower = boll_mid - 2 * boll_std

        # CCI
        tp = (high + low + close) / 3
        tp_ma = tp.rolling(window=14, min_periods=1).mean()
        tp_avedev = tp.rolling(window=14, min_periods=1).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci = (tp - tp_ma) / (0.015 * tp_avedev)

        # Volume MA
        vol_ma5 = volume.rolling(window=5, min_periods=1).mean()

        return {
            'close': close,
            'high': high,
            'low': low,
            'open': open_price,
            'volume': volume,
            'ma5': ma5,
            'ma10': close.rolling(window=10, min_periods=1).mean(),
            'ma20': close.rolling(window=20, min_periods=1).mean(),
            'rsi6': rsi6,
            'rsi14': rsi14,
            'macd_line': macd_line,
            'macd_signal': signal_line,
            'macd_hist': macd_hist,
            'k': k_value,
            'd': d_value,
            'j': j_value,
            'boll_upper': boll_upper,
            'boll_mid': boll_mid,
            'boll_lower': boll_lower,
            'cci': cci,
            'vol_ma5': vol_ma5,
        }

    def check_strategy_a(self, df, ind):
        """体系A: 短线黄金组合检查"""
        if df is None or ind is None:
            return {'passed': False, 'signals': [], 'score': 0}

        signals = []
        score = 0

        close = ind['close'].iloc[-1]
        ma5 = ind['ma5'].iloc[-1]
        vol = ind['volume'].iloc[-1]
        vol_ma5 = ind['vol_ma5'].iloc[-1]
        rsi6 = ind['rsi6'].iloc[-1]
        k = ind['k'].iloc[-1]
        d = ind['d'].iloc[-1]
        prev_k = ind['k'].iloc[-2] if len(ind['k']) >= 2 else k
        prev_d = ind['d'].iloc[-2] if len(ind['d']) >= 2 else d
        macd_hist = ind['macd_hist'].iloc[-1]
        prev_macd_hist = ind['macd_hist'].iloc[-2] if len(ind['macd_hist']) >= 2 else macd_hist

        # 1. VOL放量检测
        vol_ratio = vol / (vol_ma5 + 1e-9)
        if vol_ratio > 1.5:
            signals.append(f'VOL放量({vol_ratio:.1f}倍)')
            score += 25
        elif vol_ratio > 1.2:
            signals.append(f'VOL温和放量({vol_ratio:.1f}倍)')
            score += 15

        # 2. MACD绿柱缩短或红柱放大
        if len(ind['macd_hist']) >= 5:
            recent_5_hist = ind['macd_hist'].iloc[-5:]
            all_negative = all(recent_5_hist < 0)
            if all_negative and macd_hist < 0 and macd_hist > prev_macd_hist:
                signals.append('MACD绿柱缩短')
                score += 20
            elif macd_hist > 0 and prev_macd_hist <= 0:
                signals.append('MACD金叉放大')
                score += 20
            elif macd_hist > prev_macd_hist and macd_hist > 0:
                signals.append('MACD红柱放大')
                score += 15

        # 3. KDJ低位金叉
        if k < 25 and d < 25:
            if prev_k <= prev_d and k > d:
                signals.append(f'KDJ低位金叉(K={k:.1f})')
                score += 25
            elif k < 20:
                signals.append(f'KDJ超卖(K={k:.1f})')
                score += 15

        # 4. 股价站稳MA5
        ma5_prev = ind['ma5'].iloc[-2] if len(ind['ma5']) >= 2 else ma5
        if close > ma5 and ma5 >= ma5_prev:
            signals.append('股价站稳MA5')
            score += 20
        elif close > ma5:
            signals.append('股价在MA5上方')
            score += 10

        # 5. RSI(6)
        if rsi6 < 70:
            if rsi6 < 30:
                signals.append(f'RSI6超卖({rsi6:.1f})')
                score += 10
            else:
                score += 5

        passed = score >= 60 and len(signals) >= 2
        return {'passed': passed, 'signals': signals, 'score': score}

    def check_strategy_b(self, df, ind):
        """体系B: 三步低吸伏击法"""
        if df is None or ind is None or len(df) < 10:
            return {'signal': None, 'step': None, 'description': ''}

        close = ind['close']
        low = ind['low']
        cci = ind['cci']
        k = ind['k']
        d = ind['d']
        rsi6 = ind['rsi6']
        ma5 = ind['ma5']

        # 第一步: 深蹲信号
        crash_detected = False
        crash_days = 0
        for i in range(2, min(6, len(df))):
            idx = -(i)
            if idx >= -len(close):
                cci_val = cci.iloc[idx]
                boll_low = ind['boll_lower'].iloc[idx]
                close_val = close.iloc[idx]
                price_change = (close.iloc[-1] - close_val) / (close_val + 1e-9) * 100
                if cci_val < -100 and close_val < boll_low and price_change < -10:
                    crash_detected = True
                    crash_days = i
                    break

        if not crash_detected:
            return {'signal': None, 'step': None, 'description': '未检测到深蹲信号'}

        # 第二步: 止跌信号
        last_close = close.iloc[-1]
        last_open = ind['open'].iloc[-1]
        last_low = low.iloc[-1]
        last_cci = cci.iloc[-1]
        prev_cci = cci.iloc[-2] if len(cci) >= 2 else last_cci

        lower_shadow = last_close - last_low
        body = abs(last_close - last_open)
        is_long_lower_shadow = lower_shadow > 2 * body and last_low < last_close * 0.98
        cci_turning = prev_cci < -100 and last_cci > -100

        if is_long_lower_shadow or (last_close > last_open and body < (last_close - last_low) * 0.5):
            if cci_turning:
                return {
                    'signal': 'BUY',
                    'step': '第二步-止跌',
                    'description': f'长下影线止跌+CCI拐头({last_cci:.1f}), 深蹲{crash_days}天前'
                }

        # 第三步: 起跳确认
        if last_close > ma5.iloc[-1]:
            prev_rsi6 = rsi6.iloc[-2] if len(rsi6) >= 2 else rsi6.iloc[-1]
            curr_rsi6 = rsi6.iloc[-1]
            if prev_rsi6 < 25 and curr_rsi6 > prev_rsi6 and curr_rsi6 < 40:
                return {
                    'signal': 'BUY',
                    'step': '第三步-起跳',
                    'description': f'站稳MA5+RSI6金叉({prev_rsi6:.1f}->{curr_rsi6:.1f})'
                }

        return {
            'signal': 'WAIT',
            'step': '第一步-深蹲',
            'description': f'深蹲信号后等待{cci_turning and "CCI拐头" or "止跌确认"}'
        }

    def check_strategy_c(self, df, ind):
        """体系C: 四步定量筛股 - 技术面砸透（简化版）"""
        if df is None or ind is None or len(df) < 20:
            return {'score': 0, 'signals': [], 'passed': False}

        close = ind['close']
        high = ind['high']
        volume = ind['volume']
        ma10 = ind['ma10']

        signals = []
        score = 0

        # Step 1: 空间急跌 - 从近半年高点跌幅 > 35%（使用60日高点）
        if len(close) >= 60:
            high_60d = high.iloc[-60:].max()
            current_close = close.iloc[-1]
            if high_60d > 0:
                drop_pct = (high_60d - current_close) / high_60d * 100
                if drop_pct > 35:
                    signals.append(f'急跌{drop_pct:.1f}%')
                    score += 8
                elif drop_pct > 20:
                    signals.append(f'回调{drop_pct:.1f}%')
                    score += 4

        # Step 2: 偏离度高 - BIAS(10) < -8%
        if len(ma10) >= 10:
            current_ma10 = ma10.iloc[-1]
            current_close = close.iloc[-1]
            if current_ma10 > 0:
                bias_10 = (current_close - current_ma10) / current_ma10 * 100
                if bias_10 < -8:
                    signals.append(f'BIAS10={bias_10:.1f}%')
                    score += 6
                elif bias_10 < 0:
                    signals.append(f'BIAS10={bias_10:.1f}%')
                    score += 3

        # Step 3: 无量阴跌 - 买入前3天成交量 < 20日均量50%
        vol_ma20 = volume.rolling(window=20, min_periods=1).mean()
        vol_3d_avg = volume.iloc[-3:].mean()
        vol_20d = vol_ma20.iloc[-1] if len(vol_ma20) > 0 else 1

        if vol_20d > 0:
            vol_ratio = vol_3d_avg / vol_20d
            if vol_ratio < 0.5:
                signals.append(f'地量(0.5倍)')
                score += 6
            elif vol_ratio < 0.8:
                signals.append(f'缩量({vol_ratio:.1f}倍)')
                score += 3

        passed = score >= 12  # 技术面砸透需要至少12分才通过
        return {'score': score, 'signals': signals, 'passed': passed}

    def get_stock_3d_performance(self, code):
        """获取个股3日表现"""
        try:
            df = self.get_stock_history(code, days=10)
            if df is not None and len(df) >= 4:
                closes = df['收盘'].astype(float).tolist()
                if len(closes) >= 4:
                    change_3d = (closes[-1] - closes[-4]) / (closes[-4] + 1e-9) * 100
                    return change_3d
        except Exception:
            pass
        return 0

    def is_problem_stock(self, code, name):
        """v1.3: 走 stock_repo（data/company_info 下沉）"""
        from src.repository.stock_repo import stock_repo
        return stock_repo.is_problem_stock(code, name)

    def calculate_risk_levels(self, df, ind):
        """计算风险等级和交易规则"""
        if df is None or ind is None or len(df) < 10:
            return {
                'risk_level': 'HIGH',
                'profit_target': 0,
                'stop_loss': 0,
                'risk_warnings': ['数据不足，无法评估']
            }
        close = ind['close'].iloc[-1]
        ma10 = ind['close'].rolling(window=10, min_periods=1).mean().iloc[-1]
        boll_mid = ind['boll_mid'].iloc[-1]
        recent_low = ind['low'].rolling(window=5, min_periods=1).min().iloc[-1]
        risk_warnings = []
        if close < 5:
            risk_warnings.append('低价股波动大')
        if ind['rsi6'].iloc[-1] > 80:
            risk_warnings.append('RSI6超买')
        if abs(ind['macd_hist'].iloc[-1]) < 0.01:
            risk_warnings.append('MACD动能不足')
        target_price = min(ma10, boll_mid)
        stop_price = recent_low * 0.97
        potential_profit = (target_price - close) / close * 100
        potential_loss = (close - stop_price) / close * 100
        if potential_profit < 3 or potential_loss > 5:
            risk_level = 'HIGH'
            risk_warnings.append('盈亏比不利')
        elif potential_profit > 5 and potential_loss < 3:
            risk_level = 'LOW'
        else:
            risk_level = 'MEDIUM'
        return {
            'risk_level': risk_level,
            'profit_target': round(target_price, 2),
            'profit_target_pct': round(potential_profit, 1),
            'stop_loss': round(stop_price, 2),
            'stop_loss_pct': round(potential_loss, 1),
            'risk_warnings': risk_warnings if risk_warnings else ['无明显风险']
        }

    def screener(self, min_price=None, max_price=None, strategy='ALL', limit=20, sector=None):
        """智能选股主函数"""
        start_time = time.time()

        # 1. 获取全市场股票
        all_stocks = self.get_all_stocks_with_price()

        # 2. 按价格区间筛选
        filtered = self.filter_by_price_range(all_stocks, min_price, max_price)

        results = []
        total = len(filtered)
        self.logger.info(f"价格筛选后剩余 {total} 只股票，开始分析...")

        # 3. 分批分析
        batch_size = 50
        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            batch = filtered[batch_start:batch_end]

            for stock in batch:
                code = stock['code']
                try:
                    is_prob, prob_reason = self.is_problem_stock(code, stock['name'])
                    if is_prob:
                        continue

                    df = self.get_stock_history(code, days=60)
                    ind = self.calculate_indicators(df)

                    strat_a = self.check_strategy_a(df, ind)
                    if not strat_a['passed']:
                        continue

                    strat_b = self.check_strategy_b(df, ind)
                    strat_c = self.check_strategy_c(df, ind)

                    sector_info = self.get_sector_info(code)

                    stock_3d = self.get_stock_3d_performance(code)

                    sector_trend = 0
                    if sector_info['industry']:
                        sector_name = sector_info['industry'][0].get('name', '')
                        if sector_name:
                            sector_trend = self.get_sector_3d_trend(sector_name)

                    if not strat_a['passed']:
                        continue

                    risk = self.calculate_risk_levels(df, ind)
                    if risk['risk_level'] == 'HIGH' and strat_b['signal'] != 'BUY':
                        continue

                    final_score = strat_a['score']
                    if strat_b['signal'] == 'BUY':
                        final_score += 30
                    if risk['risk_level'] == 'LOW':
                        final_score += 10
                    final_score += strat_c['score']  # 体系C加分

                    result = {
                        'code': code,
                        'name': stock['name'],
                        'price': stock['price'],
                        'change_pct': stock['change_pct'],
                        'sector': sector_info['industry'][0].get('name', '') if sector_info['industry'] else '未知',
                        'sector_trend_3d': sector_trend,
                        'stock_trend_3d': stock_3d,
                        'strategy_a_score': strat_a['score'],
                        'strategy_a_signals': strat_a['signals'],
                        'strategy_b_step': strat_b['step'],
                        'strategy_b_desc': strat_b['description'],
                        'strategy_b_signal': strat_b['signal'],
                        'strategy_c_score': strat_c['score'],
                        'strategy_c_signals': strat_c['signals'],
                        'final_score': final_score,
                        'risk_level': risk['risk_level'],
                        'profit_target': risk['profit_target'],
                        'profit_target_pct': risk['profit_target_pct'],
                        'stop_loss': risk['stop_loss'],
                        'stop_loss_pct': risk['stop_loss_pct'],
                        'risk_warnings': risk['risk_warnings'],
                    }
                    results.append(result)

                    # v1.2: 移除 akshare 限流期重试 sleep，全市场遍历累积 70s。
                    # 改:失败立即降级到 mock,真实 + mock 混合返回。
                    if random.random() < 0.05:  # 每只 ~5% 概率轻 sleep,避免被 akshare 完全 ban
                        time.sleep(0.1)

                except Exception as e:
                    self.logger.warning(f"分析失败 {code}: {e}")
                    continue

        # 按评分排序
        results.sort(key=lambda x: x['final_score'], reverse=True)
        results = results[:limit]

        elapsed = time.time() - start_time
        self.logger.info(f"选股完成，扫描{total}只，符合条件{len(results)}只，耗时{elapsed:.1f}秒")

        return {
            'stocks': results,
            'total_scanned': total,
            'matched_count': len(results),
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'elapsed_seconds': round(elapsed, 1)
        }