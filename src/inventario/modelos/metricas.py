"""Métricas técnicas del pronóstico y métrica de negocio.

Técnicas: WAPE y sesgo del P50, RMSLE del P50, pinball promedio de los cuantiles (normalizada por
las ventas reales) y cobertura del intervalo P10–P90.
Negocio: costo de cubrir cada día la cantidad del cuantil crítico de su familia
(costo_faltante × faltante + costo_sobrante × sobrante), con los costos de configs/negocio.yaml.
"""

import numpy as np
import pandas as pd

from inventario import negocio
from inventario.modelos.base import columna


def cantidad_critica(pred: pd.DataFrame, cuantiles: list[float], proporcion: pd.Series) -> np.ndarray:
    """Interpola, fila por fila, el valor del pronóstico en la proporción crítica de su familia."""
    qs = np.asarray(cuantiles)
    valores = pred[[columna(q) for q in cuantiles]].to_numpy()
    fuera = sorted(set(proporcion[(proporcion < qs[0]) | (proporcion > qs[-1])].round(3)))
    if fuera:
        # El modelo no estima cuantiles fuera de [P10, P95]: más allá de eso el pedido ya no sigue a
        # los costos. Para cubrir proporciones más extremas hay que agregar cuantiles en modelo.yaml.
        print(f"ADVERTENCIA: proporción crítica {fuera} fuera de los cuantiles del modelo "
              f"[{qs[0]}, {qs[-1]}]: se usa el cuantil más cercano")
    p = np.clip(proporcion.to_numpy(), qs[0], qs[-1])
    j = np.clip(np.searchsorted(qs, p, side="right") - 1, 0, len(qs) - 2)
    peso = (p - qs[j]) / (qs[j + 1] - qs[j])
    filas = np.arange(len(valores))
    return valores[filas, j] * (1 - peso) + valores[filas, j + 1] * peso


def costo_negocio(real: pd.Series, cantidad: np.ndarray, costos: pd.DataFrame) -> np.ndarray:
    faltante = np.clip(real.to_numpy() - cantidad, 0, None)
    sobrante = np.clip(cantidad - real.to_numpy(), 0, None)
    return costos["costo_faltante"].to_numpy() * faltante + costos["costo_sobrante"].to_numpy() * sobrante


def detalle(tabla: pd.DataFrame, pred: pd.DataFrame, cuantiles: list[float], cfg_negocio: dict) -> pd.DataFrame:
    """Por fila: real, p50 y las piezas que se agregan en `resumir`."""
    real = tabla["ventas"].clip(lower=0)
    costos = negocio.costos(tabla["family"], cfg_negocio)
    d = pd.DataFrame({"corte": tabla["corte"].to_numpy(), "real": real.to_numpy(),
                      "p50": pred["p50"].to_numpy()}, index=tabla.index)
    d["error_abs"] = (d["p50"] - d["real"]).abs()
    d["error"] = d["p50"] - d["real"]
    d["error_log2"] = (np.log1p(d["p50"]) - np.log1p(d["real"])) ** 2
    pinball = 0.0
    for q in cuantiles:
        e = d["real"] - pred[columna(q)]
        pinball = pinball + np.maximum(q * e, (q - 1) * e)
    d["pinball"] = pinball / len(cuantiles)
    d["cubierto"] = ((d["real"] >= pred["p10"]) & (d["real"] <= pred["p90"])).astype(float)
    d["costo"] = costo_negocio(real, cantidad_critica(pred, cuantiles, costos["proporcion_critica"]), costos)
    return d


def resumir(d: pd.DataFrame) -> dict:
    total = d["real"].sum()
    return {
        "wape": float(d["error_abs"].sum() / total),
        "sesgo": float(d["error"].sum() / total),
        "rmsle": float(np.sqrt(d["error_log2"].mean())),
        "pinball": float(d["pinball"].sum() / total),
        "cobertura_p10_p90": float(d["cubierto"].mean()),
        "costo_negocio": float(d["costo"].sum()),
        "filas": int(len(d)),
    }


def por_corte(d: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame([{"corte": c, **resumir(g)} for c, g in d.groupby("corte")])
