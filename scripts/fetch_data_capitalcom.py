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

    python scripts/fetch_data_capitalcom.py --epic US100 --resolution HOUR \
        --start 2024-01-01 --end 2024-12-31 --out data/nas100/nas100_1h.csv

    python scripts/fetch_data_capitalcom.py --epic US100 --resolution MINUTE_5 \
        --start 2024-01-01 --end 2024-12-31 --out data/nas100/nas100_5m.csv

    python scripts/fetch_data_capitalcom.py --epic GOLD --resolution HOUR \
        --start 2024-01-01 --end 2024-12-31 --out data/xauusd/xauusd_1h.csv

Nota: el epic exacto de NAS100 y del oro puede variar (ej. "NAS100", "US100",
"GOLD", "XAUUSD"). Si un epic falla, usa --search para listar los epics
disponibles que coincidan con un texto.

Resoluciones soportadas: MINUTE, MINUTE_5, MINUTE_15, MINUTE_30, HOUR, HOUR_4, DAY

Limites reales de la API de Capital.com:
    - El rango maximo entre 'from' y 'to' por request es de 1 DIA,
      independientemente de la resolucion elegida (esto es distinto del
      parametro max=1000, que solo limita cantidad de velas por respuesta).
    - Este script pagina automaticamente en bloques de 1 dia para evitar
      el error "error.invalid.max.daterange". Para rangos largos (varios
      anios) esto implica cientos de requests y puede tardar varios minutos.
    - Tras el login se intenta activar explicitamente la cuenta con la que
      se va a operar via PUT /session con su accountId. Si la cuenta ya
      estaba activa por defecto, la API devuelve
      error.not-different.accountId, lo cual se ignora (no es un error real).
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
MAX_DATERANGE = timedelta(days=1)


def create_session(api_key: str, identifier: str, password: str) -> dict:
    """
    Autentica contra Capital.com, devuelve los tokens necesarios
    (CST y X-SECURITY-TOKEN), e intenta activar explicitamente la cuenta
    preferida via PUT /session. Si la cuenta ya estaba activa por defecto
    (error.not-different.accountId), se ignora ese error y se continua.
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

    accounts = data.get("accounts", [])

    # Intentar activar explicitamente la cuenta preferida (o la primera disponible)
    # llamando PUT /session con su accountId.
    account_id = None
    for acc in accounts:
        if acc.get("preferred"):
            account_id = acc.get("accountId")
            break
    if not account_id and accounts:
        account_id = accounts[0].get("accountId")

    if account_id:
        switch_headers = {
            "X-CAP-API-KEY": api_key,
            "CST": cst,
            "X-SECURITY-TOKEN": security_token,
            "Content-Type": "application/json",
        }
        switch_response = requests.put(
            url, headers=switch_headers, json={"accountId": account_id}, timeout=30
        )
        if switch_response.status_code == 200:
            # PUT /session tambien puede refrescar los tokens; los actualizamos por seguridad
            cst = switch_response.headers.get("CST", cst)
            security_token = switch_response.headers.get("X-SECURITY-TOKEN", security_token)
        else:
            body_text = switch_response.text
            if "error.not-different.accountId" in body_text:
                # La cuenta ya estaba activa por defecto tras el login normal.
                # No es un error real, se puede continuar sin problema.
                pass
            else:
                raise RuntimeError(
                    f"Error activando cuenta ({switch_response.status_code}): {body_text}"
                )

    return {
        "cst": cst,
        "security_token": security_token,
        "accounts": accounts,
        "active_account_id": account_id,
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
    Pagina requests respetando el limite real de la API de Capital.com:
    maximo 1 dia de rango entre 'from' y 'to' por request (independiente
    de la resolucion y del parametro max=1000).
    Devuelve una lista de dicts con timestamp, open, high, low, close, volume.
    """
    headers = {
        "X-CAP-API-KEY": api_key,
        "CST": cst,
        "X-SECURITY-TOKEN": security_token,
    }
    all_candles = []
    current_start = start
    total_days = max((end - start).days, 1)
    day_count = 0

    while current_start < end:
        request_to = min(current_start + MAX_DATERANGE, end)

        url = f"{BASE_URL}/prices/{epic}"
        params = {
            "resolution": resolution,
            "from": current_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "to": request_to.strftime("%Y-%m-%dT%H:%M:%S"),
            "max": MAX_CANDLES_PER_REQUEST,
        }
        response = requests.get(url, headers=headers, params=params, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"Error obteniendo precios ({response.status_code}): {response.text}")

        prices = response.json().get("prices", [])

        for p in prices:
            all_candles.append({
                "timestamp": p["snapshotTimeUTC"],
                "open": p["openPrice"]["bid"],
                "high": p["highPrice"]["bid"],
                "low": p["lowPrice"]["bid"],
                "close": p["closePrice"]["bid"],
                "volume": p.get("lastTradedVolume", 0),
            })

        day_count += 1
        if day_count % 30 == 0:
            print(f"  ... progreso: dia {day_count}/{total_days} ({len(all_candles)} velas acumuladas)")

        current_start = request_to
        time.sleep(0.25)  # evitar rate limiting (muchos requests para rangos largos)

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
    print(f"Cuenta activa (usada para /prices): {session['active_account_id']}")

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
    print("Nota: la API limita cada request a 1 dia, esto puede tardar varios minutos para rangos largos.")
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
