"""Piezas comunes de los modelos: columnas de entrada, nombres de cuantiles y post-proceso."""

import numpy as np
import pandas as pd

CATEGORICAS = ["store_nbr", "family", "city", "state", "tipo_tienda"]
NUMERICAS = [
    "media_7", "media_14", "media_28", "media_56", "ultimo", "cobertura_7", "ceros_28",
    "dias_historia", "tendencia_7_28", "promo_media_28", "transacciones_28", "petroleo",
    "petroleo_cambio_28", "cluster", "h", "dia_semana", "dia_mes", "mes", "quincena",
    "mismo_dia_4", "mismo_dia_8", "promo", "feriado_nacional", "feriado_local", "evento",
    "dia_laboral_compensado",
]
FEATURES = CATEGORICAS + NUMERICAS


def columna(q: float) -> str:
    """Nombre de la columna del cuantil q: 0.9 -> 'p90'."""
    return f"p{round(q * 100):02d}"


def objetivo_log(tabla: pd.DataFrame) -> pd.Series:
    return np.log1p(tabla["ventas"].clip(lower=0))


def inactiva(tabla: pd.DataFrame) -> np.ndarray:
    """Series sin ninguna venta en los últimos 56 días conocidos: se pronostica cero."""
    return (tabla["media_56"] == 0).to_numpy()


def finalizar(log_pred: np.ndarray, tabla: pd.DataFrame, cuantiles: list[float]) -> pd.DataFrame:
    """Pasa de log a unidades, ordena los cuantiles (sin cruces), recorta en cero y aplica inactivas."""
    pred = np.clip(np.expm1(np.sort(log_pred, axis=1)), 0, None)
    pred[inactiva(tabla)] = 0.0
    return pd.DataFrame(pred, columns=[columna(q) for q in cuantiles], index=tabla.index)
