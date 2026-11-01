"""Ingesta de la bandeja hasta una fecha de corte.

Para el corte T procesa, en orden de llegada, todos los archivos de la bandeja con
llegada ≤ T que todavía no estén registrados. Por cada archivo:
1. guarda una copia inmutable en data/ingesta/recibidos/;
2. lo valida (inventario.ingesta.validacion);
3. si es válido, guarda los datos normalizados en data/ingesta/validos/; si no, queda en cuarentena;
4. lo registra con su tipo: nuevo, correccion, reenvio o repetido.

La primera vez también valida y carga la carga histórica; si es inválida, falla: sin ella no se
puede operar. Un archivo inválido de la bandeja no hace fallar la ingesta: queda en cuarentena y
no contamina nada.

Es idempotente: un archivo ya registrado no se vuelve a procesar. Una llegada ya procesada es
inmutable por contrato: si el archivo cambia después de recibido, se conserva la versión original
y se reporta como "modificado" (así no cambia la huella de lo ya publicado). Los archivos cuyo
nombre no sigue el contrato (<fuente>_<clave>.csv dentro de llegada=AAAA-MM-DD/) se reportan como
"no reconocidos". La bandeja solo se lee.

Uso:
    PYTHONPATH=src python -m inventario.ingesta.ingestar 2017-06-15
"""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd

from inventario import rutas
from inventario.ingesta import registro
from inventario.ingesta.validacion import Contexto, validar

# tiendas primero: una tienda anunciada el mismo día ya cuenta para validar sus ventas.
ORDEN_FUENTES = ("tiendas", "feriados", "petroleo", "promociones", "transacciones", "ventas")
HISTORICO = registro.HISTORICO


def ruta_valido(fuente: str, clave: str, llegada: str) -> Path:
    nombre = "historico.parquet" if clave == HISTORICO else f"{clave}__llegada={llegada}.parquet"
    return rutas.ingesta() / "validos" / fuente / nombre


def _md5(ruta: Path) -> str:
    return hashlib.md5(ruta.read_bytes()).hexdigest()


def _escribir_parquet(df: pd.DataFrame, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(ruta)


def _leer_csv(ruta: Path) -> tuple[pd.DataFrame | None, str | None]:
    try:
        return pd.read_csv(ruta), None
    except Exception as e:  # archivo vacío, mal formado, codificación rota...
        return None, f"no se pudo leer el archivo: {type(e).__name__}: {e}"


def _procesar(con, fuente: str, clave: str, llegada: str, ruta: Path, hash_: str,
              contexto: Contexto) -> dict:
    df, error = _leer_csv(ruta)
    if error:
        errores, advertencias, datos = [error], [], None
    else:
        r = validar(fuente, None if clave == HISTORICO else clave, df, contexto)
        errores, advertencias, datos = r.errores, r.advertencias, r.datos
    if datos is not None:
        _escribir_parquet(datos, ruta_valido(fuente, clave, llegada))
    fila = {
        "fuente": fuente, "clave": clave, "llegada": llegada, "hash": hash_,
        "filas": None if df is None else len(df),
        "estado": "valido" if datos is not None else "cuarentena",
        "tipo": HISTORICO if clave == HISTORICO else registro.clasificar(con, fuente, clave, llegada, hash_),
        "errores": json.dumps(errores, ensure_ascii=False),
        "advertencias": json.dumps(advertencias, ensure_ascii=False),
    }
    registro.guardar(con, fila)
    return fila


def cargar_historico(con) -> None:
    """Valida y carga la carga histórica (solo si cambió). Falla si algún archivo es inválido."""
    contexto = Contexto()
    for fuente in ORDEN_FUENTES:
        ruta = rutas.origen() / "historico" / f"{fuente}.csv"
        if not ruta.is_file():
            raise FileNotFoundError(f"No existe la carga histórica {ruta}. Ejecuta `make origen`.")
        hash_ = _md5(ruta)
        if registro.hash_registrado(con, fuente, HISTORICO, HISTORICO) != hash_:
            fila = _procesar(con, fuente, HISTORICO, HISTORICO, ruta, hash_, contexto)
            if fila["estado"] != "valido":
                raise ValueError(f"Carga histórica de {fuente} inválida: {fila['errores']}")
        if fuente == "tiendas":
            contexto.tiendas = set(pd.read_parquet(ruta_valido("tiendas", HISTORICO, HISTORICO))["store_nbr"])


def contexto_inicial() -> Contexto:
    """Tiendas y familias conocidas según la carga histórica."""
    return Contexto(
        tiendas=set(pd.read_parquet(ruta_valido("tiendas", HISTORICO, HISTORICO))["store_nbr"]),
        familias=set(pd.read_parquet(ruta_valido("ventas", HISTORICO, HISTORICO), columns=["family"])["family"]),
    )


CARPETA = re.compile(r"llegada=(\d{4}-\d{2}-\d{2})")


def escanear_bandeja(corte: str) -> tuple[list[tuple[str, str, str, Path]], list[str]]:
    """Archivos de la bandeja con llegada ≤ corte.

    Devuelve (reconocidos, no_reconocidos): reconocidos son (llegada, fuente, clave, ruta) en orden
    de proceso; no_reconocidos, las rutas relativas de lo que no sigue el contrato de nombres.
    """
    bandeja = rutas.origen() / "bandeja"
    reconocidos, no_reconocidos = [], []
    for entrada in sorted(bandeja.iterdir()) if bandeja.is_dir() else []:
        m = CARPETA.fullmatch(entrada.name)
        if not (entrada.is_dir() and m):
            no_reconocidos.append(entrada.name)
            continue
        llegada = m.group(1)
        if llegada > corte:
            continue
        for ruta in sorted(entrada.iterdir()):
            fuente, _, clave = ruta.stem.partition("_")
            if ruta.suffix == ".csv" and fuente in ORDEN_FUENTES and clave:
                reconocidos.append((llegada, fuente, clave, ruta))
            else:
                no_reconocidos.append(f"{entrada.name}/{ruta.name}")
    reconocidos.sort(key=lambda a: (a[0], ORDEN_FUENTES.index(a[1]), a[2]))
    return reconocidos, no_reconocidos


def archivos_bandeja(corte: str) -> list[tuple[str, str, str, Path]]:
    """(llegada, fuente, clave, ruta) de la bandeja con llegada ≤ corte, en orden de proceso."""
    return escanear_bandeja(corte)[0]


def reporte(con, corte: str, no_reconocidos: list[str], modificados: list[dict]) -> dict:
    """Lo que llegó el día del corte y cómo quedó, más las anomalías de la bandeja hasta el corte.

    Depende solo del registro y del contenido de la bandeja: es idempotente.
    """
    del_dia = registro.tabla(con, "llegada=?", (corte,))
    return {
        "corte": corte,
        "archivos": len(del_dia),
        "por_tipo": del_dia["tipo"].value_counts().sort_index().to_dict(),
        "cuarentena": del_dia.loc[del_dia["estado"] == "cuarentena",
                                  ["fuente", "clave", "errores"]].to_dict("records"),
        "correcciones": del_dia.loc[(del_dia["tipo"] == "correccion") & (del_dia["estado"] == "valido"),
                                    ["fuente", "clave"]].to_dict("records"),
        "advertencias": del_dia.loc[del_dia["advertencias"] != "[]",
                                    ["fuente", "clave", "advertencias"]].to_dict("records"),
        "no_reconocidos": no_reconocidos,
        "modificados_despues_de_recibidos": modificados,
    }


def ejecutar(corte: str) -> dict:
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    con = registro.conectar()
    try:
        cargar_historico(con)
        contexto = contexto_inicial()
        procesados, modificados = 0, []
        reconocidos, no_reconocidos = escanear_bandeja(corte)
        for llegada, fuente, clave, ruta in reconocidos:
            hash_ = _md5(ruta)
            registrado = registro.hash_registrado(con, fuente, clave, llegada)
            if registrado is not None:
                if registrado != hash_:
                    modificados.append({"fuente": fuente, "clave": clave, "llegada": llegada})
                if fuente == "tiendas":
                    contexto.tiendas |= _tiendas_validas(con, clave, llegada)
                continue
            copia = rutas.ingesta() / "recibidos" / fuente / clave / f"llegada={llegada}.csv"
            copia.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ruta, copia)
            fila = _procesar(con, fuente, clave, llegada, copia, hash_, contexto)
            if fuente == "tiendas" and fila["estado"] == "valido":
                contexto.tiendas |= _tiendas_validas(con, clave, llegada)
            procesados += 1
        resumen = reporte(con, corte, no_reconocidos, modificados)
    finally:
        con.close()
    destino = rutas.ingesta() / "reportes" / f"{corte}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(resumen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"ingesta {corte}: {procesados} archivos procesados; {resumen['por_tipo']}; "
          f"{len(resumen['cuarentena'])} en cuarentena")
    if no_reconocidos:
        print(f"ingesta {corte}: ADVERTENCIA, archivos con nombre no reconocido (se ignoran): {no_reconocidos}")
    if modificados:
        print(f"ingesta {corte}: ADVERTENCIA, archivos modificados después de recibidos "
              f"(se conserva la versión original): {modificados}")
    return resumen


def _tiendas_validas(con, clave: str, llegada: str) -> set[int]:
    ruta = ruta_valido("tiendas", clave, llegada)
    return set(pd.read_parquet(ruta)["store_nbr"]) if ruta.is_file() else set()


if __name__ == "__main__":
    ejecutar(sys.argv[1])
