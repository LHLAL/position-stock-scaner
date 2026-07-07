"""回测引擎 —— 策略回测与横向比较

v1.0 基础版：支持 6 种策略，输出核心绩效指标。
所有函数纯计算、无副作用，数据源从 stock_repo 获取。
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class TradeRecord:
    """单笔交易记录"""
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    direction: str  # 'long' | 'short'
    shares: float
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    """策略回测结果"""
    strategy_name: str
    total_return: float          # 总收益率 %
    annual_return: float         # 年化收益率 %
    win_rate: float              # 胜率 %
    total_trades: int            # 总交易次数
    winning_trades: int          # 盈利次数
    losing_trades: int           # 亏损次数
    max_drawdown: float          # 最大回撤 %
    sharpe: float                # 夏普比率
    profit_factor: float         # 盈亏比
    avg_win: float               # 平均盈利 %
    avg_loss: float              # 平均亏损 %
    best_trade: float            # 最佳交易 %
    worst_trade: float           # 最差交易 %
    buy_hold_return: float       # 买入持有收益率 %
    trades: List[TradeRecord] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)


# ── 策略函数 ──────────────────────────────

def strategy_rsi(df: pd.DataFrame, period: int = 14, oversold: float = 30, overbought: float = 70) -> List[int]:
    """RSI 均值回归：超卖买入，超买卖出"""
    closes = df['close'].values.astype(float)
    signals = [0] * len(closes)
    rsi = _calc_rsi_series(closes, period)
    for i in range(period + 1, len(closes)):
        if rsi[i-1] < oversold and rsi[i] >= oversold:
            signals[i] = 1      # 买入
        elif rsi[i-1] > overbought and rsi[i] <= overbought:
            signals[i] = -1     # 卖出
    return signals


def strategy_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> List[int]:
    """MACD 金叉死叉"""
    closes = df['close'].values.astype(float)
    signals = [0] * len(closes)
    from src.core.MyTT import MACD as mytt_macd
    dif, dea, macd_hist = mytt_macd(closes, fast, slow, signal)
    for i in range(1, len(closes)):
        if dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
            signals[i] = 1
        elif dif[i-1] >= dea[i-1] and dif[i] < dea[i]:
            signals[i] = -1
    return signals


def strategy_ema_cross(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> List[int]:
    """EMA 金叉死叉"""
    closes = df['close'].values.astype(float)
    signals = [0] * len(closes)
    ema_f = _ema(closes, fast)
    ema_s = _ema(closes, slow)
    for i in range(1, len(closes)):
        if ema_f[i-1] <= ema_s[i-1] and ema_f[i] > ema_s[i]:
            signals[i] = 1
        elif ema_f[i-1] >= ema_s[i-1] and ema_f[i] < ema_s[i]:
            signals[i] = -1
    return signals


def strategy_bollinger(df: pd.DataFrame, period: int = 20, std: float = 2) -> List[int]:
    """布林带均值回归：碰下轨买入，碰上轨卖出"""
    closes = df['close'].values.astype(float)
    signals = [0] * len(closes)
    ma = _sma(closes, period)
    sd = _std(closes, period)
    for i in range(period, len(closes)):
        upper = ma[i] + std * sd[i]
        lower = ma[i] - std * sd[i]
        if i > 0 and closes[i-1] <= lower and closes[i] > lower:
            signals[i] = 1
        elif i > 0 and closes[i-1] >= upper and closes[i] < upper:
            signals[i] = -1
    return signals


def strategy_trend_follow(df: pd.DataFrame, period: int = 20) -> List[int]:
    """趋势跟踪：价格在 MA 上方买入，下方卖出"""
    closes = df['close'].values.astype(float)
    signals = [0] * len(closes)
    ma = _sma(closes, period)
    for i in range(period + 1, len(closes)):
        if closes[i-1] <= ma[i-1] and closes[i] > ma[i]:
            signals[i] = 1
        elif closes[i-1] >= ma[i-1] and closes[i] < ma[i]:
            signals[i] = -1
    return signals


# ── 回测执行 ──────────────────────────────

def run_backtest(df: pd.DataFrame, strategy_fn: Callable, strategy_name: str, commission: float = 0.001) -> BacktestResult:
    """运行单策略回测"""
    closes = df['close'].values.astype(float)
    dates = df['date'].values if 'date' in df.columns else [str(i) for i in range(len(closes))]
    signals = strategy_fn(df)

    position = 0   # 0 空仓, 1 持仓
    cash = 1.0      # 初始 1 元
    shares = 0.0
    trades: List[TradeRecord] = []
    entry_price = 0.0
    entry_date = ''
    equity = [1.0]

    for i in range(len(closes)):
        price = closes[i]
        # 买入信号
        if signals[i] == 1 and position == 0:
            position = 1
            entry_price = price
            entry_date = str(dates[i])
            shares = cash * (1 - commission) / price
            cash = 0
        # 卖出信号
        elif signals[i] == -1 and position == 1:
            position = 0
            exit_price = price
            pnl = shares * exit_price * (1 - commission) - (cash + shares * entry_price)
            pnl_pct = (exit_price - entry_price) / entry_price - commission * 2
            trades.append(TradeRecord(
                entry_date=entry_date, exit_date=str(dates[i]),
                entry_price=entry_price, exit_price=exit_price,
                direction='long', shares=shares,
                pnl=pnl, pnl_pct=pnl_pct,
            ))
            cash = shares * exit_price * (1 - commission)
            shares = 0

        # 每日净值
        total_value = cash + shares * price if position else cash + shares * price
        equity.append(total_value)

    # 最后一天平仓
    if position == 1:
        cash = shares * closes[-1] * (1 - commission)
        equity[-1] = cash

    # 计算绩效
    equity_arr = np.array(equity)
    total_return = (equity_arr[-1] - 1.0) * 100

    # 买入持有收益率
    buy_hold_return = (closes[-1] / closes[0] - 1) * 100 if closes[0] > 0 else 0.0

    # 最大回撤
    peak = np.maximum.accumulate(equity_arr)
    drawdown = (peak - equity_arr) / peak * 100
    max_dd = float(np.max(drawdown))

    # 年化收益率 (假设 250 个交易日)
    years = len(closes) / 250
    annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100 if years > 0 else 0

    # 胜率
    winning = [t for t in trades if t.pnl_pct > 0]
    losing = [t for t in trades if t.pnl_pct <= 0]
    win_rate = len(winning) / len(trades) * 100 if trades else 0

    # 夏普比率
    daily_returns = np.diff(equity_arr) / equity_arr[:-1]
    sharpe = float(np.mean(daily_returns) / np.std(daily_returns) * np.sqrt(250)) if np.std(daily_returns) > 0 else 0

    # 盈亏比
    avg_win = np.mean([t.pnl_pct for t in winning]) * 100 if winning else 0
    avg_loss = abs(np.mean([t.pnl_pct for t in losing])) * 100 if losing else 0
    profit_factor = abs(np.sum([t.pnl_pct for t in winning]) / np.sum([abs(t.pnl_pct) for t in losing])) if losing and np.sum([abs(t.pnl_pct) for t in losing]) > 0 else 0

    best = max([t.pnl_pct for t in trades]) * 100 if trades else 0
    worst = min([t.pnl_pct for t in trades]) * 100 if trades else 0

    return BacktestResult(
        strategy_name=strategy_name,
        total_return=round(total_return, 2),
        annual_return=round(annual_return, 2),
        win_rate=round(win_rate, 1),
        total_trades=len(trades),
        winning_trades=len(winning),
        losing_trades=len(losing),
        max_drawdown=round(max_dd, 2),
        sharpe=round(sharpe, 2),
        profit_factor=round(profit_factor, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        best_trade=round(best, 2),
        worst_trade=round(worst, 2),
        buy_hold_return=round(buy_hold_return, 2),
        trades=trades,
        equity_curve=[round(e, 4) for e in equity],
    )


STRATEGIES = {
    'rsi': (strategy_rsi, 'RSI 均值回归'),
    'macd': (strategy_macd, 'MACD 金叉死叉'),
    'ema_cross': (strategy_ema_cross, 'EMA 金叉死叉'),
    'bollinger': (strategy_bollinger, '布林带均值回归'),
    'trend_follow': (strategy_trend_follow, '趋势跟踪'),
}


def compare_strategies(df: pd.DataFrame) -> Dict[str, BacktestResult]:
    """横向比较所有策略"""
    results = {}
    for key, (fn, name) in STRATEGIES.items():
        try:
            results[key] = run_backtest(df, fn, name)
        except Exception as e:
            results[key] = BacktestResult(strategy_name=name, total_return=0, annual_return=0,
                win_rate=0, total_trades=0, winning_trades=0, losing_trades=0,
                max_drawdown=0, sharpe=0, profit_factor=0, avg_win=0, avg_loss=0,
                best_trade=0, worst_trade=0, buy_hold_return=0)
    return results


# ── 内部工具函数 ──────────────────────────

def _calc_rsi_series(closes, period=14):
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_g = _sma_series(gains, period)
    avg_l = _sma_series(losses, period)
    avg_l = np.where(avg_l == 0, 0.001, avg_l)
    rs = avg_g / avg_l
    rsi = 100 - (100 / (1 + rs))
    result = np.full_like(closes, 50.0)
    result[period:] = rsi[period-1:-1]
    return result

def _sma_series(arr, window):
    result = np.full_like(arr, np.nan)
    cum = np.cumsum(arr)
    result[window-1:] = (cum[window-1:] - np.concatenate([[0], cum[:-window]])) / window
    return result

def _sma(arr, window):
    result = np.full_like(arr, np.nan)
    for i in range(len(arr)):
        if i >= window - 1:
            result[i] = np.mean(arr[i - window + 1:i + 1])
    return result

def _ema(arr, window):
    result = np.full_like(arr, np.nan)
    m = 2 / (window + 1)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = (arr[i] - result[i-1]) * m + result[i-1]
    return result

def _std(arr, window):
    result = np.full_like(arr, np.nan)
    for i in range(len(arr)):
        if i >= window - 1:
            result[i] = np.std(arr[i - window + 1:i + 1])
    return result
