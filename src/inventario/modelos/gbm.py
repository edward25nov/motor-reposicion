"""Modelo de ML: un HistGradientBoostingRegressor con pérdida cuantílica por cada cuantil.

Un solo modelo global para todas las tiendas, familias y días del horizonte, entrenado sobre
log(1 + ventas). Los cuantiles se conservan al volver a unidades (expm1 es creciente).
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from inventario.modelos.base import CATEGORICAS, FEATURES, finalizar, objetivo_log


class GBMCuantiles:
    tipo = "gbm"

    def __init__(self, cuantiles: list[float], params: dict):
        self.cuantiles = list(cuantiles)
        self.params = dict(params)
        self.categorias: dict[str, list] = {}
        self.modelos: list[HistGradientBoostingRegressor] = []

    def _entrada(self, tabla: pd.DataFrame) -> pd.DataFrame:
        X = tabla[FEATURES].copy()
        for c in CATEGORICAS:
            X[c] = pd.Categorical(X[c].astype(str), categories=self.categorias[c])
        return X

    def ajustar(self, tabla: pd.DataFrame) -> "GBMCuantiles":
        self.categorias = {c: sorted(tabla[c].astype(str).unique()) for c in CATEGORICAS}
        X, y = self._entrada(tabla), objetivo_log(tabla)
        self.modelos = [
            HistGradientBoostingRegressor(loss="quantile", quantile=q, categorical_features="from_dtype",
                                          early_stopping=False, **self.params).fit(X, y)
            for q in self.cuantiles
        ]
        return self

    def predecir(self, tabla: pd.DataFrame) -> pd.DataFrame:
        X = self._entrada(tabla)
        log_pred = np.column_stack([m.predict(X) for m in self.modelos])
        return finalizar(log_pred, tabla, self.cuantiles)
