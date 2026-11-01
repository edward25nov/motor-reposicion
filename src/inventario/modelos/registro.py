"""Registro de modelos: versiones entrenadas, su evaluación, la decisión tomada y cuál es el vigente.

    models/registro.json                 {"vigente": "<version>", "versiones": {...}}
    models/<version>/modelo.joblib       el modelo
"""

import json
import subprocess

import joblib

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


def guardar_modelo(version: str, modelo) -> None:
    ruta = rutas.modelos() / version / "modelo.joblib"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(modelo, ruta, compress=3)


def cargar_modelo(version: str):
    return joblib.load(rutas.modelos() / version / "modelo.joblib")


def vigente() -> tuple[str, object] | None:
    """(versión, modelo) del vigente, o None si todavía no hay ninguno."""
    version = cargar()["vigente"]
    return (version, cargar_modelo(version)) if version else None


def commit_git() -> str:
    try:
        salida = subprocess.run(["git", "rev-parse", "HEAD"], cwd=rutas.raiz(), capture_output=True,
                                text=True, timeout=10)
        return salida.stdout.strip() or "desconocido"
    except (OSError, subprocess.SubprocessError):
        return "desconocido"
