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
    "1h": {"resolution": "HOUR", "hours": 2160},
    "4h": {"resolution": "HOUR_4", "hours": 2160},
    "1d": {"resolution": "DAY", "hours": 2160},
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


def _load_signal_history(csv_path: str = "live/signals_log.csv", limit: int = 200) -> pd.DataFrame:
    """Crea un historial de señales para pintarlas en el gráfico."""
    path = Path(csv_path)
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "direction", "entry_price", "strategy_id"])

    try:
        df = pd.read_csv(path)
    except Exception:
        return pd.DataFrame(columns=["timestamp", "direction", "entry_price", "strategy_id"])

    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df.get("timestamp", pd.Series(dtype="object")), errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").tail(limit)
    df = df.reset_index(drop=True)
    return df


def _compute_macro_zones(macro_context: dict) -> tuple[float | None, float | None]:
    """Obtiene soporte y resistencia macro desde 1h/4h para resaltar el contexto en el gráfico."""
    levels = []
    for tf_name in ("4h", "1h", "1d"):
        frame = macro_context.get(tf_name)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            continue
        recent = frame.tail(80)
        if recent.empty:
            continue
        levels.append({
            "support": float(recent["low"].min()),
            "resistance": float(recent["high"].max()),
        })

    if not levels:
        return None, None

    support = min(item["support"] for item in levels)
    resistance = max(item["resistance"] for item in levels)
    return support, resistance


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
    .chart-legend {
        position: sticky;
        top: 0.5rem;
        z-index: 10;
        display: flex;
        gap: 0.75rem;
        flex-wrap: wrap;
        background: rgba(15, 23, 42, 0.82);
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 12px;
        padding: 0.65rem 0.8rem;
        margin-bottom: 0.8rem;
        box-shadow: 0 6px 18px rgba(15, 23, 42, 0.2);
    }
    .legend-item {
        display: inline-flex;
        align-items: center;
        gap: 0.45rem;
        color: #e2e8f0;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .legend-swatch {
        width: 12px;
        height: 12px;
        border-radius: 50%;
        display: inline-block;
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

st.markdown(
    """
    <div class="chart-legend">
      <div class="legend-item"><span class="legend-swatch" style="background:#22c55e;"></span>Soporte 90d</div>
      <div class="legend-item"><span class="legend-swatch" style="background:#ef4444;"></span>Resistencia 90d</div>
      <div class="legend-item"><span class="legend-swatch" style="background:#f59e0b;"></span>Señal actual</div>
      <div class="legend-item"><span class="legend-swatch" style="background:#38bdf8;"></span>Zona activa</div>
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


def _build_macro_context_for_dashboard(epic: str) -> dict:
    """Trae contexto macro de 90 días para que la zona no dependa del ruido intradía."""
    context = {}
    for tf_name, resolution in {"1h": "HOUR", "4h": "HOUR_4", "1d": "DAY"}.items():
        try:
            data = fetch_recent_candles(epic=epic, resolution=resolution, hours=2160, max_points=3000)
            context[tf_name] = data["df"]
        except Exception:
            pass
    return context

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
            max_points=3000,
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
    macro_context = _build_macro_context_for_dashboard(capital_epic) if selected_timeframe in {"1m", "5m", "15m"} else {}
    signal = build_signal_from_recent_candles(strategy, df, timeframe=selected_timeframe, macro_context=macro_context)
    macro_support, macro_resistance = _compute_macro_zones(macro_context)
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

    metric_cols = st.columns(5)
    with metric_cols[0]:
        st.metric("Precio actual", f"{current_price:.2f}")
    with metric_cols[1]:
        st.metric("Último cierre", f"{last_close:.2f}")
    with metric_cols[2]:
        st.metric("Soporte 90d", f"{macro_support:.2f}" if macro_support is not None else "—")
    with metric_cols[3]:
        st.metric("Resistencia 90d", f"{macro_resistance:.2f}" if macro_resistance is not None else "—")
    with metric_cols[4]:
        zone_state = "Dentro" if macro_support is not None and macro_resistance is not None and macro_support <= current_price <= macro_resistance else "Fuera"
        st.metric("Rango activo", zone_state)

    fig = go.Figure(data=[go.Candlestick(
        x=df["timestamp"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name=live_data["epic"],
    )])

    if macro_support is not None and macro_resistance is not None:
        support_padding = abs(macro_support) * 0.005 if abs(macro_support) > 0 else 0.01
        resistance_padding = abs(macro_resistance) * 0.005 if abs(macro_resistance) > 0 else 0.01
        fig.add_hrect(
            y0=macro_support - support_padding,
            y1=macro_support + support_padding,
            line_width=0,
            fillcolor="rgba(34, 197, 94, 0.12)",
            annotation_text="Soporte 90d",
            annotation_position="top left",
        )
        fig.add_hrect(
            y0=macro_resistance - resistance_padding,
            y1=macro_resistance + resistance_padding,
            line_width=0,
            fillcolor="rgba(239, 68, 68, 0.12)",
            annotation_text="Resistencia 90d",
            annotation_position="top left",
        )
        fig.add_hline(y=macro_support, line_dash="dot", line_color="#22c55e", line_width=1.5, name="Soporte 90d")
        fig.add_hline(y=macro_resistance, line_dash="dot", line_color="#ef4444", line_width=1.5, name="Resistencia 90d")

        zone_active = macro_support <= current_price <= macro_resistance if macro_support is not None and macro_resistance is not None else False
        if zone_active:
            fig.add_hrect(
                y0=min(macro_support, current_price),
                y1=max(macro_resistance, current_price),
                line_width=0,
                fillcolor="rgba(56, 189, 248, 0.09)",
                annotation_text="Zona activa",
                annotation_position="top right",
            )

    signal_history = _load_signal_history()
    if not signal_history.empty:
        chart_start = df["timestamp"].min()
        chart_end = df["timestamp"].max()
        chart_history = signal_history[
            (signal_history["timestamp"] >= chart_start) &
            (signal_history["timestamp"] <= chart_end)
        ].copy()
        for _, row in chart_history.iterrows():
            direction = str(row.get("direction", "")).lower()
            if direction not in {"bullish", "bearish"}:
                continue
            signal_price = float(row.get("entry_price", 0.0) or 0.0)
            color = "#22c55e" if direction == "bullish" else "#ef4444"
            symbol = "triangle-up" if direction == "bullish" else "triangle-down"
            fig.add_trace(go.Scatter(
                x=[pd.Timestamp(row["timestamp"])],
                y=[signal_price],
                mode="markers",
                name=f"Señal histórica {direction}",
                marker=dict(color=color, size=18, symbol=symbol, line=dict(color="white", width=1)),
                hovertemplate=(
                    "<b>Señal histórica</b><br>"
                    f"Dirección: {direction}<br>"
                    "Precio de entrada: %{y:.2f}<br>"
                    "Hora: %{x|%Y-%m-%d %H:%M}<extra></extra>"
                ),
                showlegend=False,
            ))

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
        height=560,
        margin=dict(l=10, r=10, t=10, b=10),
        dragmode="pan",
        hovermode="x unified",
        xaxis_rangeslider_visible=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        font=dict(color="#e2e8f0"),
        xaxis=dict(showgrid=False, tickfont=dict(color="#cbd5e1"), rangeslider=dict(visible=True), type="date"),
        yaxis=dict(showgrid=True, gridcolor="rgba(148, 163, 184, 0.18)", tickfont=dict(color="#cbd5e1")),
        template="plotly_dark",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": True,
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToAdd": [
                "drawline",
                "drawopenpath",
                "drawclosedpath",
                "eraseshape",
                "zoom2d",
                "pan2d",
                "zoomIn2d",
                "zoomOut2d",
                "autoScale2d",
                "resetScale2d",
            ],
            "toImageButtonOptions": {
                "format": "png",
                "filename": f"{selected}-{capital_epic}-chart",
            },
        },
    )
    st.caption("Navegación: arrastra para mover el gráfico, rueda del ratón para hacer zoom y hover para crosshair tipo TradingView.")
    st.caption("Validación por rango activo: el precio debe estar dentro del soporte/resistencia de 90 días para que el contexto de la estrategia sea relevante.")
    st.caption("Importante: el precio del watcher y del dashboard se basan en el último cierre del timeframe elegido, no en el último tick instantáneo del mercado.")
else:
    if st.session_state.get("live_data_error"):
        st.warning(f"No se pudo cargar Capital.com live: {st.session_state['live_data_error']}")
    else:
        st.info("No hay datos live disponibles todavía.")
