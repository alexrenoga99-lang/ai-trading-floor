"""
Dashboard visual con Streamlit para el AI Trading Floor.
Reutiliza engine/backtester.py, engine/structure.py, engine/rules_guard.py
sin modificarlos.

Ejecutar con:
    streamlit run dashboard/app.py
"""
import json
import os
import time
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from live.capital_live import fetch_recent_candles
from live.telegram_router import send_signal_alert
from live.watcher import build_signal_from_recent_candles

TIMEFRAME_OPTIONS = {
    "1m": {"resolution": "MINUTE", "hours": 12},
    "5m": {"resolution": "MINUTE_5", "hours": 24},
    "15m": {"resolution": "MINUTE_15", "hours": 48},
    "1h": {"resolution": "HOUR", "hours": 72},
    "4h": {"resolution": "HOUR_4", "hours": 168},
    "1d": {"resolution": "DAY", "hours": 720},
}


def _ensure_env_loaded() -> None:
    """Carga .env local para que el dashboard funcione sin un source manual."""
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


_ensure_env_loaded()

st.set_page_config(page_title="AI Trading Floor", layout="wide")
st.title("AI Trading Floor - Dashboard")
st.caption("Actualización en tiempo real: cada 15 segundos para evitar rate limit de Capital.com")
st_autorefresh(interval=15000, key="live_refresh")

# --- Selector de estrategia ---
strategy_files = list(Path("strategies").glob("*.json"))
strategy_names = [f.stem for f in strategy_files]
selected = st.sidebar.selectbox("Estrategia", strategy_names)

with open(f"strategies/{selected}.json") as f:
    strategy = json.load(f)

st.sidebar.json(strategy, expanded=False)

st.sidebar.caption("Telegram alert routing")
st.sidebar.write(f"Bot token: {'OK' if os.getenv('TELEGRAM_BOT_TOKEN') else 'missing'}")
st.sidebar.write(f"Chat ID: {'OK' if os.getenv('TELEGRAM_CHAT_ID') else 'missing'}")
if st.sidebar.button("Enviar alerta de prueba"):
    sample_signal = {
        "strategy_id": strategy["strategy_id"],
        "direction": "bullish",
        "entry_price": 22300.5,
        "stop_price": 22280.0,
        "target_price": 22360.0,
        "position_size": 0.75,
        "timestamp": "now",
    }
    try:
        result = send_signal_alert(sample_signal)
        st.sidebar.success(f"Alerta enviada: {result.get('ok', True)}")
    except Exception as exc:
        st.sidebar.error(f"Telegram no configurado: {exc}")

st.sidebar.caption("Capital.com live")
capital_epic = st.sidebar.text_input("Epic live", "US100")
selected_timeframe = st.sidebar.selectbox("Timeframe", list(TIMEFRAME_OPTIONS.keys()), index=3)
selected_resolution = TIMEFRAME_OPTIONS[selected_timeframe]["resolution"]
selected_hours = TIMEFRAME_OPTIONS[selected_timeframe]["hours"]

should_refresh = (
    "live_data" not in st.session_state
    or st.session_state.get("live_timeframe") != selected_timeframe
    or (time.time() - st.session_state.get("live_last_fetch", 0)) >= 15
)

if should_refresh:
    try:
        live_data = fetch_recent_candles(
            epic=capital_epic,
            resolution=selected_resolution,
            hours=selected_hours,
            max_points=200,
        )
        st.session_state["live_data"] = live_data
        st.session_state["live_data_error"] = None
        st.session_state["live_last_fetch"] = time.time()
        st.session_state["live_timeframe"] = selected_timeframe
    except Exception as exc:
        st.session_state["live_data_error"] = str(exc)

live_data = st.session_state.get("live_data")

st.subheader(f"Precio live · {selected_timeframe}")
if live_data:
    df = live_data["df"]
    signal = build_signal_from_recent_candles(strategy, df, timeframe=selected_timeframe)
    fig = go.Figure(data=[go.Candlestick(
        x=df["timestamp"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name=live_data["epic"],
    )])

    if signal:
        last_ts = df["timestamp"].iloc[-1]
        fig.add_vline(x=last_ts, line_dash="dash", line_color="#ff9f1c", line_width=2)
        fig.add_hline(y=signal["stop_price"], line_dash="dot", line_color="#d32f2f", line_width=1)
        fig.add_hline(y=signal["target_price"], line_dash="dot", line_color="#2e7d32", line_width=1)
        fig.add_trace(go.Scatter(
            x=[last_ts],
            y=[signal["entry_price"]],
            mode="markers+text",
            name="Alerta estrategia",
            text=["ALERTA"],
            textposition="top center",
            marker=dict(color="#ff9f1c", size=12, symbol="diamond"),
        ))
        st.caption(
            f"Señal: {signal['direction']} | timeframe={signal.get('timeframe')} | entrada {signal['entry_price']} | stop {signal['stop_price']} | target {signal['target_price']}"
        )

    fig.update_layout(
        height=500,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.metric("Último cierre del timeframe", f"{live_data['current_price']:.2f}")
    st.caption("Importante: el precio del watcher y del dashboard se basan en el último cierre del timeframe elegido, no en el último tick instantáneo del mercado.")
else:
    if st.session_state.get("live_data_error"):
        st.warning(f"No se pudo cargar Capital.com live: {st.session_state['live_data_error']}")
    else:
        st.info("No hay datos live disponibles todavía.")
