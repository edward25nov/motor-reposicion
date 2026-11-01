"""Registro de modelos: versiones entrenadas, su evaluación, la decisión tomada y cuál es el vigente.

    models/registro.json                 {"vigente": "<version>", "versiones": {...}}
    models/<version>/modelo.pkl.gz       el modelo (pickle estándar comprimido)

El vigente se consulta "as-of": en el corte T vale la última versión aprobada (vigente inicial o
promovida) con snapshot <= T. Así un corte nunca usa un modelo entrenado con datos posteriores,
aunque los cortes se procesen fuera de orden.
"""

import gzip
import json
import pickle
import subprocess
from pathlib import Path

import pandas as pd

from inventario import rutas


def _ruta():
    return rutas.modelos() / "registro.json"


def cargar() -> dict:
    ruta = _ruta()
    if not ruta.is_file():
        return {"vigente": None, "versiones": {}}
    return json.loads(ruta.read_text(encoding="utf-8"))


def guardar(registro: dict) -> None:
    ruta = _ruta()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(registro, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(ruta)


def ruta_modelo(version: str) -> Path:
    return rutas.modelos() / version / "modelo.pkl.gz"


def guardar_modelo(version: str, modelo) -> None:
    """Guarda con el pickler en C de Python, comprimido con gzip sin fecha (archivo determinista).

    No se usa joblib: su pickler es el de Python puro, que `dill` modifica de forma global apenas se
    importa (Airflow lo importa en las tareas), y el archivo quedaba dependiendo de `dill`.
    """
    ruta = ruta_modelo(version)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with open(tmp, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
        pickle.dump(modelo, gz, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(ruta)


def cargar_modelo(version: str):
    with gzip.open(ruta_modelo(version), "rb") as gz:
        return pickle.load(gz)


APROBADAS = ("vigente inicial", "promovido")


def vigente_al(corte, reg: dict | None = None) -> str | None:
    """Versión vigente en el corte: la última aprobada con snapshot <= corte (o None)."""
    reg = reg if reg is not None else cargar()
    corte = pd.Timestamp(corte)
    vigente = None
    # En un mismo snapshot el baseline (vigente inicial) va antes que el retador que se le compara.
    for nombre, v in sorted(reg["versiones"].items(), key=lambda kv: (kv[1]["snapshot"], kv[1]["tipo"] != "baseline")):
        if pd.Timestamp(v["snapshot"]) > corte:
            break
        if v["decision"] in APROBADAS:
            vigente = nombre
    return vigente


def vigente(corte) -> tuple[str, object] | None:
    """(versión, modelo) vigente en el corte, o None si todavía no hay ninguno."""
    version = vigente_al(corte)
    return (version, cargar_modelo(version)) if version else None


# Lo que define el resultado: el código y la configuración. Los punteros .dvc los modifica el
# propio flujo en cada corte (versionar), así que no cuentan como cambios del código.
CODIGO = ("src", "dags", "configs", "requirements.txt", "airflow/Dockerfile", "airflow/docker-compose.yaml")


def cambios_sin_commit(raiz: Path | None = None) -> bool | None:
    """True si el código o la configuración tienen cambios sin commit; None si no hay Git."""
    try:
        salida = subprocess.run(["git", "status", "--porcelain", "--", *CODIGO], cwd=raiz or rutas.raiz(),
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(salida.stdout.strip()) if salida.returncode == 0 else None


def commit_git() -> str:
    try:
        salida = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rutas.raiz(), capture_output=True,
                                text=True, timeout=10)
        return salida.stdout.strip() or "desconocido"
    except (OSError, subprocess.SubprocessError):
        return "desconocido"
