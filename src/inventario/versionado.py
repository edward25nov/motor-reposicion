"""Versiona con DVC lo que produce el flujo: ingesta, procesados, modelos, publicaciones y reportes.

`dvc add` registra el contenido actual en el caché de DVC y actualiza el puntero .dvc de cada
directorio. Si el remoto tiene credenciales configuradas (.dvc/config.local), además hace
`dvc push`; si no las tiene (por ejemplo, en el equipo de quien evalúa), lo informa y sigue: no
tener acceso al remoto no es un error del flujo. Los punteros .dvc se agregan a Git a mano, con un
commit, cuando se quiere fijar una versión.
"""

import subprocess

from inventario import rutas

DIRECTORIOS = ("data/ingesta", "data/procesados", "models", "data/publicado", "data/reportes")


def _dvc(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["dvc", *args], cwd=rutas.raiz(), capture_output=True, text=True, timeout=timeout)


def ejecutar() -> dict:
    existentes = [d for d in DIRECTORIOS if (rutas.raiz() / d).is_dir()]
    if not existentes:
        return {"versionados": [], "push": False, "motivo": "no hay nada que versionar"}
    agregado = _dvc("add", *existentes)
    if agregado.returncode != 0:
        raise RuntimeError(f"dvc add falló:\n{agregado.stderr}")
    resultado = {"versionados": existentes, "push": False}
    if not (rutas.raiz() / ".dvc" / "config.local").is_file():
        resultado["motivo"] = "sin credenciales del remoto (.dvc/config.local): solo caché local"
    else:
        try:
            enviado = _dvc("push", *[f"{d}.dvc" for d in existentes])
            resultado["push"] = enviado.returncode == 0
            if not resultado["push"]:
                resultado["motivo"] = f"dvc push falló: {enviado.stderr.strip()[-300:]}"
        except subprocess.TimeoutExpired:
            resultado["motivo"] = "dvc push excedió el tiempo límite"
    print(f"versionado: {resultado}")
    return resultado
