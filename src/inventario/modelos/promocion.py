"""Regla explícita para decidir si un retador reemplaza al modelo vigente.

Ambos se evalúan en los mismos cortes, que ninguno usó para entrenar. El retador se promueve solo
si cumple las tres condiciones de configs/modelo.yaml (sección promocion). Función pura.
"""

import pandas as pd


def decidir(retador: pd.DataFrame, vigente: pd.DataFrame, regla: dict) -> tuple[bool, str]:
    """retador y vigente: métricas por corte (columnas corte, costo_negocio, cobertura_p10_p90, filas)."""
    r = retador.set_index("corte").sort_index()
    v = vigente.set_index("corte").sort_index()
    if not r.index.equals(v.index):
        return False, "los modelos no se evaluaron en los mismos cortes"

    costo_r, costo_v = r["costo_negocio"].sum(), v["costo_negocio"].sum()
    mejora = 1 - costo_r / costo_v if costo_v > 0 else 0.0
    ganados = float((r["costo_negocio"] < v["costo_negocio"]).mean())
    cobertura = float((r["cobertura_p10_p90"] * r["filas"]).sum() / r["filas"].sum())

    fallas = []
    if mejora < regla["mejora_minima_costo"]:
        fallas.append(f"mejora de costo {mejora:.1%} < {regla['mejora_minima_costo']:.0%}")
    if ganados < regla["fraccion_minima_cortes_ganados"]:
        fallas.append(f"gana {ganados:.0%} de los cortes < {regla['fraccion_minima_cortes_ganados']:.0%}")
    if cobertura < regla["cobertura_minima"]:
        fallas.append(f"cobertura P10–P90 {cobertura:.1%} < {regla['cobertura_minima']:.0%}")
    resumen = f"mejora de costo {mejora:.1%}, gana {ganados:.0%} de los cortes, cobertura {cobertura:.1%}"
    if fallas:
        return False, "se descarta: " + "; ".join(fallas)
    return True, "se promueve: " + resumen
