"""Pronóstico y pedido sugerido de un corte. Funciones puras: no leen ni escriben archivos.

El pedido de cada tienda y familia es la demanda que conviene cubrir en el periodo de cobertura:
la suma, día por día, del pronóstico interpolado en la proporción crítica de la familia
(configs/negocio.yaml), menos el inventario disponible, redondeada hacia arriba.
"""

import numpy as np
import pandas as pd

from inventario import negocio
from inventario.modelos.base import columna
from inventario.modelos.metricas import cantidad_critica

LLAVE = ["store_nbr", "family"]


def pronostico(features: pd.DataFrame, modelo, version: str, cuantiles: list[float]) -> pd.DataFrame:
    pred = modelo.predecir(features)
    base = features[["corte", "fecha", "h", *LLAVE]].reset_index(drop=True)
    base["family"] = base["family"].astype(str)
    return pd.concat([base, pred.reset_index(drop=True)[[columna(q) for q in cuantiles]]], axis=1) \
        .assign(modelo=version)


def periodo_cobertura(corte, cfg_negocio: dict, horizonte: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    p = cfg_negocio["pedido"]
    if p["dias_hasta_entrega"] + p["dias_cobertura"] - 1 > horizonte:
        raise ValueError("El periodo de cobertura del pedido no cabe en el horizonte del pronóstico")
    desde = pd.Timestamp(corte) + pd.Timedelta(days=p["dias_hasta_entrega"])
    return desde, desde + pd.Timedelta(days=p["dias_cobertura"] - 1)


def calcular(pron: pd.DataFrame, cuantiles: list[float], cfg_negocio: dict, horizonte: int) -> pd.DataFrame:
    corte = pron["corte"].iloc[0]
    desde, hasta = periodo_cobertura(corte, cfg_negocio, horizonte)
    dias = pron[pron["fecha"].between(desde, hasta)].copy()
    costos = negocio.costos(dias["family"], cfg_negocio)
    dias["cantidad_dia"] = cantidad_critica(dias, cuantiles, costos["proporcion_critica"])
    dias = pd.concat([dias, costos], axis=1)
    pedido = dias.groupby(LLAVE, as_index=False).agg(
        demanda_p50=("p50", "sum"),
        demanda_critica=("cantidad_dia", "sum"),
        proporcion_critica=("proporcion_critica", "first"),
        costo_faltante=("costo_faltante", "first"),
        costo_sobrante=("costo_sobrante", "first"),
        modelo=("modelo", "first"),
    )
    inventario = cfg_negocio["pedido"]["inventario_disponible"]
    pedido["inventario_disponible"] = inventario
    neto = np.clip(pedido["demanda_critica"] - inventario, 0, None).round(6)
    pedido["cantidad_sugerida"] = np.ceil(neto) + 0.0   # + 0.0 evita -0.0
    pedido.insert(0, "corte", corte)
    pedido.insert(1, "entrega", desde)
    pedido.insert(2, "cobertura_hasta", hasta)
    return pedido.round({"demanda_p50": 3, "demanda_critica": 3, "proporcion_critica": 4})
