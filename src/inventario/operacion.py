"""Decisiones de operación que toman los DAGs, como funciones con pruebas.

Los DAGs solo orquestan: cada tarea llama a una función de este paquete con la fecha lógica.
"""

import pandas as pd

from inventario import config
from inventario.modelos import entrenar, registro


def toca_reentrenar(corte: str, reg: dict, cfg_modelo: dict) -> bool:
    """Sí si no hay modelo vigente al corte o si el último retador anterior al corte tiene N semanas."""
    corte_ts = pd.Timestamp(corte)
    if registro.vigente_al(corte_ts, reg) is None:
        return True
    snapshots = [pd.Timestamp(v["snapshot"]) for v in reg["versiones"].values()
                 if v["tipo"] == "gbm" and pd.Timestamp(v["snapshot"]) <= corte_ts]
    if not snapshots:
        return True
    semanas = cfg_modelo["entrenamiento"]["reentrenar_cada_semanas"]
    return corte_ts - max(snapshots) >= pd.Timedelta(weeks=semanas)


def entrenar_si_corresponde(corte: str) -> str:
    """Entrena un retador en el corte si corresponde; devuelve la versión vigente en el corte."""
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    reg = registro.cargar()
    if toca_reentrenar(corte, reg, config.cargar("modelo")):
        reg = entrenar.ejecutar(corte)
    else:
        print(f"entrenar {corte}: no corresponde reentrenar")
    vigente = registro.vigente_al(corte, reg)
    print(f"entrenar {corte}: vigente en el corte: {vigente}")
    return vigente
