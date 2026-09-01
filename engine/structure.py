"""
Deteccion de estructura de mercado: swing highs/lows, BOS y CHoCH,
y Order Blocks (velas de origen) sobre datos OHLCV.
"""
import pandas as pd

SWING_LOOKBACK = 3


def find_swings(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> pd.DataFrame:
    df = df.copy()
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)

    swing_high = [False] * n
    swing_low = [False] * n

    for i in range(lookback, n - lookback):
        window_high = highs[i - lookback: i + lookback + 1]
        window_low = lows[i - lookback: i + lookback + 1]
        if highs[i] == window_high.max():
            swing_high[i] = True
        if lows[i] == window_low.min():
            swing_low[i] = True

    df["swing_high"] = swing_high
    df["swing_low"] = swing_low
    return df


def detect_bos_choch(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    events = [None] * len(df)
    trend_series = [None] * len(df)

    last_swing_high = None
    last_swing_low = None
    trend = None

    for i in range(len(df)):
        if df["swing_high"].iloc[i]:
            last_swing_high = df["high"].iloc[i]
        if df["swing_low"].iloc[i]:
            last_swing_low = df["low"].iloc[i]

        close = df["close"].iloc[i]

        if last_swing_high is not None and close > last_swing_high:
            if trend in (None, "up"):
                events[i] = "BOS_UP"
            else:
                events[i] = "CHOCH_UP"
            trend = "up"
            last_swing_high = None

        elif last_swing_low is not None and close < last_swing_low:
            if trend in (None, "down"):
                events[i] = "BOS_DOWN"
            else:
                events[i] = "CHOCH_DOWN"
            trend = "down"
            last_swing_low = None

        trend_series[i] = trend

    df["structure_event"] = events
    df["trend"] = trend_series
    return df


def find_order_blocks(df: pd.DataFrame) -> list:
    order_blocks = []

    for i in range(1, len(df)):
        event = df["structure_event"].iloc[i]
        if event not in ("BOS_UP", "CHOCH_UP", "BOS_DOWN", "CHOCH_DOWN"):
            continue

        direction = "bullish" if event in ("BOS_UP", "CHOCH_UP") else "bearish"
        j = i - 1
        ob_index = None
        while j >= 0:
            is_bearish_candle = df["close"].iloc[j] < df["open"].iloc[j]
            is_bullish_candle = df["close"].iloc[j] > df["open"].iloc[j]
            if direction == "bullish" and is_bearish_candle:
                ob_index = j
                break
            if direction == "bearish" and is_bullish_candle:
                ob_index = j
                break
            j -= 1

        if ob_index is None:
            continue

        order_blocks.append({
            "index": ob_index,
            "direction": direction,
            "high": df["high"].iloc[ob_index],
            "low": df["low"].iloc[ob_index],
            "open": df["open"].iloc[ob_index],
            "close": df["close"].iloc[ob_index],
            "mitigated": False,
            "event_index": i,
            "event_type": event,
        })

    return order_blocks
