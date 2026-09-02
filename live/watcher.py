"""Watcher live para detectar señales en el stream de Capital.com y publicar alertas."""
import csv
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from live.telegram_router import send_signal_alert


DEFAULT_SIGNAL_LOG = Path("live/signals_log.csv")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _macro_liquidity_context(macro_context: Optional[Dict[str, pd.DataFrame]]) -> Dict[str, Any]:
    if not macro_context:
        return {"macro_bias": "neutral", "support": None, "resistance": None, "swing_lows": [], "swing_highs": [], "strong_liquidity": False}

    context = {"macro_bias": "neutral", "support": None, "resistance": None, "swing_lows": [], "swing_highs": [], "strong_liquidity": False}
    valid_frames = []
    for key, frame in macro_context.items():
        if key in {"1m", "5m", "15m"}:
            continue
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            df = frame.copy().sort_values("timestamp").reset_index(drop=True)
            df = df[~df["close"].isna()].copy()
            if not df.empty:
                valid_frames.append(df)
    if not valid_frames:
        return context

    longest = max(valid_frames, key=len)
    recent = longest.tail(min(len(longest), 60))
    recent_close = longest.iloc[-1]
    prev = longest.iloc[-2] if len(longest) >= 2 else recent_close
    context["macro_bias"] = "bullish" if _safe_float(recent_close["close"]) > _safe_float(prev["close"]) else "bearish"

    swing_lows = [float(x) for x in recent["low"].tail(12).tolist()]
    swing_highs = [float(x) for x in recent["high"].tail(12).tolist()]
    context["swing_lows"] = swing_lows
    context["swing_highs"] = swing_highs
    context["support"] = min(swing_lows[-5:]) if len(swing_lows) >= 5 else min(swing_lows)
    context["resistance"] = max(swing_highs[-5:]) if len(swing_highs) >= 5 else max(swing_highs)

    if len(longest) >= 5:
        last_close = _safe_float(longest["close"].iloc[-1])
        prev_close = _safe_float(longest["close"].iloc[-2])
        context["strong_liquidity"] = last_close > prev_close if context["macro_bias"] == "bullish" else last_close < prev_close

    return context


def should_emit_signal(signal: Optional[Dict[str, Any]], last_signal_time: Optional[datetime], cooldown_minutes: int = 15) -> bool:
    """Evita spam por alertas repetidas durante el mismo cooldown."""
    if signal is None:
        return False
    if last_signal_time is None:
        return True
    if isinstance(last_signal_time, str):
        try:
            last_signal_time = datetime.fromisoformat(last_signal_time.replace("Z", "+00:00"))
        except ValueError:
            return True
    if last_signal_time.tzinfo is None:
        last_signal_time = last_signal_time.replace(tzinfo=timezone.utc)
    elapsed_minutes = (datetime.now(timezone.utc) - last_signal_time).total_seconds() / 60.0
    return elapsed_minutes >= cooldown_minutes


def build_signal_from_recent_candles(strategy: Dict[str, Any], candles: pd.DataFrame, timeframe: str | None = None, macro_context: Optional[Dict[str, pd.DataFrame]] = None) -> Optional[Dict[str, Any]]:
    """Versión 5: solo dispara cuando hay validación de zona macro y breakout real."""
    if candles.empty:
        return None

    df = candles.copy().sort_values("timestamp").reset_index(drop=True)
    if len(df) < 3:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]
    signal_cfg = strategy.get("signal_config", {})

    macro = _macro_liquidity_context(macro_context)
    macro_bias = macro.get("macro_bias", "neutral")
    liquidity_zone = None
    require_alignment = bool(signal_cfg.get("require_1m_5m_alignment", True))
    zone_tolerance = float(signal_cfg.get("liquidity_zone_tolerance", 0.003))

    def _zone_retest_valid(direction: str) -> bool:
        nonlocal liquidity_zone
        if not macro_context:
            return False

        support = macro.get("support")
        resistance = macro.get("resistance")
        zone_value = float(support if direction == "bullish" else resistance) if (support is not None and direction == "bullish") or (resistance is not None and direction == "bearish") else None
        if zone_value is None:
            return False

        current_close = float(last["close"])
        recent_high = float(df["high"].tail(12).max())
        recent_low = float(df["low"].tail(12).min())
        liquidity_zone = zone_value

        if direction == "bullish":
            if not (current_close > zone_value):
                return False
            if abs(current_close - zone_value) / max(abs(zone_value), 1.0) > 0.01:
                return False
            # Debe haber un re-teste real en la zona y no solo un impulso aleatorio lejos del nivel.
            return recent_low <= (zone_value * (1 + zone_tolerance * 2.0)) or recent_high >= zone_value

        if not (current_close < zone_value):
            return False
        if abs(zone_value - current_close) / max(abs(zone_value), 1.0) > 0.01:
            return False
        return recent_high >= (zone_value * (1 - zone_tolerance * 2.0)) or recent_low <= zone_value

    if not macro_context:
        lookback = max(int(signal_cfg.get("lookback_bars", 5)), 3)
        recent_close_window = df["close"].tail(lookback).astype(float)
        recent_average = float(recent_close_window.mean())
        recent_slope = float(recent_close_window.iloc[-1] - recent_close_window.iloc[0])
        relative_move = abs(float(last["close"]) - recent_average) / max(abs(recent_average), 1.0)
        min_strength = float(signal_cfg.get("min_trend_strength_pct", 0.0002))

        bullish_bias = (
            float(last["close"]) > float(prev["close"]) and
            float(last["close"]) > recent_average and
            recent_slope > 0 and
            relative_move >= min_strength
        )
        bearish_bias = (
            float(last["close"]) < float(prev["close"]) and
            float(last["close"]) < recent_average and
            recent_slope < 0 and
            relative_move >= min_strength
        )
    else:
        bullish_bias = _zone_retest_valid("bullish") if macro_bias == "bullish" else False
        bearish_bias = _zone_retest_valid("bearish") if macro_bias == "bearish" else False

        if require_alignment and isinstance(macro_context, dict):
            minute_df = macro_context.get("1m")
            five_df = macro_context.get("5m")
            minute_dir = None
            five_dir = None

            if isinstance(minute_df, pd.DataFrame) and not minute_df.empty:
                minute_last = minute_df.iloc[-1]
                minute_prev = minute_df.iloc[-2] if len(minute_df) >= 2 else minute_last
                minute_dir = "bullish" if float(minute_last["close"]) > float(minute_prev["close"]) else "bearish"

            if isinstance(five_df, pd.DataFrame) and not five_df.empty:
                five_last = five_df.iloc[-1]
                five_prev = five_df.iloc[-2] if len(five_df) >= 2 else five_last
                five_dir = "bullish" if float(five_last["close"]) > float(five_prev["close"]) else "bearish"

            if minute_dir and five_dir:
                if minute_dir != five_dir:
                    return None
                if minute_dir == "bullish":
                    if not bullish_bias:
                        return None
                else:
                    if not bearish_bias:
                        return None

    if not (bullish_bias or bearish_bias):
        return None

    direction = "bullish" if bullish_bias else "bearish"
    entry_price = float(last["close"])
    stop_distance = max(float(df["high"].max()) - float(df["low"].min()), 1.0)
    stop_price = float(df["low"].min()) if direction == "bullish" else float(df["high"].max())
    rr = float(strategy.get("reward_to_risk", {}).get("fixed", signal_cfg.get("min_rr", 3.0)))
    target_price = entry_price + (stop_distance * rr) if direction == "bullish" else entry_price - (stop_distance * rr)
    risk_amount = float(strategy.get("risk_amount_usd", signal_cfg.get("risk_amount_usd", 100.0)))
    position_size = risk_amount / max(stop_distance, 1.0)

    return {
        "strategy_id": strategy.get("strategy_id", "unknown"),
        "direction": direction,
        "entry_price": round(entry_price, 5),
        "stop_price": round(stop_price, 5),
        "target_price": round(target_price, 5),
        "position_size": round(position_size, 6),
        "timeframe": timeframe or "unknown",
        "macro_bias": macro.get("macro_bias"),
        "macro_zone": liquidity_zone,
        "multi_tf_confirmed": bool(macro_context),
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


def publish_signal(strategy: Dict[str, Any], candles: pd.DataFrame, csv_path: str = str(DEFAULT_SIGNAL_LOG), timeframe: str | None = None, macro_context: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
    signal = build_signal_from_recent_candles(strategy, candles, timeframe=timeframe, macro_context=macro_context)
    if signal is None:
        return {"ok": False, "reason": "no_signal"}

    log_signal(signal, csv_path=csv_path)
    try:
        result = send_signal_alert(signal)
        return {"ok": True, "signal": signal, "telegram": result}
    except Exception as exc:
        return {"ok": True, "signal": signal, "telegram_error": str(exc)}
