"""Lectura de los CSV originales de Kaggle."""

from pathlib import Path

import pandas as pd

ARCHIVOS = {
    "train": "train.csv",
    "stores": "stores.csv",
    "holidays_events": "holidays_events.csv",
    "oil": "oil.csv",
    "transactions": "transactions.csv",
}


def leer(directorio: Path) -> dict[str, pd.DataFrame]:
    """Lee los cinco CSV y convierte la columna date a fecha. Falla si falta alguno."""
    faltantes = [a for a in ARCHIVOS.values() if not (directorio / a).is_file()]
    if faltantes:
        raise FileNotFoundError(
            f"Faltan archivos de Kaggle en {directorio}: {', '.join(faltantes)}. "
            "Descárgalos de Kaggle y cópialos ahí (ver README.md)."
        )
    datos = {}
    for nombre, archivo in ARCHIVOS.items():
        df = pd.read_csv(directorio / archivo)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        datos[nombre] = df
    datos["train"] = datos["train"].drop(columns="id", errors="ignore")
    return datos
