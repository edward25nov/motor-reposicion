"""Rutas del proyecto, relativas a la raíz del repositorio.

La raíz se puede cambiar con la variable de entorno MOTOR_RAIZ (lo usan las pruebas
y los contenedores de Airflow).
"""

import os
from pathlib import Path

_RAIZ_POR_DEFECTO = Path(__file__).resolve().parents[2]


def raiz() -> Path:
    return Path(os.environ.get("MOTOR_RAIZ", _RAIZ_POR_DEFECTO))


def configs() -> Path:
    return raiz() / "configs"


def kaggle() -> Path:
    """Donde se colocan los CSV originales de Kaggle (versionados con DVC)."""
    return raiz() / "data" / "raw" / "kaggle"


def origen() -> Path:
    """Sistema de origen simulado: carga histórica y bandeja (generado, no versionado en Git)."""
    return raiz() / "origen"
