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
- `data/` — datos históricos (no incluidos aún)
- `engine/` — motor de backtest, métricas, reglas de riesgo, correlación (pendiente)
- `results/` — resultados de cada backtest (pendiente)
- `live/` — módulos de monitoreo en tiempo real y alertas (pendiente)

## Estrategia 1 (definida)
Order Block + CHoCH/BOS estructural, NAS100, TF estructura 1H/4H, TF gatillo
1m/5m, RR fijo 3:1, OBs vírgenes únicamente. Ver `strategies/nas100_ob_choch_v1.json`.

## Próximos pasos
1. Descargar datos históricos.
2. Implementar `engine/backtester.py`.
3. Correr Backtest Agent sobre la estrategia 1.
4. Correr Rules-Guard Agent.
