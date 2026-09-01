"""
Descarga velas historicas OHLCV desde la API de Capital.com (cuenta demo)
y las guarda en el formato CSV que espera engine/backtester.py
(columnas: timestamp, open, high, low, close, volume).

Requiere las variables de entorno:
    CAPITAL_API_KEY       -> tu API key generada en Capital.com
    CAPITAL_IDENTIFIER    -> tu email de login de Capital.com
    CAPITAL_API_PASSWORD  -> la contrasena de API (distinta a tu password normal)

Uso:
    export CAPITAL_API_KEY="tu_api_key"
    export CAPITAL_IDENTIFIER="tu_email@ejemplo.com"
    export CAPITAL_API_PASSWORD="tu_password_de_api"

    python scripts/fetch_data_capitalcom.py --epic NAS100 --resolution HOUR \
        --start 2022-01-01 --end 2024-12-31 --out data/nas100/nas100_1h.csv

    python scripts/fetch_data_capitalcom.py --epic NAS100 --resolution MINUTE_5 \
        --start 2024-01-01 --end 2024-12-31 --out data/nas100/nas100_5m.csv

    python scripts/fetch_data_capitalcom.py --epic GOLD --resolution HOUR \
        --start 2022-01-01 --end 2024-12-31 --out data/xauusd/xauusd_1h.csv

Nota: el epic exacto de NAS100 y del oro puede variar (ej. "NAS100", "US100",
"GOLD", "XAUUSD"). Si un epic falla, usa --search para listar los epics
disponibles que coincidan con un texto.

Resoluciones soportadas: MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY
Limite de la API: 1000 velas por request. Este script pagina automaticamente.
"""
import argparse
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE_URL = "https://demo-api-capital.backend-capital.com/api/v1"

RESOLUTION_SECONDS = {
    "MINUTE": 60,
    "MINUTE_5": 300,
    "MINUTE_15": 900,
    "MINUTE_30": 1800,
    "HOUR": 3600,
    "HOUR_4": 14400,
    "DAY": 86400,
}

MAX_CANDLES_PER_REQUEST = 1000


def create_session(api_key: str, identifier: str, password: str) -> dict:
    """
    Autentica contra Capital.com y devuelve los tokens necesarios
    para las siguientes requests (CST y X-SECURITY-TOKEN), junto
    con la lista de cuentas disponibles.
    """
    url = f"{BASE_URL}/session"
    headers = {"X-CAP-API-KEY": api_key, "Content-Type": "application/json"}
    body = {"identifier": identifier, "password": password, "encryptedPassword": False}

    response = requests.post(url, headers=headers, json=body, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"Error de autenticacion Capital.com ({response.status_code}): {response.text}")

    cst = response.headers.get("CST")
    security_token = response.headers.get("X-SECURITY-TOKEN")
    data = response.json()

    if not cst or not security_token:
        raise RuntimeError("La respuesta no incluyo los tokens CST / X-SECURITY-TOKEN esperados.")

    return {
        "cst": cst,
        "security_token": security_token,
        "accounts": data.get("accounts", []),
    }


def search_epics(api_key: str, cst: str, security_token: str, search_term: str) -> list:
    """Lista epics disponibles que coincidan con un termino de busqueda."""
    url = f"{BASE_URL}/markets"
    headers = {
        "X-CAP-API-KEY": api_key,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    params = {"searchTerm": search_term}
    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(f"Error buscando epics ({response.status_code}): {response.text}")

    markets = response.json().get("markets", [])
    return [{"epic": m["epic"], "instrumentName": m["instrumentName"]} for m in markets]


def fetch_candles(api_key: str, cst: str, security_token: str, epic: str,
                   resolution: str, start: datetime, end: datetime) -> list:
    """
    Pagina requests de 1000 velas hasta cubrir [start, end].
    Devuelve una lista de dicts con timestamp, open, high, low, close, volume.
    """
    headers = {
        "X-CAP-API-KEY": api_key,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    all_candles = []
    current_start = start
    seconds_per_candle = RESOLUTION_SECONDS[resolution]

    while current_start < end:
        url = f"{BASE_URL}/prices/{epic}"
        params = {
            "resolution": resolution,
            "from": current_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": end.strftime("%Y-%m-%dT%H:%M:%S"),
            "max": MAX_CANDLES_PER_REQUEST,
        }
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"Error obteniendo precios ({response.status_code}): {response.text}")

        prices = response.json().get("prices", [])
        if not prices:
            break

        for p in prices:
            all_candles.append({
                "timestamp": p["snapshotTimeUTC"],
                "open": p["openPrice"]["bid"],
                "high": p["highPrice"]["bid"],
                "low": p["lowPrice"]["bid"],
                "close": p["closePrice"]["bid"],
                "volume": p.get("lastTradedVolume", 0),
            })

        last_time_str = prices[-1]["snapshotTimeUTC"]
        last_time = datetime.strptime(last_time_str[:19], "%Y-%m-%dT%H:%M:%S")
        next_start = last_time + timedelta(seconds=seconds_per_candle)

        if next_start <= current_start:
            break
        current_start = next_start

        if len(prices) < MAX_CANDLES_PER_REQUEST:
            break

        time.sleep(0.3)  # evitar rate limiting

    return all_candles


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epic", help="ej. NAS100, GOLD, US100, XAUUSD")
    parser.add_argument("--resolution", default="HOUR", help="MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY")
    parser.add_argument("--start", help="YYYY-MM-DD")
    parser.add_argument("--end", help="YYYY-MM-DD")
    parser.add_argument("--out", help="ruta del CSV de salida")
    parser.add_argument("--search", help="buscar epics disponibles que coincidan con este texto (ej. 'nasdaq' o 'gold')")
    args = parser.parse_args()

    api_key = os.environ.get("CAPITAL_API_KEY")
    identifier = os.environ.get("CAPITAL_IDENTIFIER")
    password = os.environ.get("CAPITAL_API_PASSWORD")

    if not all([api_key, identifier, password]):
        raise SystemExit(
            "ERROR: define CAPITAL_API_KEY, CAPITAL_IDENTIFIER y CAPITAL_API_PASSWORD "
            "como variables de entorno antes de correr este script."
        )

    print("Autenticando con Capital.com...")
    session = create_session(api_key, identifier, password)
    print(f"Sesion creada. Cuentas disponibles: {session['accounts']}")

    if args.search:
        print(f"Buscando epics que coincidan con '{args.search}'...")
        results = search_epics(api_key, session["cst"], session["security_token"], args.search)
        for r in results:
            print(f"  epic={r['epic']}  ->  {r['instrumentName']}")
        return

    if not all([args.epic, args.start, args.end, args.out]):
        raise SystemExit("ERROR: --epic, --start, --end y --out son requeridos (o usa --search para explorar epics).")

    if args.resolution not in RESOLUTION_SECONDS:
        raise SystemExit(f"Resolucion no soportada: {args.resolution}. Usa: {list(RESOLUTION_SECONDS.keys())}")

    start_dt = datetime.strptime(args.start, "%Y-%m-%d")
    end_dt = datetime.strptime(args.end, "%Y-%m-%d")

    print(f"Descargando {args.epic} [{args.resolution}] desde {args.start} hasta {args.end}...")
    candles = fetch_candles(api_key, session["cst"], session["security_token"],
                             args.epic, args.resolution, start_dt, end_dt)

    if not candles:
        raise SystemExit("No se descargaron velas. Verifica el epic, resolucion y fechas (usa --search para explorar).")

    df = pd.DataFrame(candles)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df.to_csv(args.out, index=False)

    print(f"Guardado: {args.out} ({len(df)} velas)")


if __name__ == "__main__":
    main()
