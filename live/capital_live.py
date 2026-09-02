"""Helpers para leer precios y velas recientes desde Capital.com."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from scripts.fetch_data_capitalcom import create_session

_SESSION_CACHE = {"session": None, "created_at": 0.0}
_SESSION_TTL_SECONDS = 180


def _ensure_env_loaded() -> None:
    """Carga .env local si existe, sin depender de python-dotenv en el entorno."""
    try:
        # Import local cuando la dependencia está instalada en el entorno del proyecto.
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

BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"


def _request_with_backoff(url: str, headers: dict, params: dict, timeout: int = 30, max_retries: int = 3) -> requests.Response:
    """Reintenta peticiones a Capital.com si responde 429 por rate limit."""
    for attempt in range(max_retries):
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        if response.status_code != 429:
            return response
        if attempt == max_retries - 1:
            raise RuntimeError(f"Capital.com rate limit ({response.status_code}): {response.text}")
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError("Capital.com no devolvio respuesta valida.")


def _load_env_and_validate() -> dict:
    _ensure_env_loaded()
    api_key = os.getenv("CAPITAL_API_KEY")
    identifier = os.getenv("CAPITAL_IDENTIFIER")
    password = os.getenv("CAPITAL_API_PASSWORD")
    if not all([api_key, identifier, password]):
        raise RuntimeError(
            "Faltan CAPITAL_API_KEY, CAPITAL_IDENTIFIER o CAPITAL_API_PASSWORD en .env o el entorno."
        )
    return {"api_key": api_key, "identifier": identifier, "password": password}


def _get_valid_session() -> dict:
    """Reusa la sesión autenticada mientras sigue siendo válida."""
    now = time.time()
    if _SESSION_CACHE["session"] and (now - _SESSION_CACHE["created_at"]) < _SESSION_TTL_SECONDS:
        return _SESSION_CACHE["session"]

    config = _load_env_and_validate()
    session = create_session(config["api_key"], config["identifier"], config["password"])
    _SESSION_CACHE["session"] = session
    _SESSION_CACHE["created_at"] = now
    return session


def fetch_recent_candles(epic: str = "US100", resolution: str = "HOUR", hours: int = 24, max_points: int = 200) -> dict:
    config = _load_env_and_validate()
    max_points = max(int(max_points), 3000 if hours >= 2160 else 200)
    session = _get_valid_session()
    headers = {
        "X-CAP-API-KEY": config["api_key"],
        "CST": session["cst"],
        "X-SECURITY-TOKEN": session["security_token"],
    }

    candidate_epics = [epic, epic.upper(), "US100", "NAS100", "NASDAQ100", "XAUUSD", "GOLD"]
    seen = set()
    resolved_epic = epic

    for candidate in candidate_epics:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(hours=hours)
            response = _request_with_backoff(
                f"{BASE_URL}/prices/{candidate}",
                headers=headers,
                params={
                    "resolution": resolution,
                    "from": start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "to": end.strftime("%Y-%m-%dT%H:%M:%S"),
                    "max": max_points,
                },
                timeout=30,
            )
            if response.status_code == 200:
                resolved_epic = candidate
                prices = response.json().get("prices", [])
                if not prices:
                    continue
                rows = []
                for p in prices:
                    rows.append({
                        "timestamp": p["snapshotTimeUTC"],
                        "open": p["openPrice"]["bid"],
                        "high": p["highPrice"]["bid"],
                        "low": p["lowPrice"]["bid"],
                        "close": p["closePrice"]["bid"],
                        "volume": p.get("lastTradedVolume", 0),
                    })
                df = pd.DataFrame(rows)
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                df = df.sort_values("timestamp").reset_index(drop=True)
                return {"epic": resolved_epic, "df": df, "current_price": float(df["close"].iloc[-1])}
        except requests.RequestException:
            continue

    raise RuntimeError(f"No se pudieron cargar datos live de Capital.com para {epic}.")


# Limpia la caché si una sesión deja de ser valida.
def invalidate_session_cache() -> None:
    _SESSION_CACHE["session"] = None
    _SESSION_CACHE["created_at"] = 0.0
