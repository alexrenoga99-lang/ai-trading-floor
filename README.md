# AI Trading Floor

Sistema de agentes IA (para usar con GitHub Copilot o Claude) para investigar,
backtestear, validar riesgo y monitorear en vivo estrategias intradía en
NAS100 y XAUUSD.

## Perfil de cuenta
- Capital: $10,000
- Riesgo máximo por operación: 1% ($100)
- RR objetivo: 2:1 a 3:1

## Estructura
- `agents/` — prompts de cada agente (Strategy, Backtest, Rules-Guard, Portfolio, Watcher)
- `strategies/` — estrategias formalizadas en JSON
- `data/` — datos de mercado (históricos y live)
- `engine/` — backtest, métricas y reglas de riesgo
- `dashboard/` — dashboard Streamlit para review del sistema
- `live/` — monitoreo en tiempo real y routing de alertas
- `results/` — resultados de cada backtest

## Estrategia 1 (definida)
Order Block + CHoCH/BOS estructural, NAS100, TF estructura 1H/4H, TF gatillo
1m/5m, RR fijo 3:1, OBs vírgenes únicamente. Ver `strategies/nas100_ob_choch_v1.json`.

## Requisitos del live
- `CAPITAL_API_KEY`
- `CAPITAL_IDENTIFIER`
- `CAPITAL_API_PASSWORD`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Dashboard
```bash
streamlit run dashboard/app.py
```

## Telegram
```bash
export TELEGRAM_BOT_TOKEN="tu_token"
export TELEGRAM_CHAT_ID="tu_chat_id"
```

## Producción en la nube (24/7)

Para que la app siga funcionando aunque GitHub/Codespaces se cierre, debes desplegar dos procesos:

1. Dashboard web: `streamlit run dashboard/app.py`
2. Worker live: `python live/worker.py --timeframe 1m --interval 5`

El worker es el que consulta Capital.com y envía Telegram en tiempo real. El dashboard solo muestra el estado y el gráfico; la lógica operativa vive en el worker.

### Opciones de hosting recomendadas
- Render.com: un servicio web para el dashboard y un worker para la lógica live.
- Railway: igual de sencillo para web + worker.
- Fly.io: muy bueno para 24/7 y workers con persistencia.

### Variables requeridas en la nube
```bash
export CAPITAL_API_KEY="..."
export CAPITAL_IDENTIFIER="..."
export CAPITAL_API_PASSWORD="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
```

### Cómo dejarlo corriendo sin parar
- Crear un servicio web para Streamlit.
- Crear un worker/cronjob para `live/worker.py`.
- Dejar `render.yaml` y el proceso `worker.py` como base del despliegue.

## Próximos pasos
1. Validar la descarga de candles live desde Capital.com.
2. Completar la señal en el Watcher Agent y mandar alertas por Telegram.
3. Lanzar el dashboard con el flujo en vivo.
4. Reforzar la gestión del riesgo y la validación de señales.
5. Desplegar el dashboard y el worker en la nube para 24/7.
