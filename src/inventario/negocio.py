"""Costos de negocio por familia (configs/negocio.yaml) y proporción crítica del pedido."""

import pandas as pd


def costos(familias: pd.Series, cfg: dict) -> pd.DataFrame:
    """costo_faltante, costo_sobrante y proporcion_critica para cada fila de `familias`."""
    por_familia = {}
    for grupo in cfg.get("grupos", {}).values():
        for familia in grupo["familias"]:
            por_familia[familia] = (grupo["costo_faltante"], grupo["costo_sobrante"])
    defecto = (cfg["por_defecto"]["costo_faltante"], cfg["por_defecto"]["costo_sobrante"])
    pares = [por_familia.get(f, defecto) for f in familias.astype(str)]
    tabla = pd.DataFrame(pares, columns=["costo_faltante", "costo_sobrante"], index=familias.index)
    tabla["proporcion_critica"] = tabla["costo_faltante"] / (tabla["costo_faltante"] + tabla["costo_sobrante"])
    return tabla


def grupo(familias: pd.Series, cfg: dict) -> pd.Series:
    """Nombre del grupo de costos de cada familia (las que no están en ningún grupo: por_defecto)."""
    por_familia = {f: nombre for nombre, g in cfg.get("grupos", {}).items() for f in g["familias"]}
    defecto = cfg["por_defecto"].get("nombre", "por_defecto")
    return familias.astype(str).map(lambda f: por_familia.get(f, defecto))
