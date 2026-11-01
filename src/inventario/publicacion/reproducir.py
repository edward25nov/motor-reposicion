"""Reproduce un pronóstico publicado y lo compara con lo que se publicó.

Vuelve a calcular las features del corte con los datos tal como se conocían ese día (lectura
as-of del registro de ingesta), aplica la versión de modelo que dice el manifest y compara el
pronóstico y el pedido con los archivos publicados. No escribe nada.

Para reproducir una publicación pasada desde cero: `git checkout <git_commit del manifest>`,
`dvc checkout` y luego este comando (ver README).

Uso:
    PYTHONPATH=src python -m inventario.publicacion.reproducir 2017-07-17
"""

import json
import sys

import numpy as np
import pandas as pd

from inventario import config
from inventario.ingesta import registro as registro_ingesta
from inventario.modelos import registro
from inventario.preparacion.features import Insumos, features_corte
from inventario.preparacion.preparar import datos_al_corte
from inventario.publicacion.publicar import calcular, carpeta

LLAVE_PRON = ["fecha", "store_nbr", "family"]


def ejecutar(corte: str) -> dict:
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    origen = carpeta(corte)
    manifest = json.loads((origen / "manifest.json").read_text(encoding="utf-8"))

    con = registro_ingesta.conectar()
    try:
        entradas = registro_ingesta.huella_entradas(con, corte)
    finally:
        con.close()

    features = features_corte(Insumos.desde(datos_al_corte(corte)), corte, config.cargar("preparacion"))
    version = manifest["modelo"]["version"]
    pron, ped = calcular(features, version, registro.cargar_modelo(version))

    publicado_pron = pd.read_parquet(origen / "pronostico.parquet").sort_values(LLAVE_PRON)
    publicado_ped = pd.read_csv(origen / "pedido.csv").sort_values(["store_nbr", "family"])
    pron = pron.sort_values(LLAVE_PRON)
    ped = ped.sort_values(["store_nbr", "family"])
    cuantiles = [c for c in pron.columns if c.startswith("p") and c[1:].isdigit()]

    resultado = {
        "corte": corte,
        "modelo": version,
        "misma_huella_de_datos": entradas["hash"] == manifest["datos"]["hash"],
        "filas_iguales": len(pron) == len(publicado_pron) and len(ped) == len(publicado_ped),
        "max_dif_pronostico": float(np.abs(pron[cuantiles].to_numpy() - publicado_pron[cuantiles].to_numpy()).max()),
        "pedidos_distintos": int((ped["cantidad_sugerida"].to_numpy() != publicado_ped["cantidad_sugerida"].to_numpy()).sum()),
        "unidades_publicadas": float(publicado_ped["cantidad_sugerida"].sum()),
        "unidades_reproducidas": float(ped["cantidad_sugerida"].sum()),
    }
    resultado["reproducido"] = (resultado["misma_huella_de_datos"] and resultado["filas_iguales"]
                                and resultado["max_dif_pronostico"] < 1e-6 and resultado["pedidos_distintos"] == 0)
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return resultado


if __name__ == "__main__":
    if not ejecutar(sys.argv[1])["reproducido"]:
        sys.exit(1)
