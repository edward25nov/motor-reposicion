"""Esquema temporal común: qué cortes se evalúan y con qué filas se entrena cada modelo.

Un corte c se puede evaluar en el snapshot S si todo su horizonte ya se observó:
c + horizonte <= S - atraso de ventas. Para evaluar a partir del corte c0, solo se entrena con
filas cuyo objetivo se conocía en c0 (fecha <= c0 - atraso) y con cortes de la ventana configurada.
"""

import pandas as pd

from inventario.preparacion.preparar import cortes_semanales


def cortes_evaluables(snapshot: str, n: int, cfg_prep: dict) -> list[pd.Timestamp]:
    """Los n cortes más recientes con el horizonte completo observado en snapshot."""
    ultimo = (pd.Timestamp(snapshot) - pd.Timedelta(days=cfg_prep["disponibilidad"]["ventas_atraso"])
              - pd.Timedelta(days=cfg_prep["corte"]["horizonte_dias"]))
    cortes = cortes_semanales(ultimo - pd.Timedelta(weeks=n + 1), ultimo, cfg_prep)
    if len(cortes) < n:
        raise ValueError(f"No hay {n} cortes evaluables antes de {snapshot}")
    return cortes[-n:]


def filas_entrenamiento(tabla: pd.DataFrame, inicio_eval: pd.Timestamp, cfg_modelo: dict,
                        cfg_prep: dict) -> pd.DataFrame:
    conocido = inicio_eval - pd.Timedelta(days=cfg_prep["disponibilidad"]["ventas_atraso"])
    desde = inicio_eval - pd.Timedelta(weeks=cfg_modelo["entrenamiento"]["ventana_semanas"])
    return tabla[(tabla["fecha"] <= conocido) & (tabla["corte"] >= desde)]
