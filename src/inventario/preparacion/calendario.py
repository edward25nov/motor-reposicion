"""Variables de calendario por tienda y fecha a partir de holidays_events (Ecuador).

Reglas de Kaggle:
- Holiday con transferred=True no se celebra ese día; el día libre es el registro Transfer.
- Holiday, Transfer, Additional y Bridge son días libres.
- Work Day es un fin de semana que se trabaja para compensar un puente.
- Event son fechas comerciales o extraordinarias (Día de la Madre, Mundial, terremoto 2016).
- National aplica a todas las tiendas; Regional, a las de esa provincia (state); Local, a las de
  esa ciudad (city).
"""

import pandas as pd

LIBRES = {"Holiday", "Transfer", "Additional", "Bridge"}
COLUMNAS = ["feriado_nacional", "feriado_local", "evento", "dia_laboral_compensado"]


def banderas(feriados: pd.DataFrame, tiendas: pd.DataFrame, fechas: pd.DatetimeIndex) -> pd.DataFrame:
    """Una fila por (store_nbr, date) de `fechas` con las banderas de COLUMNAS (0/1)."""
    base = pd.MultiIndex.from_product([tiendas["store_nbr"], fechas], names=["store_nbr", "date"])
    salida = pd.DataFrame(0, index=base, columns=COLUMNAS)
    f = feriados[feriados["date"].isin(fechas) & ~feriados["transferred"]]
    if f.empty:
        return salida.reset_index()

    lugar = tiendas.set_index("store_nbr")[["city", "state"]]
    for fila in f.itertuples(index=False):
        if fila.locale == "National":
            afectadas = lugar.index
        elif fila.locale == "Regional":
            afectadas = lugar.index[lugar["state"] == fila.locale_name]
        else:
            afectadas = lugar.index[lugar["city"] == fila.locale_name]
        if fila.type in LIBRES:
            columna = "feriado_nacional" if fila.locale == "National" else "feriado_local"
        elif fila.type == "Event":
            columna = "evento"
        elif fila.type == "Work Day":
            columna = "dia_laboral_compensado"
        else:
            continue
        idx = pd.MultiIndex.from_product([afectadas, [fila.date]])
        salida.loc[idx, columna] = 1
    return salida.reset_index()
