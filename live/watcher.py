"""Watcher live para detectar señales en el stream de Capital.com y publicar alertas."""
import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from live.telegram_router import send_signal_alert


DEFAULT_SIGNAL_LOG = Path("live/signals_log.csv")


def build_signal_from_recent_candles(strategy: Dict[str, Any], candles: pd.DataFrame, timeframe: str | None = None) -> Optional[Dict[str, Any]]:
    """Genera una alerta simple basada en la última vela y la tendencia reciente.

    El punto clave es que la señal se calcula con el último cierre del timeframe
    actual. Por eso el precio de la señal puede diferir del precio streaming
    instantáneo del mercado si se compara con otro timeframe o con un tick real.
    """
    if candles.empty:
        return None

    df = candles.copy().sort_values("timestamp").reset_index(drop=True)
    if len(df) < 3:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    prev2 = df.iloc[-3]

    recent_close_window = df["close"].tail(5).astype(float)
    recent_average = float(recent_close_window.mean())
    recent_slope = float(recent_close_window.iloc[-1] - recent_close_window.iloc[0])

    bullish_bias = (
        float(last["close"]) > float(prev["close"]) and
        float(last["close"]) > recent_average and
        recent_slope > 0
    )
    bearish_bias = (
        float(last["close"]) < float(prev["close"]) and
        float(last["close"]) < recent_average and
        recent_slope < 0
    )

    if not (bullish_bias or bearish_bias):
        return None

    direction = "bullish" if bullish_bias else "bearish"
    entry_price = float(last["close"])
    stop_distance = max(float(last["high"]) - float(last["low"]), 1.0)
    stop_price = float(last["low"]) if direction == "bullish" else float(last["high"])
    rr = float(strategy.get("reward_to_risk", {}).get("fixed", 3.0))
    target_price = entry_price + (stop_distance * rr) if direction == "bullish" else entry_price - (stop_distance * rr)
    risk_amount = float(strategy.get("risk_amount_usd", 100.0))
    position_size = risk_amount / max(stop_distance, 1.0)

    return {
        "strategy_id": strategy.get("strategy_id", "unknown"),
        "direction": direction,
        "entry_price": round(entry_price, 5),
        "stop_price": round(stop_price, 5),
        "target_price": round(target_price, 5),
        "position_size": round(position_size, 6),
        "timeframe": timeframe or "unknown",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def log_signal(signal: Dict[str, Any], csv_path: str = str(DEFAULT_SIGNAL_LOG)) -> None:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "strategy_id",
        "direction",
        "entry_price",
        "stop_price",
        "target_price",
        "position_size",
        "timestamp",
    ]

    file_exists = path.exists() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({k: signal.get(k, "") for k in fieldnames})


def publish_signal(strategy: Dict[str, Any], candles: pd.DataFrame, csv_path: str = str(DEFAULT_SIGNAL_LOG), timeframe: str | None = None) -> Dict[str, Any]:
    signal = build_signal_from_recent_candles(strategy, candles, timeframe=timeframe)
    if signal is None:
        return {"ok": False, "reason": "no_signal"}

    log_signal(signal, csv_path=csv_path)
    try:
        result = send_signal_alert(signal)
        return {"ok": True, "signal": signal, "telegram": result}
    except Exception as exc:
        return {"ok": True, "signal": signal, "telegram_error": str(exc)}
