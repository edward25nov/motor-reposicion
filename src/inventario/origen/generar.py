"""Construye el sistema de origen simulado a partir de los CSV de Kaggle.

Escribe en origen/:
    historico/<fuente>.csv                         carga histórica inicial
    bandeja/llegada=<AAAA-MM-DD>/<fuente>_<clave>.csv  un archivo por fuente y fecha
    incidentes_simulados.csv                       hoja de respuestas (el flujo no la lee)

La carpeta llegada=... es el día en que el archivo está disponible. Un archivo de la misma
fuente y clave en una llegada posterior es una corrección o un reenvío.

Es idempotente: reconstruye todo en origen.tmp/ y lo reemplaza de una vez.

Uso:
    make origen
"""

import shutil
from pathlib import Path

import pandas as pd

from inventario import config, rutas
from inventario.origen import kaggle
from inventario.origen.entregas import (
    FUENTES, aplicar_incidentes, alterar, programa_base, tablas,
)


def _escribir(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    df.drop(columns="clave").to_csv(ruta, index=False, date_format="%Y-%m-%d")


def generar(datos: dict[str, pd.DataFrame], cfg: dict, destino: Path) -> dict:
    inicio = pd.Timestamp(cfg["inicio_bandeja"])
    contenido = tablas(datos, cfg)
    programa = programa_base(contenido, cfg)
    entregas, registro = aplicar_incidentes(programa, cfg)

    tmp = destino.with_name(destino.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)

    historico = programa[programa["llegada"] < inicio]
    for fuente in FUENTES:
        claves = set(historico.loc[historico["fuente"] == fuente, "clave"])
        df = contenido[fuente]
        _escribir(df[df["clave"].isin(claves)], tmp / "historico" / f"{fuente}.csv")

    # La operación simulada termina con la última entrega de ventas: nada llega después.
    fin = entregas.loc[entregas["fuente"] == "ventas", "llegada"].max()
    bandeja = entregas[entregas["llegada"].between(inicio, fin)]
    por_clave = {
        fuente: dict(tuple(df[df["clave"].isin(set(bandeja.loc[bandeja["fuente"] == fuente, "clave"]))]
                           .groupby("clave")))
        for fuente, df in contenido.items()
    }
    for e in bandeja.itertuples(index=False):
        df = alterar(por_clave[e.fuente][e.clave], e.variante, e.semilla, cfg["incidentes"])
        carpeta = tmp / "bandeja" / f"llegada={e.llegada:%Y-%m-%d}"
        _escribir(df, carpeta / f"{e.fuente}_{e.clave}.csv")

    registro.to_csv(tmp / "incidentes_simulados.csv", index=False, date_format="%Y-%m-%d")

    shutil.rmtree(destino, ignore_errors=True)
    tmp.rename(destino)

    return {
        "inicio_bandeja": cfg["inicio_bandeja"],
        "ultima_llegada": f"{fin:%Y-%m-%d}",
        "archivos_bandeja": len(bandeja),
        "dias_con_llegadas": bandeja["llegada"].nunique(),
        "incidentes": registro["tipo"].value_counts().to_dict(),
    }


def main() -> None:
    resumen = generar(kaggle.leer(rutas.kaggle()), config.cargar("bandeja"), rutas.origen())
    print(f"origen generado en {rutas.origen()}: {resumen}")


if __name__ == "__main__":
    main()
