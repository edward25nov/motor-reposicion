import numpy as np
import pandas as pd
import pytest

FAMILIAS = ["BEVERAGES", "PRODUCE"]


def kaggle_sintetico(inicio="2017-03-01", fin="2017-07-31", tiendas=(1, 2, 3, 4, 5), semilla=0):
    """Datos con la forma de los CSV de Kaggle. La tienda 5 abre el 2017-06-20."""
    rng = np.random.default_rng(semilla)
    fechas = pd.date_range(inicio, fin)
    fechas = fechas[~((fechas.month == 12) & (fechas.day == 25))]
    train = pd.DataFrame(
        [(f, t, fam) for f in fechas for t in tiendas for fam in FAMILIAS],
        columns=["date", "store_nbr", "family"],
    )
    train["sales"] = rng.integers(0, 500, len(train)).astype(float)
    train.loc[(train["store_nbr"] == 5) & (train["date"] < "2017-06-20"), "sales"] = 0.0
    train["onpromotion"] = rng.integers(0, 3, len(train))
    habiles = fechas[fechas.day_of_week < 5]
    return {
        "train": train,
        "stores": pd.DataFrame({"store_nbr": list(tiendas), "city": "Quito", "state": "Pichincha",
                                "type": "D", "cluster": 13}),
        "holidays_events": pd.DataFrame({
            "date": pd.to_datetime(["2017-04-14", "2017-05-01", "2017-05-24", "2017-08-10"]),
            "type": "Holiday", "locale": "National", "locale_name": "Ecuador",
            "description": ["Viernes Santo", "Dia del Trabajo", "Batalla de Pichincha",
                            "Primer Grito de Independencia"],
            "transferred": False,
        }),
        "oil": pd.DataFrame({"date": habiles, "dcoilwtico": rng.uniform(40, 55, len(habiles))}),
        "transactions": pd.DataFrame(
            [(f, t, int(rng.integers(500, 3000))) for f in fechas for t in tiendas],
            columns=["date", "store_nbr", "transactions"],
        ),
    }


@pytest.fixture
def datos():
    return kaggle_sintetico()


@pytest.fixture
def cfg():
    return {
        "semilla": 7,
        "inicio_bandeja": "2017-06-01",
        "fuentes": {
            "ventas": {"atraso_dias": 1},
            "promociones": {"anticipacion_dias": 16},
            "transacciones": {"atraso_dias": 3},
            "petroleo": {"atraso_dias": 1},
            "feriados": {"meses_anticipacion": 1},
            "tiendas": {"aviso_dias": 7},
        },
        "incidentes": {
            "correccion": {"fuentes": ["ventas"], "probabilidad": 0.3,
                           "dias_hasta_correccion": [3, 7], "fraccion_filas": 0.2,
                           "tiendas_faltantes": 2},
            "invalido": {"fuentes": ["ventas"], "probabilidad": 0.2,
                         "dias_hasta_reenvio": [1, 2], "fraccion_filas": 0.1},
            "atraso": {"fuentes": ["ventas", "transacciones"], "probabilidad": 0.1,
                       "dias_extra": [1, 3]},
        },
    }
