"""Lectura de los archivos de configuración versionados en configs/."""

import yaml

from inventario import rutas


def cargar(nombre: str) -> dict:
    """Lee configs/<nombre>.yaml."""
    return yaml.safe_load((rutas.configs() / f"{nombre}.yaml").read_text(encoding="utf-8"))
