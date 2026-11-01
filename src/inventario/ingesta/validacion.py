"""Validación de un archivo de una fuente.

Distingue dos cosas:
- errores: el archivo no puede usarse y va a cuarentena (esquema roto, tipos inválidos,
  negativos, duplicados, fechas que no corresponden).
- advertencias: situaciones esperadas del negocio que no detienen nada (petróleo nulo, tiendas
  que no reportan, tiendas aún no anunciadas, familias nuevas, columnas de más).

No lee ni escribe archivos: recibe un DataFrame y devuelve el resultado.
"""

from dataclasses import dataclass, field

import pandas as pd

# Columnas obligatorias y su tipo. "real?" admite nulos.
ESQUEMAS = {
    "ventas": {"date": "fecha", "store_nbr": "entero", "family": "texto", "sales": "real"},
    "promociones": {"date": "fecha", "store_nbr": "entero", "family": "texto", "onpromotion": "entero"},
    "transacciones": {"date": "fecha", "store_nbr": "entero", "transactions": "entero"},
    "petroleo": {"date": "fecha", "dcoilwtico": "real?"},
    "feriados": {"date": "fecha", "type": "texto", "locale": "texto", "locale_name": "texto",
                 "description": "texto", "transferred": "booleano"},
    "tiendas": {"store_nbr": "entero", "city": "texto", "state": "texto", "type": "texto",
                "cluster": "entero"},
}
LLAVES = {
    "ventas": ["date", "store_nbr", "family"],
    "promociones": ["date", "store_nbr", "family"],
    "transacciones": ["date", "store_nbr"],
    "petroleo": ["date"],
    "feriados": ["date", "locale_name", "description"],
    "tiendas": ["store_nbr"],
}
NO_NEGATIVOS = {"ventas": "sales", "promociones": "onpromotion", "transacciones": "transactions"}
POR_TIENDA = ("ventas", "promociones", "transacciones")
POR_FAMILIA = ("ventas", "promociones")


@dataclass
class Contexto:
    """Lo que se conoce del negocio al momento de validar."""
    tiendas: set[int] = field(default_factory=set)
    familias: set[str] = field(default_factory=set)


@dataclass
class Resultado:
    datos: pd.DataFrame | None
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def valido(self) -> bool:
        return not self.errores


def _convertir(serie: pd.Series, tipo: str) -> pd.Series:
    if tipo == "fecha":
        return pd.to_datetime(serie, format="%Y-%m-%d", errors="coerce")
    if tipo in ("entero", "real", "real?"):
        return pd.to_numeric(serie, errors="coerce")
    if tipo == "booleano":
        return serie.map({True: True, False: False, "True": True, "False": False})
    return serie.astype("string").str.strip()


def _lista(valores, maximo=5) -> str:
    valores = sorted(valores)
    texto = ", ".join(str(v) for v in valores[:maximo])
    return texto + (f" y {len(valores) - maximo} más" if len(valores) > maximo else "")


def validar(fuente: str, clave: str | None, df: pd.DataFrame, contexto: Contexto) -> Resultado:
    """Valida y normaliza un archivo. clave=None omite la verificación de fechas (carga histórica)."""
    esquema = ESQUEMAS[fuente]
    faltan = [c for c in esquema if c not in df.columns]
    if faltan:
        return Resultado(None, [f"faltan columnas: {', '.join(faltan)}"])
    if df.empty:
        return Resultado(None, ["el archivo no tiene filas"])

    r = Resultado(None)
    sobran = [c for c in df.columns if c not in esquema]
    if sobran:
        r.advertencias.append(f"columnas ignoradas: {', '.join(sobran)}")

    datos = pd.DataFrame({c: _convertir(df[c], t) for c, t in esquema.items()})
    for c, t in esquema.items():
        invalidos = datos[c].isna() & df[c].notna()
        if invalidos.any():
            r.errores.append(f"{c}: {int(invalidos.sum())} valores con tipo inválido")
        nulos = df[c].isna()
        if nulos.any() and not t.endswith("?"):
            r.errores.append(f"{c}: {int(nulos.sum())} valores nulos")
        elif nulos.any():
            r.advertencias.append(f"{c}: {int(nulos.sum())} valores nulos")
    if r.errores:
        return r
    for c, t in esquema.items():
        if t == "entero":
            if (datos[c] % 1 != 0).any():
                r.errores.append(f"{c}: valores no enteros")
            else:
                datos[c] = datos[c].astype("int64")
        elif t == "texto":
            datos[c] = datos[c].astype(str)
        elif t == "booleano":
            datos[c] = datos[c].astype(bool)

    if fuente in NO_NEGATIVOS:
        col = NO_NEGATIVOS[fuente]
        negativos = datos[col] < 0
        if negativos.any():
            r.errores.append(f"{col}: {int(negativos.sum())} valores negativos")

    duplicados = datos.duplicated(LLAVES[fuente], keep=False)
    if duplicados.any():
        r.errores.append(f"{int(duplicados.sum())} filas duplicadas por {', '.join(LLAVES[fuente])}")

    if clave is not None and "date" in datos:
        fechas = datos["date"].dt.strftime("%Y-%m" if fuente == "feriados" else "%Y-%m-%d")
        ajenas = fechas != clave
        if ajenas.any():
            r.errores.append(f"{int(ajenas.sum())} filas con fecha distinta a {clave}")

    if fuente in POR_TIENDA and contexto.tiendas:
        # Una tienda que todavía no se anunció es una situación del negocio (abre una tienda y el
        # maestro llega después): sus filas se guardan y la preparación las usa cuando la tienda
        # aparece en el maestro. Descartarlas las perdería para siempre.
        desconocida = ~datos["store_nbr"].isin(contexto.tiendas)
        if desconocida.any():
            r.advertencias.append(f"tiendas aún no anunciadas ({int(desconocida.sum())} filas, se guardan): "
                                  f"{_lista(datos.loc[desconocida, 'store_nbr'].unique())}")
        faltantes = contexto.tiendas - set(datos["store_nbr"])
        if faltantes and fuente != "transacciones":
            r.advertencias.append(f"tiendas sin datos: {_lista(faltantes)}")

    if fuente in POR_FAMILIA and contexto.familias:
        # Una familia nueva se pronostica igual: el modelo la trata como categoría no vista (D28)
        # y recibe los costos por defecto.
        desconocidas = set(datos["family"]) - contexto.familias
        if desconocidas:
            r.advertencias.append(f"familias nuevas: {_lista(desconocidas)}")

    if not r.errores:
        r.datos = datos.reset_index(drop=True)
    return r
