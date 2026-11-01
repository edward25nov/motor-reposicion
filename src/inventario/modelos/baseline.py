"""Baseline: ingenuo estacional con cuantiles empíricos de su error.

El punto central es la media (en log) del mismo día de la semana de las últimas 4 semanas; si no
hay, la media de 28 días; si tampoco, cero. Los cuantiles salen de los residuos de entrenamiento
por familia: pred_q = expm1(base + cuantil_q(residuo de la familia)).
"""

import numpy as np
import pandas as pd

from inventario.modelos.base import finalizar, objetivo_log


class Baseline:
    tipo = "baseline"

    def __init__(self, cuantiles: list[float]):
        self.cuantiles = list(cuantiles)
        self.desvios: pd.DataFrame | None = None   # familia x cuantil
        self.desvio_global: np.ndarray | None = None

    @staticmethod
    def base(tabla: pd.DataFrame) -> pd.Series:
        return tabla["mismo_dia_4"].fillna(tabla["media_28"]).fillna(0.0)

    def ajustar(self, tabla: pd.DataFrame) -> "Baseline":
        residuo = objetivo_log(tabla) - self.base(tabla)
        familia = tabla["family"].astype(str)
        self.desvios = residuo.groupby(familia).quantile(self.cuantiles).unstack()
        self.desvio_global = residuo.quantile(self.cuantiles).to_numpy()
        return self

    def predecir(self, tabla: pd.DataFrame) -> pd.DataFrame:
        desvio = self.desvios.reindex(tabla["family"].astype(str)).to_numpy()
        desvio = np.where(np.isnan(desvio), self.desvio_global, desvio)
        log_pred = self.base(tabla).to_numpy()[:, None] + desvio
        return finalizar(log_pred, tabla, self.cuantiles)
