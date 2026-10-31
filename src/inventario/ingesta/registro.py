"""Registro de la ingesta: qué archivo llegó, cuándo, con qué contenido y en qué estado quedó.

Una fila por archivo recibido (fuente, clave, llegada). La carga histórica usa
clave = llegada = "historico". Se guarda en data/ingesta/registro.db (SQLite).
"""

import sqlite3
from pathlib import Path

import pandas as pd

from inventario import rutas

HISTORICO = "historico"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS archivos (
    fuente       TEXT NOT NULL,
    clave        TEXT NOT NULL,
    llegada      TEXT NOT NULL,
    hash         TEXT NOT NULL,
    filas        INTEGER,
    estado       TEXT NOT NULL,   -- valido | cuarentena
    tipo         TEXT NOT NULL,   -- historico | nuevo | correccion | reenvio | repetido
    errores      TEXT NOT NULL,
    advertencias TEXT NOT NULL,
    PRIMARY KEY (fuente, clave, llegada)
)
"""
COLUMNAS = ["fuente", "clave", "llegada", "hash", "filas", "estado", "tipo", "errores", "advertencias"]


def ruta_db() -> Path:
    return rutas.ingesta() / "registro.db"


def conectar() -> sqlite3.Connection:
    ruta_db().parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta_db())
    con.execute(ESQUEMA)
    return con


def hash_registrado(con, fuente: str, clave: str, llegada: str) -> str | None:
    fila = con.execute("SELECT hash FROM archivos WHERE fuente=? AND clave=? AND llegada=?",
                       (fuente, clave, llegada)).fetchone()
    return fila[0] if fila else None


def clasificar(con, fuente: str, clave: str, llegada: str, hash_: str) -> str:
    """Tipo de llegada según las versiones anteriores del mismo archivo."""
    ultima_valida = con.execute(
        "SELECT hash FROM archivos WHERE fuente=? AND clave=? AND llegada<? AND estado='valido' "
        "ORDER BY llegada DESC LIMIT 1", (fuente, clave, llegada)).fetchone()
    if ultima_valida:
        return "repetido" if ultima_valida[0] == hash_ else "correccion"
    anterior = con.execute("SELECT 1 FROM archivos WHERE fuente=? AND clave=? AND llegada<?",
                           (fuente, clave, llegada)).fetchone()
    return "reenvio" if anterior else "nuevo"


def guardar(con, fila: dict) -> None:
    """Inserta o reemplaza la fila del archivo (idempotente)."""
    with con:
        con.execute(f"INSERT OR REPLACE INTO archivos ({', '.join(COLUMNAS)}) "
                    f"VALUES ({', '.join('?' * len(COLUMNAS))})", [fila[c] for c in COLUMNAS])


def tabla(con, where: str = "1=1", params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(f"SELECT * FROM archivos WHERE {where} ORDER BY llegada, fuente, clave",
                             con, params=params)


def vigentes(con, fuente: str, corte: str) -> pd.DataFrame:
    """Versión válida más reciente de cada clave de la bandeja disponible al corte (llegada ≤ corte)."""
    return pd.read_sql_query(
        "SELECT clave, MAX(llegada) AS llegada FROM archivos "
        "WHERE fuente=? AND estado='valido' AND llegada<>? AND llegada<=? GROUP BY clave ORDER BY clave",
        con, params=(fuente, HISTORICO, corte))


def correcciones(con, desde: str, hasta: str) -> pd.DataFrame:
    """Correcciones que llegaron en el rango [desde, hasta]: datos ya usados que cambiaron."""
    return tabla(con, "tipo='correccion' AND estado='valido' AND llegada BETWEEN ? AND ?", (desde, hasta))
