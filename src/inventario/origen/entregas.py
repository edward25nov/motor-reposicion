"""Programa de entregas del sistema de origen simulado.

Una entrega es un archivo de la bandeja: una fuente, una clave (la fecha de los datos; en
feriados, el mes; en tiendas, el día del anuncio) y la fecha en que llega. Todo se calcula a
partir de los CSV de Kaggle y de configs/bandeja.yaml, de forma determinista: la misma semilla
produce siempre las mismas entregas.
"""

import numpy as np
import pandas as pd

FUENTES = ("ventas", "promociones", "transacciones", "petroleo", "feriados", "tiendas")
COLUMNAS = {
    "ventas": ["date", "store_nbr", "family", "sales"],
    "promociones": ["date", "store_nbr", "family", "onpromotion"],
    "transacciones": ["date", "store_nbr", "transactions"],
    "petroleo": ["date", "dcoilwtico"],
    "feriados": ["date", "type", "locale", "locale_name", "description", "transferred"],
    "tiendas": ["store_nbr", "city", "state", "type", "cluster"],
}
VARIANTES_CORRECCION = ("parcial", "valores")
VARIANTES_INVALIDO = ("negativas", "duplicadas", "esquema")
INCIDENTES = ("correccion", "invalido", "atraso")


def _dias(n: int) -> pd.Timedelta:
    return pd.Timedelta(days=int(n))


def apertura_tiendas(train: pd.DataFrame, tiendas: pd.Series) -> pd.Series:
    """Primera fecha con ventas de cada tienda; si nunca vendió, la primera fecha del histórico."""
    primera_venta = train[train["sales"] > 0].groupby("store_nbr")["date"].min()
    return pd.Series(
        [primera_venta.get(t, train["date"].min()) for t in tiendas], index=tiendas, name="apertura"
    )


def tablas(datos: dict[str, pd.DataFrame], cfg: dict) -> dict[str, pd.DataFrame]:
    """Contenido de cada fuente con la columna `clave` que dice a qué archivo pertenece cada fila."""
    train = datos["train"]
    t = {
        "ventas": train[COLUMNAS["ventas"]].copy(),
        "promociones": train[COLUMNAS["promociones"]].copy(),
        "transacciones": datos["transactions"][COLUMNAS["transacciones"]].copy(),
        "petroleo": datos["oil"][COLUMNAS["petroleo"]].copy(),
        "feriados": datos["holidays_events"][COLUMNAS["feriados"]].copy(),
    }
    for fuente in ("ventas", "promociones", "transacciones", "petroleo"):
        t[fuente]["clave"] = t[fuente]["date"].dt.strftime("%Y-%m-%d")
    t["feriados"]["clave"] = t["feriados"]["date"].dt.strftime("%Y-%m")

    tiendas = datos["stores"][COLUMNAS["tiendas"]].copy()
    apertura = apertura_tiendas(train, tiendas["store_nbr"])
    anuncio = apertura.values - _dias(cfg["fuentes"]["tiendas"]["aviso_dias"])
    tiendas["clave"] = pd.DatetimeIndex(anuncio).strftime("%Y-%m-%d")
    t["tiendas"] = tiendas
    return t


def llegada(fuente: str, clave: pd.Series, cfg: dict) -> pd.Series:
    """Fecha en que llega a la bandeja el archivo normal de cada clave."""
    f = cfg["fuentes"][fuente]
    if fuente == "feriados":
        meses = pd.PeriodIndex(clave, freq="M") - f["meses_anticipacion"]
        return pd.Series(meses.to_timestamp(), index=clave.index)
    fecha = pd.to_datetime(clave)
    if fuente == "promociones":
        return fecha - _dias(f["anticipacion_dias"])
    if fuente == "tiendas":
        return fecha
    return fecha + _dias(f["atraso_dias"])


def programa_base(contenido: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame:
    """Una fila por archivo normal: fuente, clave y llegada, sin incidentes."""
    bloques = []
    for fuente in FUENTES:
        claves = pd.Series(sorted(contenido[fuente]["clave"].unique()), dtype=object)
        bloques.append(pd.DataFrame({
            "fuente": fuente,
            "clave": claves,
            "llegada": llegada(fuente, claves, cfg).values,
        }))
    return pd.concat(bloques, ignore_index=True)


def _sortear(rng: np.random.Generator, fuente: str, cfg_incidentes: dict) -> str | None:
    """Elige a lo sumo un incidente para el archivo. Siempre consume un número aleatorio."""
    u = rng.random()
    acumulado = 0.0
    for tipo in INCIDENTES:
        c = cfg_incidentes.get(tipo)
        if c and fuente in c["fuentes"]:
            acumulado += c["probabilidad"]
            if u < acumulado:
                return tipo
    return None


def aplicar_incidentes(programa: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convierte el programa base en entregas, inyectando incidentes solo en la bandeja.

    Devuelve (entregas, registro). entregas tiene una fila por archivo, con su variante
    ("normal" o la alteración) y la semilla que la reproduce. registro describe cada
    incidente: es la "hoja de respuestas" de la simulación y el flujo nunca la lee.
    """
    inicio = pd.Timestamp(cfg["inicio_bandeja"])
    inc = cfg["incidentes"]
    rng = np.random.default_rng(cfg["semilla"])
    entregas, registro = [], []

    def entrega(f, llegada_, variante="normal", semilla=0):
        entregas.append({"fuente": f.fuente, "clave": f.clave, "llegada": llegada_,
                         "variante": variante, "semilla": semilla})

    for f in programa.sort_values(["llegada", "fuente", "clave"]).itertuples(index=False):
        if f.llegada < inicio:
            entrega(f, f.llegada)
            continue
        tipo = _sortear(rng, f.fuente, inc)
        if tipo is None:
            entrega(f, f.llegada)
            continue
        if tipo == "atraso":
            final = f.llegada + _dias(rng.integers(inc["atraso"]["dias_extra"][0],
                                                   inc["atraso"]["dias_extra"][1] + 1))
            entrega(f, final)
            variante = "normal"
        else:
            c = inc[tipo]
            rango = c["dias_hasta_correccion"] if tipo == "correccion" else c["dias_hasta_reenvio"]
            variantes = VARIANTES_CORRECCION if tipo == "correccion" else VARIANTES_INVALIDO
            variante = str(rng.choice(variantes))
            entrega(f, f.llegada, variante, int(rng.integers(1, 2**31 - 1)))
            final = f.llegada + _dias(rng.integers(rango[0], rango[1] + 1))
            entrega(f, final)
        registro.append({"tipo": tipo, "fuente": f.fuente, "clave": f.clave, "variante": variante,
                         "llegada_esperada": f.llegada, "llegada_version_final": final})

    columnas_registro = ["tipo", "fuente", "clave", "variante", "llegada_esperada",
                         "llegada_version_final"]
    return pd.DataFrame(entregas), pd.DataFrame(registro, columns=columnas_registro)


def alterar(df: pd.DataFrame, variante: str, semilla: int, cfg_incidentes: dict) -> pd.DataFrame:
    """Aplica a un archivo de ventas la alteración de su variante. "normal" lo deja igual."""
    if variante == "normal":
        return df
    rng = np.random.default_rng(semilla)
    df = df.copy()
    if variante == "parcial":
        tiendas = np.sort(df["store_nbr"].unique())
        n = min(cfg_incidentes["correccion"]["tiendas_faltantes"], len(tiendas) - 1)
        return df[~df["store_nbr"].isin(rng.choice(tiendas, size=n, replace=False))]
    if variante == "valores":
        m = rng.random(len(df)) < cfg_incidentes["correccion"]["fraccion_filas"]
        df.loc[m, "sales"] = (df.loc[m, "sales"] * rng.uniform(0, 0.5, m.sum())).round(3)
        return df
    if variante == "negativas":
        m = rng.random(len(df)) < cfg_incidentes["invalido"]["fraccion_filas"]
        m[rng.integers(len(df))] = True
        df.loc[m, "sales"] = -(df.loc[m, "sales"] + 1)
        return df
    if variante == "duplicadas":
        n = max(1, int(len(df) * cfg_incidentes["invalido"]["fraccion_filas"]))
        return pd.concat([df, df.sample(n, random_state=semilla)], ignore_index=True)
    if variante == "esquema":
        return df.rename(columns={"sales": "venta"})
    raise ValueError(f"Variante desconocida: {variante!r}")
