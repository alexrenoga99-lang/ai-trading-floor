"""
Motor de backtest para la estrategia nas100_ob_choch_v1
(Order Block virgen + BOS/CHoCH multi-timeframe).

Uso:
    python engine/backtester.py --strategy strategies/nas100_ob_choch_v1.json \
        --structure-data data/nas100/nas100_1h.csv \
        --trigger-data data/nas100/nas100_5m.csv

Requisitos de los CSV de entrada (ambos):
    columnas: timestamp, open, high, low, close, volume
    timestamp en formato ISO parseable por pandas, orden cronologico ascendente.
"""
import argparse
import json
from pathlib import Path

import pandas as pd

from engine.structure import find_swings, detect_bos_choch, find_order_blocks
from engine.metrics import compute_trade_metrics, compute_equity_metrics


def load_ohlcv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.lower() for c in df.columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def is_rejection_candle(row) -> bool:
    body = abs(row["close"] - row["open"])
    upper_wick = row["high"] - max(row["close"], row["open"])
    lower_wick = min(row["close"], row["open"]) - row["low"]
    total_range = row["high"] - row["low"]
    if total_range == 0:
        return False
    if lower_wick > body * 2 and lower_wick > upper_wick:
        return True
    if upper_wick > body * 2 and upper_wick > lower_wick:
        return True
    return False


def run_backtest(strategy: dict, structure_df: pd.DataFrame, trigger_df: pd.DataFrame) -> dict:
    account_size = strategy.get("account_size", 10000)
    risk_amount = strategy.get("risk_amount_usd", 100)
    rr_fixed = strategy["reward_to_risk"]["fixed"]
    point_value = strategy.get("point_value", 1.0)

    structure_df = find_swings(structure_df)
    structure_df = detect_bos_choch(structure_df)
    order_blocks = find_order_blocks(structure_df)

    trigger_df = find_swings(trigger_df, lookback=2)
    trigger_df = detect_bos_choch(trigger_df)

    trades = []

    for ob in order_blocks:
        if ob["mitigated"]:
            continue

        ob_high, ob_low = ob["high"], ob["low"]
        event_time = structure_df["timestamp"].iloc[ob["event_index"]]

        future_trigger = trigger_df[trigger_df["timestamp"] > event_time].reset_index(drop=True)
        if future_trigger.empty:
            continue

        touched = False

        for k in range(1, len(future_trigger)):
            row = future_trigger.iloc[k]
            in_zone = (
                ob_low <= row["low"] <= ob_high
                or ob_low <= row["high"] <= ob_high
                or (row["low"] <= ob_low and row["high"] >= ob_high)
            )

            if not touched and in_zone:
                touched = True
                ob["mitigated"] = True

                rejection = is_rejection_candle(row)
                favorable_events = (
                    ("CHOCH_UP", "BOS_UP") if ob["direction"] == "bullish" else ("CHOCH_DOWN", "BOS_DOWN")
                )
                mini_choch = future_trigger["structure_event"].iloc[k] in favorable_events

                if rejection and mini_choch:
                    entry_price = row["close"]
                    stop_price = ob_low if ob["direction"] == "bullish" else ob_high
                    stop_points = abs(entry_price - stop_price)
                    if stop_points == 0:
                        break

                    target_points = stop_points * rr_fixed
                    target_price = (
                        entry_price + target_points
                        if ob["direction"] == "bullish"
                        else entry_price - target_points
                    )
                    position_size = risk_amount / (stop_points * point_value)

                    result = simulate_trade_management(
                        future_trigger.iloc[k:], ob["direction"], entry_price,
                        stop_price, target_price, position_size, point_value, risk_amount
                    )
                    if result:
                        result["strategy_id"] = strategy["strategy_id"]
                        result["ob_index"] = ob["index"]
                        trades.append(result)
                break

    trades_df = pd.DataFrame(trades)
    daily_pnl = build_daily_pnl(trades_df) if not trades_df.empty else pd.DataFrame(columns=["date", "pnl_usd"])

    trade_metrics = compute_trade_metrics(trades_df) if not trades_df.empty else compute_trade_metrics(pd.DataFrame())
    equity_metrics = compute_equity_metrics(daily_pnl, account_size=account_size)

    return {
        "trades": trades_df,
        "daily_pnl": daily_pnl,
        "metrics": {**trade_metrics, **equity_metrics},
    }


def simulate_trade_management(future_bars, direction, entry_price, stop_price,
                               target_price, position_size, point_value, risk_amount):
    current_stop = stop_price
    moved_to_be = False

    for _, bar in future_bars.iloc[1:].iterrows():
        favorable_event = "CHOCH_UP" if direction == "bullish" else "CHOCH_DOWN"
        favorable_bos = "BOS_UP" if direction == "bullish" else "BOS_DOWN"
        if not moved_to_be and bar["structure_event"] in (favorable_event, favorable_bos):
            current_stop = entry_price
            moved_to_be = True

        if direction == "bullish":
            if bar["low"] <= current_stop:
                return _close_trade(entry_price, current_stop, direction, position_size,
                                     point_value, risk_amount, bar["timestamp"], stop_price)
            if bar["high"] >= target_price:
                return _close_trade(entry_price, target_price, direction, position_size,
                                     point_value, risk_amount, bar["timestamp"], stop_price)
        else:
            if bar["high"] >= current_stop:
                return _close_trade(entry_price, current_stop, direction, position_size,
                                     point_value, risk_amount, bar["timestamp"], stop_price)
            if bar["low"] <= target_price:
                return _close_trade(entry_price, target_price, direction, position_size,
                                     point_value, risk_amount, bar["timestamp"], stop_price)

    return None


def _close_trade(entry_price, exit_price, direction, position_size, point_value,
                  risk_amount, exit_time, original_stop_price):
    price_diff = (exit_price - entry_price) if direction == "bullish" else (entry_price - exit_price)
    pnl_usd = price_diff * position_size * point_value
    r_multiple = pnl_usd / risk_amount if risk_amount else 0

    return {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "direction": direction,
        "exit_date": exit_time,
        "pnl_usd": round(pnl_usd, 2),
        "r_multiple": round(r_multiple, 3),
        "result": "win" if pnl_usd > 0 else ("be" if pnl_usd == 0 else "loss"),
    }


def build_daily_pnl(trades_df: pd.DataFrame) -> pd.DataFrame:
    trades_df = trades_df.copy()
    trades_df["date"] = pd.to_datetime(trades_df["exit_date"]).dt.date
    daily = trades_df.groupby("date")["pnl_usd"].sum().reset_index()
    return daily


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--structure-data", required=True)
    parser.add_argument("--trigger-data", required=True)
    args = parser.parse_args()

    with open(args.strategy) as f:
        strategy = json.load(f)

    structure_df = load_ohlcv(args.structure_data)
    trigger_df = load_ohlcv(args.trigger_data)

    result = run_backtest(strategy, structure_df, trigger_df)

    out_dir = Path("results") / strategy["strategy_id"]
    out_dir.mkdir(parents=True, exist_ok=True)

    result["trades"].to_csv(out_dir / "trades.csv", index=False)
    result["daily_pnl"].to_csv(out_dir / "daily_pnl.csv", index=False)
    with open(out_dir / "metrics.json", "w") as f:
        json.dump(result["metrics"], f, indent=2, default=str)

    print(json.dumps(result["metrics"], indent=2, default=str))
    print(f"\nResultados guardados en {out_dir}/")


if __name__ == "__main__":
    main()
