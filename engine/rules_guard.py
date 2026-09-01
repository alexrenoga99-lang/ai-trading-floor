"""
Rules-Guard Agent (version ejecutable). Evalua el daily_pnl.csv de una
estrategia contra el perfil de riesgo personal de $10,000.

Uso:
    python engine/rules_guard.py --results results/nas100_ob_choch_v1
"""
import argparse
import json
from pathlib import Path

import pandas as pd

PROFILE = {
    "account_size": 10000,
    "risk_per_trade_usd": 100,
    "daily_loss_limit_usd": -250,
    "max_losing_trades_per_day": 3,
    "weekly_drawdown_alarm_usd": -600,
}


def evaluate(daily_pnl: pd.DataFrame, trades: pd.DataFrame) -> dict:
    breach_events = []

    daily_breaches = daily_pnl[daily_pnl["pnl_usd"] <= PROFILE["daily_loss_limit_usd"]]
    for _, row in daily_breaches.iterrows():
        breach_events.append({"date": str(row["date"]), "type": "daily_loss", "value_usd": row["pnl_usd"]})

    max_consecutive_losses = 0
    if not trades.empty:
        trades = trades.copy()
        trades["date"] = pd.to_datetime(trades["exit_date"]).dt.date
        for date, group in trades.groupby("date"):
            streak = 0
            max_streak_day = 0
            for pnl in group["pnl_usd"]:
                if pnl < 0:
                    streak += 1
                    max_streak_day = max(max_streak_day, streak)
                else:
                    streak = 0
            max_consecutive_losses = max(max_consecutive_losses, max_streak_day)
            if max_streak_day > PROFILE["max_losing_trades_per_day"]:
                breach_events.append({"date": str(date), "type": "consecutive_losses", "value": max_streak_day})

    weekly_breach = False
    if not daily_pnl.empty:
        daily_pnl_sorted = daily_pnl.sort_values("date").reset_index(drop=True)
        daily_pnl_sorted["rolling_5d"] = daily_pnl_sorted["pnl_usd"].rolling(5, min_periods=1).sum()
        weekly_min = daily_pnl_sorted["rolling_5d"].min()
        if weekly_min <= PROFILE["weekly_drawdown_alarm_usd"]:
            weekly_breach = True
            breach_events.append({"type": "weekly_drawdown", "value_usd": round(weekly_min, 2)})

    worst_day_usd = daily_pnl["pnl_usd"].min() if not daily_pnl.empty else 0
    total_days = len(daily_pnl) if not daily_pnl.empty else 1
    breached_days = len(daily_breaches)
    sessions_survived_pct = round((1 - breached_days / total_days) * 100, 2)

    would_have_breached_daily = len(daily_breaches) > 0

    if would_have_breached_daily or weekly_breach:
        verdict = "FAIL"
    elif worst_day_usd <= PROFILE["daily_loss_limit_usd"] * 0.8:
        verdict = "PASS_WITH_WARNING"
    else:
        verdict = "PASS"

    return {
        "would_have_breached_daily": would_have_breached_daily,
        "would_have_breached_weekly": weekly_breach,
        "breach_events": breach_events,
        "worst_day_usd": round(worst_day_usd, 2),
        "max_consecutive_losses": max_consecutive_losses,
        "sessions_survived_pct": sessions_survived_pct,
        "verdict": verdict,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, help="carpeta results/{strategy_id}")
    args = parser.parse_args()

    results_dir = Path(args.results)
    daily_pnl = pd.read_csv(results_dir / "daily_pnl.csv")
    trades = pd.read_csv(results_dir / "trades.csv")

    verdict = evaluate(daily_pnl, trades)

    with open(results_dir / "rules_guard_verdict.json", "w") as f:
        json.dump(verdict, f, indent=2)

    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    main()
