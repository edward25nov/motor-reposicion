"""Preparación de los datos del modelo para una fecha de corte.

Lee cada fuente tal como se conocía en el corte (vigente.leer), revisa que haya datos suficientes
para pronosticar y escribe:
    data/procesados/features/corte=<AAAA-MM-DD>.parquet   una fila por serie y día del horizonte
    data/procesados/calidad/corte=<AAAA-MM-DD>.json       qué datos había y qué faltaba

Es idempotente: reescribe los archivos del corte con el mismo contenido.

Uso:
    PYTHONPATH=src python -m inventario.preparacion.preparar 2017-07-17
"""

import json
import sys

import numpy as np
import pandas as pd

from inventario import config, rutas
from inventario.ingesta import vigente
from inventario.preparacion.features import Insumos, features_corte

FUENTES = ("ventas", "promociones", "transacciones", "petroleo", "feriados", "tiendas")


class DatosInsuficientes(Exception):
    """Faltan datos recientes de ventas: pronosticar así no es confiable."""


def datos_al_corte(corte: str) -> dict[str, pd.DataFrame]:
    return {f: vigente.leer(f, corte) for f in FUENTES}


def calidad(ins: Insumos, corte: str, cfg: dict) -> dict:
    """Resumen de los datos disponibles; falla si las ventas están demasiado atrasadas."""
    T = pd.Timestamp(corte)
    disp = cfg["disponibilidad"]
    esperada = T - pd.Timedelta(days=disp["ventas_atraso"])
    con_dato = ins.fechas[~np.all(np.isnan(ins.ventas), axis=0)]
    con_dato = con_dato[con_dato <= esperada]
    ultima = con_dato.max() if len(con_dato) else None
    ultimos_7 = pd.date_range(esperada - pd.Timedelta(days=6), esperada)
    resumen = {
        "corte": T.strftime("%Y-%m-%d"),
        "ultima_venta_esperada": esperada.strftime("%Y-%m-%d"),
        "ultima_venta_disponible": ultima.strftime("%Y-%m-%d") if ultima is not None else None,
        "dias_sin_ventas_ultimos_7": [d.strftime("%Y-%m-%d") for d in ultimos_7 if d not in set(con_dato)],
        "series": len(ins.series),
        "tiendas": int(ins.series["store_nbr"].nunique()),
    }
    limite = esperada - pd.Timedelta(days=disp["tolerancia_atraso_ventas"])
    if ultima is None or ultima < limite:
        raise DatosInsuficientes(
            f"Corte {resumen['corte']}: la última venta disponible es {resumen['ultima_venta_disponible']} "
            f"y se necesita al menos {limite:%Y-%m-%d}. No se pronostica con datos tan atrasados."
        )
    return resumen


def ejecutar(corte: str) -> str:
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    cfg = config.cargar("preparacion")
    ins = Insumos.desde(datos_al_corte(corte))
    resumen = calidad(ins, corte, cfg)
    tabla = features_corte(ins, corte, cfg)
    resumen["filas"] = len(tabla)

    base = rutas.raiz() / "data" / "procesados"
    destino = base / "features" / f"corte={corte}.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tabla.to_parquet(tmp, index=False)
    tmp.replace(destino)
    reporte = base / "calidad" / f"corte={corte}.json"
    reporte.parent.mkdir(parents=True, exist_ok=True)
    reporte.write_text(json.dumps(resumen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"preparacion {corte}: {len(tabla)} filas; última venta {resumen['ultima_venta_disponible']}; "
          f"días sin ventas en la última semana: {resumen['dias_sin_ventas_ultimos_7'] or 'ninguno'}")
    return str(destino)


def cortes_semanales(desde: str, hasta: str, cfg: dict) -> list[pd.Timestamp]:
    """Fechas de corte (el día de la semana configurado) entre desde y hasta, inclusive."""
    dias = pd.date_range(desde, hasta)
    return list(dias[dias.day_of_week == cfg["corte"]["dia_semana"]])


def entrenamiento(snapshot: str, desde: str, hasta: str) -> pd.DataFrame:
    """Filas de features con su venta real para los cortes semanales entre desde y hasta.

    Usa una sola vista de los datos: la conocida en `snapshot` (vigente.leer). Cada corte del
    pasado aplica sus propias reglas de disponibilidad, así ninguna fila ve ventas posteriores a
    su corte. Solo se incluyen filas cuyo objetivo ya se conocía en el snapshot.
    """
    cfg = config.cargar("preparacion")
    ins = Insumos.desde(datos_al_corte(snapshot))
    tablas = [features_corte(ins, c, cfg) for c in cortes_semanales(desde, hasta, cfg)]
    tabla = pd.concat(tablas, ignore_index=True)
    conocido = pd.Timestamp(snapshot) - pd.Timedelta(days=cfg["disponibilidad"]["ventas_atraso"])
    tabla = tabla[tabla["ventas"].notna() & (tabla["fecha"] <= conocido)].reset_index(drop=True)
    texto = ["family", "city", "state", "tipo_tienda"]
    reales = [c for c in tabla.select_dtypes("float64").columns if c != "ventas"]
    return tabla.astype({**{c: "category" for c in texto}, **{c: "float32" for c in reales}})


if __name__ == "__main__":
    ejecutar(sys.argv[1])
