"""Enrutador de alertas a Telegram para señales del watcher agent."""
import json
import os
from pathlib import Path
from typing import Any, Dict

import requests

TELEGRAM_BASE_URL = "https://api.telegram.org/bot{token}"


def _ensure_env_loaded() -> None:
    """Carga .env local si existe, sin depender de python-dotenv."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return
    except ModuleNotFoundError:
        pass

    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def send_signal_alert(signal: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_env_loaded()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        raise RuntimeError("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el entorno.")

    payload = {
        "chat_id": chat_id,
        "text": format_signal_message(signal),
        "parse_mode": "HTML",
    }

    url = f"{TELEGRAM_BASE_URL.format(token=token)}/sendMessage"
    response = requests.post(url, data=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    return {"ok": bool(data.get("ok")), "payload": payload, "response": data}


def format_signal_message(signal: Dict[str, Any]) -> str:
    direction = signal.get("direction", "unknown").upper()
    entry = signal.get("entry_price")
    stop = signal.get("stop_price")
    target = signal.get("target_price")
    size = signal.get("position_size")
    strategy = signal.get("strategy_id", "strategy")
    timestamp = signal.get("timestamp", "now")

    return (
        f"<b>AI Trading Floor</b>\n"
        f"<b>Estratégia:</b> {strategy}\n"
        f"<b>Dirección:</b> {direction}\n"
        f"<b>Entrada:</b> {entry}\n"
        f"<b>Stop:</b> {stop}\n"
        f"<b>Target:</b> {target}\n"
        f"<b>Size:</b> {size}\n"
        f"<b>Tiempo:</b> {timestamp}"
    )


def send_alert_from_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        signal = json.load(fh)
    return send_signal_alert(signal)
