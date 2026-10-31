"""Lectura "as-of": los datos de una fuente tal como se conocían en una fecha de corte.

Combina la carga histórica con la versión válida más reciente de cada archivo de la bandeja que
llegó hasta el corte (llegada ≤ corte). Un archivo en cuarentena nunca se usa; una corrección
reemplaza a la versión anterior solo desde el día en que llegó.
"""

import pandas as pd

from inventario.ingesta import registro
from inventario.ingesta.ingestar import HISTORICO, ruta_valido


def _clave(fuente: str, df: pd.DataFrame) -> pd.Series:
    return df["date"].dt.strftime("%Y-%m" if fuente == "feriados" else "%Y-%m-%d")


def leer(fuente: str, corte: str) -> pd.DataFrame:
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    con = registro.conectar()
    try:
        vigentes = registro.vigentes(con, fuente, corte)
    finally:
        con.close()
    historico = pd.read_parquet(ruta_valido(fuente, HISTORICO, HISTORICO))
    partes = [pd.read_parquet(ruta_valido(fuente, v.clave, v.llegada)) for v in vigentes.itertuples()]
    if fuente == "tiendas":
        return (pd.concat([historico, *partes], ignore_index=True)
                .drop_duplicates("store_nbr", keep="last").reset_index(drop=True))
    historico = historico[~_clave(fuente, historico).isin(set(vigentes["clave"]))]
    return pd.concat([historico, *partes], ignore_index=True)
