"""Tabla de features para un corte: una fila por serie (tienda, familia) y día del horizonte.

Todo lo que se calcula para el corte T respeta la disponibilidad de cada fuente
(configs/preparacion.yaml): ventas hasta T - 1, transacciones hasta T - 3, petróleo hasta T - 1,
promociones hasta T + 16 y feriados publicados. Así la misma función sirve para pronosticar
(con los datos as-of de T) y para armar el entrenamiento con cortes del pasado.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from inventario.preparacion import calendario

LLAVE = ["store_nbr", "family"]


@dataclass
class Insumos:
    """Datos de las fuentes pivotados una sola vez, para calcular muchos cortes rápido."""
    series: pd.DataFrame        # store_nbr, family (una fila por serie, en orden)
    fechas: pd.DatetimeIndex    # columnas de las matrices
    ventas: np.ndarray          # series x fechas, log1p(sales); NaN si no hay dato
    promos: np.ndarray          # series x fechas, onpromotion; NaN si no hay dato
    transacciones: pd.DataFrame  # store_nbr x fechas, log1p(transactions)
    petroleo: pd.Series         # precio por fecha (solo días con dato)
    feriados: pd.DataFrame
    tiendas: pd.DataFrame

    @classmethod
    def desde(cls, datos: dict[str, pd.DataFrame]) -> "Insumos":
        tiendas = datos["tiendas"].sort_values("store_nbr").reset_index(drop=True)
        v = datos["ventas"].merge(datos["promociones"], on=["date", *LLAVE], how="outer")
        inicio = v["date"].min()
        fin = max(v["date"].max(), pd.Timestamp(datos["promociones"]["date"].max()))
        fechas = pd.date_range(inicio, fin)
        series = (pd.DataFrame(sorted(set(zip(v["store_nbr"], v["family"]))), columns=LLAVE)
                  .query("store_nbr in @tiendas.store_nbr").reset_index(drop=True))

        def matriz(col):
            p = v.pivot_table(index=LLAVE, columns="date", values=col, aggfunc="first")
            p = p.reindex(index=pd.MultiIndex.from_frame(series), columns=fechas)
            return p.to_numpy(dtype="float64")

        ventas = matriz("sales")
        t = datos["transacciones"].assign(transactions=lambda d: np.log1p(d["transactions"]))
        trans = (t.pivot_table(index="store_nbr", columns="date", values="transactions")
                 .reindex(index=tiendas["store_nbr"], columns=fechas))
        oil = datos["petroleo"].dropna(subset=["dcoilwtico"]).set_index("date")["dcoilwtico"].sort_index()
        return cls(series, fechas, np.log1p(ventas), matriz("onpromotion"), trans, oil,
                   datos["feriados"], tiendas)


def _hasta(fechas: pd.DatetimeIndex, fecha: pd.Timestamp) -> int:
    """Cantidad de columnas con fecha <= fecha."""
    return int(fechas.searchsorted(fecha, side="right"))


def _media(m: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        conteo = np.sum(~np.isnan(m), axis=1)
        return np.where(conteo > 0, np.nansum(m, axis=1) / np.maximum(conteo, 1), np.nan)


def features_corte(ins: Insumos, corte, cfg: dict) -> pd.DataFrame:
    T = pd.Timestamp(corte)
    disp, feat = cfg["disponibilidad"], cfg["features"]
    H = cfg["corte"]["horizonte_dias"]

    # Historia de ventas utilizable: fechas <= T - atraso.
    fin_v = _hasta(ins.fechas, T - pd.Timedelta(days=disp["ventas_atraso"]))
    hist = ins.ventas[:, :fin_v]
    fechas_hist = ins.fechas[:fin_v]
    serie = ins.series.copy()
    for w in feat["ventanas_dias"]:
        serie[f"media_{w}"] = _media(hist[:, -w:])
    serie["ultimo"] = hist[:, -1] if fin_v else np.nan
    serie["cobertura_7"] = np.sum(~np.isnan(hist[:, -7:]), axis=1) / 7
    serie["ceros_28"] = _media(np.where(np.isnan(hist[:, -28:]), np.nan, hist[:, -28:] == 0))
    serie["dias_historia"] = np.sum(~np.isnan(hist) & (hist > 0), axis=1)
    serie["tendencia_7_28"] = serie["media_7"] - serie["media_28"]
    serie["promo_media_28"] = _media(ins.promos[:, max(fin_v - 28, 0):fin_v])

    # Media del mismo día de la semana: una columna por día (0..6), luego se elige la del día objetivo.
    mismo_dia = {}
    max_semanas = max(feat["semanas_mismo_dia"])
    ventana = hist[:, -7 * max_semanas:]
    dias_ventana = fechas_hist[-7 * max_semanas:].day_of_week
    for k in feat["semanas_mismo_dia"]:
        for d in range(7):
            cols = np.flatnonzero(dias_ventana == d)[-k:]
            mismo_dia[(k, d)] = _media(ventana[:, cols])

    # Transacciones de la tienda (fuente lenta) y petróleo.
    fin_t = _hasta(ins.fechas, T - pd.Timedelta(days=disp["transacciones_atraso"]))
    trans = ins.transacciones.iloc[:, max(fin_t - 28, 0):fin_t].mean(axis=1).rename("transacciones_28")
    serie = serie.merge(trans, left_on="store_nbr", right_index=True, how="left")
    oil = ins.petroleo[ins.petroleo.index <= T - pd.Timedelta(days=disp["petroleo_atraso"])]
    serie["petroleo"] = oil.iloc[-1] if len(oil) else np.nan
    previo = oil[oil.index <= (oil.index[-1] if len(oil) else T) - pd.Timedelta(days=28)]
    serie["petroleo_cambio_28"] = (oil.iloc[-1] / previo.iloc[-1] - 1) if len(previo) else np.nan

    serie = serie.merge(ins.tiendas.rename(columns={"type": "tipo_tienda"}), on="store_nbr", how="left")

    # Feriados publicados al corte.
    publicado = (T.to_period("M") + disp["feriados_meses_anticipacion"]).end_time
    objetivos = pd.date_range(T + pd.Timedelta(days=1), periods=H)
    cal = calendario.banderas(ins.feriados[ins.feriados["date"] <= publicado], ins.tiendas, objetivos)

    promo_hasta = T + pd.Timedelta(days=disp["promociones_anticipacion"])
    bloques = []
    for h, fecha in enumerate(objetivos, start=1):
        b = serie.copy()
        b.insert(0, "corte", T)
        b.insert(1, "fecha", fecha)
        b["h"] = h
        b["dia_semana"] = fecha.day_of_week
        b["dia_mes"] = fecha.day
        b["mes"] = fecha.month
        b["quincena"] = int(fecha.day == 15 or fecha.is_month_end)
        for k in feat["semanas_mismo_dia"]:
            b[f"mismo_dia_{k}"] = mismo_dia[(k, fecha.day_of_week)]
        j = ins.fechas.get_indexer([fecha])[0]
        b["promo"] = ins.promos[:, j] if (j >= 0 and fecha <= promo_hasta) else np.nan
        b["ventas"] = np.expm1(ins.ventas[:, j]) if j >= 0 else np.nan  # objetivo; NaN si no se conoce
        bloques.append(b)
    tabla = pd.concat(bloques, ignore_index=True)
    return tabla.merge(cal, left_on=["store_nbr", "fecha"], right_on=["store_nbr", "date"],
                       how="left").drop(columns="date")
