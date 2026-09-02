"""Worker 24/7 para alertas live y precios en tiempo real.

Ejecuta este proceso en la nube como un worker persistente y
se conecta a Capital.com cada N segundos para detectar señales de
la estrategia y mandar Telegram sin depender de Codespaces/PC local.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from live.capital_live import fetch_recent_candles
from live.watcher import build_signal_from_recent_candles, publish_signal


def _load_strategy(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_env_local() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ModuleNotFoundError:
        pass

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _resolve_timeframe(timeframe: str) -> tuple[str, int]:
    mapping = {
        "1m": ("MINUTE", 12),
        "5m": ("MINUTE_5", 24),
        "15m": ("MINUTE_15", 48),
        "1h": ("HOUR", 72),
        "4h": ("HOUR_4", 168),
        "1d": ("DAY", 720),
    }
    if timeframe not in mapping:
        raise ValueError(f"Timeframe no soportado: {timeframe}")
    return mapping[timeframe]


def run_worker(epic: str = "US100", timeframe: str = "1m", interval_seconds: int = 15) -> None:
    _load_env_local()
    strategy = _load_strategy(Path(__file__).resolve().parents[1] / "strategies" / "nas100_ob_choch_v1.json")
    resolution, hours = _resolve_timeframe(timeframe)
    last_signature = None

    print(f"Worker live iniciado: epic={epic} timeframe={timeframe} interval={interval_seconds}s")
    while True:
        try:
            data = fetch_recent_candles(
                epic=epic,
                resolution=resolution,
                hours=hours,
                max_points=200,
            )
            signal = build_signal_from_recent_candles(strategy, data["df"], timeframe=timeframe)

            if signal:
                signature = (
                    signal["direction"],
                    round(float(signal["entry_price"]), 5),
                    round(float(signal["stop_price"]), 5),
                    round(float(signal["target_price"]), 5),
                )
                if signature != last_signature:
                    result = publish_signal(strategy, data["df"], timeframe=timeframe)
                    print(f"[ALERTA] {signal['direction']} entry={signal['entry_price']} stop={signal['stop_price']} target={signal['target_price']} -> {result}")
                    last_signature = signature
                else:
                    print(f"[REPETIDA] {signal['direction']} entry={signal['entry_price']} stop={signal['stop_price']} target={signal['target_price']}")
            else:
                print(f"[SIN_SEÑAL] {data['epic']} @ {timeframe} {data['current_price']}")
        except Exception as exc:  # pragma: no cover - runtime worker loop
            print(f"[ERROR] {type(exc).__name__}: {exc}")

        time.sleep(interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Worker 24/7 para señales live de Capital.com")
    parser.add_argument("--epic", default=os.getenv("CAPITAL_EPIC", "US100"))
    parser.add_argument("--timeframe", default=os.getenv("WATCHER_TIMEFRAME", "1m"))
    parser.add_argument("--interval", type=int, default=int(os.getenv("WATCHER_INTERVAL_SECONDS", "15")))
    args = parser.parse_args()
    run_worker(epic=args.epic, timeframe=args.timeframe, interval_seconds=args.interval)


if __name__ == "__main__":
    main()
