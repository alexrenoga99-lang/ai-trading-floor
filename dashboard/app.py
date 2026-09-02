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
st.markdown(
    """
    <style>
    .stApp {
        background: linear-gradient(180deg, #07111f 0%, #0f172a 100%);
    }
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }
    .title-box {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 14px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 10px 25px rgba(15, 23, 42, 0.25);
    }
    .status-card {
        background: rgba(15, 23, 42, 0.8);
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 12px;
        padding: 0.9rem 1rem;
        min-height: 110px;
        box-shadow: 0 6px 18px rgba(15, 23, 42, 0.20);
    }
    .status-label {
        font-size: 0.74rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #94a3b8;
        margin-bottom: 0.4rem;
    }
    .status-value {
        font-size: 1.3rem;
        font-weight: 700;
        color: #e2e8f0;
    }
    .status-pill {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        background: rgba(34, 197, 94, 0.15);
        color: #86efac;
        border: 1px solid rgba(34, 197, 94, 0.35);
    }
    .signal-pill {
        display: inline-block;
        padding: 0.28rem 0.7rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
    }
    .signal-bullish {
        background: rgba(16, 185, 129, 0.15);
        color: #6ee7b7;
        border: 1px solid rgba(16, 185, 129, 0.35);
    }
    .signal-bearish {
        background: rgba(239, 68, 68, 0.15);
        color: #fca5a5;
        border: 1px solid rgba(239, 68, 68, 0.35);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="title-box">
      <h1 style="margin:0; color:#f8fafc;">AI Trading Floor - Dashboard</h1>
      <div style="color:#94a3b8; margin-top:0.4rem; font-size:0.96rem;">Actualización en tiempo real: cada 15 segundos para evitar rate limit de Capital.com</div>
    </div>
    """,
    unsafe_allow_html=True,
)
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
    last_close = float(df["close"].iloc[-1])
    current_price = float(live_data["current_price"])
    signal_label = signal["direction"].title() if signal else "Sin señal"
    signal_class = "signal-bullish" if signal and signal["direction"] == "bullish" else "signal-bearish" if signal else ""

    status_cols = st.columns(4)
    with status_cols[0]:
        st.markdown(
            """
            <div class="status-card">
                <div class="status-label">Mercado</div>
                <div class="status-value">Capital.com</div>
                <div class="status-pill">Live</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with status_cols[1]:
        st.markdown(
            """
            <div class="status-card">
                <div class="status-label">Timeframe</div>
                <div class="status-value">{timeframe}</div>
                <div class="status-pill">{resolution}</div>
            </div>
            """.format(timeframe=selected_timeframe, resolution=selected_resolution),
            unsafe_allow_html=True,
        )
    with status_cols[2]:
        st.markdown(
            """
            <div class="status-card">
                <div class="status-label">Último cierre</div>
                <div class="status-value">{price:.2f}</div>
                <div class="status-pill">{epic}</div>
            </div>
            """.format(price=last_close, epic=live_data["epic"]),
            unsafe_allow_html=True,
        )
    with status_cols[3]:
        if signal:
            st.markdown(
                """
                <div class="status-card">
                    <div class="status-label">Señal</div>
                    <div class="status-value">{direction}</div>
                    <div class="signal-pill {class_name}">{entry}</div>
                </div>
                """.format(direction=signal_label, entry=f"Entrada {signal['entry_price']:.2f}", class_name="signal-bullish" if signal["direction"] == "bullish" else "signal-bearish"),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div class="status-card">
                    <div class="status-label">Señal</div>
                    <div class="status-value">No hay señal</div>
                    <div class="status-pill">Esperando</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    metric_cols = st.columns(3)
    with metric_cols[0]:
        st.metric("Precio actual", f"{current_price:.2f}")
    with metric_cols[1]:
        st.metric("Último cierre", f"{last_close:.2f}")
    with metric_cols[2]:
        st.metric("Estrategia", selected)

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
        if st.button("Enviar señal al Telegram"):
            try:
                result = send_signal_alert(signal)
                st.success(f"Señal enviada a Telegram: {result.get('ok', True)}")
            except Exception as exc:
                st.error(f"No se pudo enviar la señal: {exc}")

    fig.update_layout(
        height=520,
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
        xaxis=dict(showgrid=False, tickfont=dict(color="#cbd5e1")),
        yaxis=dict(showgrid=True, gridcolor="rgba(148, 163, 184, 0.18)", tickfont=dict(color="#cbd5e1")),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Importante: el precio del watcher y del dashboard se basan en el último cierre del timeframe elegido, no en el último tick instantáneo del mercado.")
else:
    if st.session_state.get("live_data_error"):
        st.warning(f"No se pudo cargar Capital.com live: {st.session_state['live_data_error']}")
    else:
        st.info("No hay datos live disponibles todavía.")
