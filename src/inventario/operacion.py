"""Decisiones de operación que toman los DAGs, como funciones con pruebas.

Los DAGs solo orquestan: cada tarea llama a una función de este paquete con la fecha lógica.
"""

import pandas as pd

from inventario import config, rutas
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


# --- Fin de la operación simulada -----------------------------------------------------------
# La bandeja simulada termina en algún momento. Más allá de su última llegada no hay nada que
# procesar: las tareas se omiten (no fallan). Dentro del periodo, la falta de datos que sí debían
# llegar sigue siendo un error (DatosInsuficientes). En producción la bandeja no termina y estas
# guardas no omitirían nada.

def _bandeja() -> list[tuple[str, str, str]]:
    """(llegada, fuente, clave) de todos los archivos de la bandeja."""
    archivos = []
    for carpeta in (rutas.origen() / "bandeja").glob("llegada=*"):
        llegada = carpeta.name.removeprefix("llegada=")
        for ruta in carpeta.glob("*.csv"):
            fuente, _, clave = ruta.stem.partition("_")
            archivos.append((llegada, fuente, clave))
    return archivos


def hay_bandeja(fecha: str) -> bool:
    """La fecha está dentro del periodo de la bandeja (hasta su última llegada)."""
    llegadas = [a[0] for a in _bandeja()]
    dentro = bool(llegadas) and pd.Timestamp(fecha) <= pd.Timestamp(max(llegadas))
    if not dentro:
        print(f"{fecha}: posterior a la última llegada de la bandeja ({max(llegadas, default='ninguna')}): se omite")
    return dentro


def hay_ventas_para_corte(fecha: str) -> bool:
    """El origen llegó a tener ventas suficientemente recientes para pronosticar en el corte."""
    disp = config.cargar("preparacion")["disponibilidad"]
    ventas = [pd.Timestamp(a[2]) for a in _bandeja() if a[1] == "ventas"]
    if not ventas:
        return False
    necesaria = pd.Timestamp(fecha) - pd.Timedelta(days=disp["ventas_atraso"] + disp["tolerancia_atraso_ventas"])
    dentro = necesaria <= max(ventas)
    if not dentro:
        print(f"{fecha}: la bandeja no tiene ventas posteriores al {max(ventas):%Y-%m-%d}: "
              "fin de la operación simulada, se omite")
    return dentro
