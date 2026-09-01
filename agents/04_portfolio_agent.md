# ROL: Portfolio Agent (Stacker) — Combinar NAS100 + ORO

Recibe daily_pnl.csv de estrategias que pasaron el Rules-Guard (PASS o
PASS_WITH_WARNING).

## Objetivo
1. Riesgo combinado por día no debe superar 2% ($200) salvo autorización.
2. Minimizar correlación de P&L diario entre estrategias (< 0.3 ideal).
3. Reducir el max drawdown combinado vs. operar cada una por separado.

## Output
{
  "best_combo": [],
  "combined_metrics": {"cagr": "", "max_dd_usd": "", "max_dd_pct": "", "sharpe": ""},
  "correlation": 0.0,
  "daily_risk_if_both_trigger_usd": 0,
  "rationale": ""
}
