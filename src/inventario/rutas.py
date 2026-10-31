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
    """La configuración es parte del código: viene del repositorio, no de MOTOR_RAIZ."""
    return Path(os.environ.get("MOTOR_CONFIGS", _RAIZ_POR_DEFECTO / "configs"))


def kaggle() -> Path:
    """Donde se colocan los CSV originales de Kaggle (versionados con DVC)."""
    return raiz() / "data" / "raw" / "kaggle"


def origen() -> Path:
    """Sistema de origen simulado: carga histórica y bandeja (generado, no versionado en Git).

    En Airflow se monta aparte y en solo lectura; su ruta se indica con MOTOR_ORIGEN.
    """
    return Path(os.environ.get("MOTOR_ORIGEN", raiz() / "origen"))


def ingesta() -> Path:
    """Copia inmutable de lo recibido, datos validados y registro de la ingesta."""
    return raiz() / "data" / "ingesta"


def modelos() -> Path:
    """Modelos entrenados y su registro (versionados con DVC, no con Git)."""
    return raiz() / "models"


def reportes() -> Path:
    """Comparaciones de modelos, seguimiento y otras salidas para revisar."""
    return raiz() / "data" / "reportes"
