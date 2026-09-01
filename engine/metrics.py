"""
Metricas estandar para evaluar resultados de backtest.
Usado por engine/backtester.py y por los agentes Backtest/Rules-Guard.
"""
import pandas as pd
import numpy as np


def compute_trade_metrics(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": None,
            "avg_r": None,
            "expectancy_usd": None,
            "expectancy_pct": None,
            "max_consecutive_losses": 0,
        }

    wins = trades[trades["pnl_usd"] > 0]

    win_rate = len(wins) / len(trades) * 100
    avg_r = trades["r_multiple"].mean()
    expectancy_usd = trades["pnl_usd"].mean()

    max_consec = 0
    current = 0
    for pnl in trades["pnl_usd"]:
        if pnl < 0:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0

    return {
        "total_trades": len(trades),
        "win_rate": round(win_rate, 2),
        "avg_r": round(avg_r, 3),
        "expectancy_usd": round(expectancy_usd, 2),
        "expectancy_pct": round(expectancy_usd / 10000 * 100, 4),
        "max_consecutive_losses": max_consec,
    }


def compute_equity_metrics(daily_pnl: pd.DataFrame, account_size: float = 10000.0) -> dict:
    if daily_pnl.empty:
        return {
            "cagr_pct": None,
            "max_drawdown_usd": None,
            "max_drawdown_pct": None,
            "sharpe": None,
            "worst_day_usd": None,
            "worst_day_date": None,
        }

    df = daily_pnl.sort_values("date").copy()
    df["equity"] = account_size + df["pnl_usd"].cumsum()
    df["running_max"] = df["equity"].cummax()
    df["drawdown_usd"] = df["equity"] - df["running_max"]
    df["drawdown_pct"] = df["drawdown_usd"] / df["running_max"] * 100

    max_dd_usd = df["drawdown_usd"].min()
    max_dd_pct = df["drawdown_pct"].min()

    n_days = len(df)
    years = max(n_days / 252, 1e-6)
    final_equity = df["equity"].iloc[-1]
    cagr = ((final_equity / account_size) ** (1 / years) - 1) * 100 if final_equity > 0 else -100

    daily_returns = df["pnl_usd"] / account_size
    sharpe = (
        (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
        if daily_returns.std() > 0
        else 0.0
    )

    worst_idx = df["pnl_usd"].idxmin()
    worst_day_usd = df.loc[worst_idx, "pnl_usd"]
    worst_day_date = df.loc[worst_idx, "date"]

    return {
        "cagr_pct": round(cagr, 2),
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": round(sharpe, 2),
        "worst_day_usd": round(worst_day_usd, 2),
        "worst_day_date": str(worst_day_date),
    }
