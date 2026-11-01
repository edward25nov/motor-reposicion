"""Publica el pronóstico y el pedido sugerido de un corte.

Lee las features del corte (make preparar), aplica el modelo vigente y escribe en
data/publicado/corte=<AAAA-MM-DD>/:
    pronostico.parquet   una fila por tienda, familia y día del horizonte, con sus cuantiles
    pedido.csv           cantidad sugerida por tienda y familia para el periodo de cobertura
    manifest.json        qué código, configuración, modelo y datos produjeron la publicación

Una publicación es inmutable: si el corte ya está publicado, no se vuelve a escribir (así un
reintento o un backfill no la cambian, aunque hayan llegado correcciones después).

Uso:
    PYTHONPATH=src python -m inventario.publicacion.publicar 2017-07-17
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

from inventario import config, rutas
from inventario.ingesta import registro as registro_ingesta
from inventario.modelos import registro
from inventario.publicacion import pedido

CONFIGS = ("preparacion", "modelo", "negocio")


def carpeta(corte: str) -> Path:
    return rutas.raiz() / "data" / "publicado" / f"corte={corte}"


def ruta_features(corte: str) -> Path:
    return rutas.raiz() / "data" / "procesados" / "features" / f"corte={corte}.parquet"


def md5(ruta: Path) -> str:
    return hashlib.md5(ruta.read_bytes()).hexdigest()


def calcular(features: pd.DataFrame, version: str, modelo) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg_m, cfg_n, cfg_p = config.cargar("modelo"), config.cargar("negocio"), config.cargar("preparacion")
    pron = pedido.pronostico(features, modelo, version, cfg_m["cuantiles"])
    ped = pedido.calcular(pron, cfg_m["cuantiles"], cfg_n, cfg_p["corte"]["horizonte_dias"])
    return pron, ped


def ejecutar(corte: str) -> str:
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    destino = carpeta(corte)
    if (destino / "manifest.json").is_file():
        print(f"publicar {corte}: ya estaba publicado; las publicaciones no se modifican")
        return str(destino)

    features_path = ruta_features(corte)
    if not features_path.is_file():
        raise FileNotFoundError(f"No hay features para {corte}: ejecuta antes la preparación del corte")
    vigente = registro.vigente()
    if vigente is None:
        raise RuntimeError("No hay modelo vigente: ejecuta antes el entrenamiento (make entrenar)")
    version, modelo = vigente

    pron, ped = calcular(pd.read_parquet(features_path), version, modelo)

    con = registro_ingesta.conectar()
    try:
        entradas = registro_ingesta.huella_entradas(con, corte)
    finally:
        con.close()
    manifest = {
        "corte": corte,
        "git_commit": registro.commit_git(),
        "modelo": {"version": version, "md5": md5(rutas.modelos() / version / "modelo.joblib")},
        "datos": entradas,
        "features_md5": md5(features_path),
        "configs_md5": {c: md5(rutas.configs() / f"{c}.yaml") for c in CONFIGS},
        "periodo_cobertura": [ped["entrega"].iloc[0].strftime("%Y-%m-%d"),
                              ped["cobertura_hasta"].iloc[0].strftime("%Y-%m-%d")],
        "filas_pronostico": len(pron),
        "filas_pedido": len(ped),
        "unidades_sugeridas": float(ped["cantidad_sugerida"].sum()),
    }

    tmp = destino.with_name(destino.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    pron.to_parquet(tmp / "pronostico.parquet", index=False)
    ped.to_csv(tmp / "pedido.csv", index=False, date_format="%Y-%m-%d")
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                       encoding="utf-8")
    tmp.rename(destino)
    print(f"publicar {corte}: modelo {version}; {len(ped)} pedidos, "
          f"{manifest['unidades_sugeridas']:,.0f} unidades para {manifest['periodo_cobertura']}")
    return str(destino)


if __name__ == "__main__":
    ejecutar(sys.argv[1])
