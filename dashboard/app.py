"""
Dashboard visual con Streamlit para el AI Trading Floor.
Reutiliza engine/backtester.py, engine/structure.py, engine/rules_guard.py
sin modificarlos.

Ejecutar con:
    streamlit run dashboard/app.py
"""
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.backtester import load_ohlcv, run_backtest
from engine.rules_guard import evaluate as rules_guard_evaluate
from engine.structure import find_swings, detect_bos_choch, find_order_blocks

st.set_page_config(page_title="AI Trading Floor", layout="wide")
st.title("AI Trading Floor - Dashboard")

# --- Selector de estrategia ---
strategy_files = list(Path("strategies").glob("*.json"))
strategy_names = [f.stem for f in strategy_files]
selected = st.sidebar.selectbox("Estrategia", strategy_names)

with open(f"strategies/{selected}.json") as f:
    strategy = json.load(f)

st.sidebar.json(strategy, expanded=False)

structure_path = st.sidebar.text_input("CSV Estructura (1H/4H)", "data/nas100/nas100_1h.csv")
trigger_path = st.sidebar.text_input("CSV Gatillo (1m/5m)", "data/nas100/nas100_5m.csv")

tab1, tab2, tab3 = st.tabs(["Grafico + Order Blocks", "Backtest", "Rules-Guard"])

# --- TAB 1: Grafico de velas con Order Blocks ---
with tab1:
    if Path(structure_path).exists():
        df = load_ohlcv(structure_path)
        df = find_swings(df)
        df = detect_bos_choch(df)
        order_blocks = find_order_blocks(df)

        fig = go.Figure(data=[go.Candlestick(
            x=df["timestamp"], open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name="Precio"
        )])

        for ob in order_blocks:
            color = "rgba(0,255,0,0.2)" if ob["direction"] == "bullish" else "rgba(255,0,0,0.2)"
            fig.add_shape(
                type="rect",
                x0=df["timestamp"].iloc[ob["index"]], x1=df["timestamp"].iloc[-1],
                y0=ob["low"], y1=ob["high"],
                fillcolor=color, line=dict(width=0),
            )

        fig.update_layout(height=600, xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"{len(order_blocks)} Order Blocks detectados en el TF de estructura.")
    else:
        st.warning(f"No se encontro el archivo {structure_path}. Descarga los datos primero con scripts/fetch_data.py.")

# --- TAB 2: Backtest ---
with tab2:
    if st.button("Correr Backtest", type="primary"):
        if Path(structure_path).exists() and Path(trigger_path).exists():
            structure_df = load_ohlcv(structure_path)
            trigger_df = load_ohlcv(trigger_path)
            with st.spinner("Ejecutando backtest..."):
                result = run_backtest(strategy, structure_df, trigger_df)

            st.session_state["backtest_result"] = result
        else:
            st.error("Faltan los archivos de datos. Verifica las rutas en la barra lateral.")

    if "backtest_result" in st.session_state:
        result = st.session_state["backtest_result"]
        metrics = result["metrics"]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Win Rate", f"{metrics.get('win_rate', 0)}%")
        col2.metric("Expectancy", f"${metrics.get('expectancy_usd', 0)}")
        col3.metric("Max Drawdown", f"${metrics.get('max_drawdown_usd', 0)}")
        col4.metric("Sharpe", f"{metrics.get('sharpe', 0)}")

        if not result["daily_pnl"].empty:
            equity = 10000 + result["daily_pnl"]["pnl_usd"].cumsum()
            fig_eq = go.Figure(go.Scatter(x=result["daily_pnl"]["date"], y=equity, mode="lines"))
            fig_eq.update_layout(title="Curva de Equity", height=400)
            st.plotly_chart(fig_eq, use_container_width=True)

        st.subheader("Trades")
        st.dataframe(result["trades"], use_container_width=True)

# --- TAB 3: Rules-Guard ---
with tab3:
    if "backtest_result" in st.session_state:
        result = st.session_state["backtest_result"]
        verdict = rules_guard_evaluate(result["daily_pnl"], result["trades"])

        color = {"PASS": "[PASS]", "PASS_WITH_WARNING": "[WARNING]", "FAIL": "[FAIL]"}[verdict["verdict"]]
        st.header(f"{color} Veredicto: {verdict['verdict']}")

        col1, col2, col3 = st.columns(3)
        col1.metric("Peor dia", f"${verdict['worst_day_usd']}")
        col2.metric("Max. perdidas seguidas", verdict["max_consecutive_losses"])
        col3.metric("% sesiones sobrevividas", f"{verdict['sessions_survived_pct']}%")

        if verdict["breach_events"]:
            st.subheader("Eventos de ruptura de reglas")
            st.dataframe(pd.DataFrame(verdict["breach_events"]), use_container_width=True)
    else:
        st.info("Corre primero un backtest en la pestana anterior.")
