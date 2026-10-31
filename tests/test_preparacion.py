import numpy as np
import pandas as pd
import pytest

from inventario import config
from inventario.ingesta import ingestar
from inventario.origen.generar import generar
from inventario.preparacion import calendario, preparar
from inventario.preparacion.features import Insumos, features_corte
from tests.conftest import kaggle_sintetico

CFG = config.cargar("preparacion")
CORTE = "2017-07-17"


def fuentes(datos):
    """Datos sintéticos de Kaggle con los nombres de las fuentes del producto."""
    tr = datos["train"]
    return {
        "ventas": tr[["date", "store_nbr", "family", "sales"]],
        "promociones": tr[["date", "store_nbr", "family", "onpromotion"]],
        "transacciones": datos["transactions"],
        "petroleo": datos["oil"],
        "feriados": datos["holidays_events"],
        "tiendas": datos["stores"],
    }


def sin_objetivo(tabla):
    return tabla.drop(columns="ventas").reset_index(drop=True)


def test_ninguna_feature_ve_ventas_posteriores_al_corte(datos):
    base = features_corte(Insumos.desde(fuentes(datos)), CORTE, CFG)
    alterado = fuentes(kaggle_sintetico())
    futuro = alterado["ventas"]["date"] >= CORTE          # T - 1 es lo último utilizable
    alterado["ventas"] = alterado["ventas"].assign(
        sales=np.where(futuro, alterado["ventas"]["sales"] * 10 + 7, alterado["ventas"]["sales"]))
    t = alterado["transacciones"]
    alterado["transacciones"] = t.assign(
        transactions=np.where(t["date"] >= "2017-07-15", 1, t["transactions"]))
    pd.testing.assert_frame_equal(sin_objetivo(base),
                                  sin_objetivo(features_corte(Insumos.desde(alterado), CORTE, CFG)))


def test_promociones_solo_dentro_de_la_anticipacion(datos):
    cfg = {**CFG, "corte": {**CFG["corte"], "horizonte_dias": 20}}
    tabla = features_corte(Insumos.desde(fuentes(datos)), "2017-07-03", cfg)
    limite = pd.Timestamp("2017-07-03") + pd.Timedelta(days=16)
    assert tabla.loc[tabla["fecha"] <= limite, "promo"].notna().all()
    assert tabla.loc[tabla["fecha"] > limite, "promo"].isna().all()


def test_estructura_y_medias(datos):
    tabla = features_corte(Insumos.desde(fuentes(datos)), CORTE, CFG)
    assert len(tabla) == 5 * 2 * 14
    assert tabla["h"].tolist()[:1] == [1] and tabla["fecha"].min() == pd.Timestamp("2017-07-18")
    tr = datos["train"]
    serie = tr[(tr["store_nbr"] == 1) & (tr["family"] == "PRODUCE")].set_index("date")["sales"]
    esperado = np.log1p(serie["2017-07-10":"2017-07-16"]).mean()
    fila = tabla[(tabla["store_nbr"] == 1) & (tabla["family"] == "PRODUCE")].iloc[0]
    assert fila["media_7"] == pytest.approx(esperado)
    domingos = np.log1p(serie[serie.index.day_of_week == 6]["2017-06-19":"2017-07-16"]).mean()
    assert tabla.query("store_nbr == 1 and family == 'PRODUCE' and dia_semana == 6")["mismo_dia_4"].iloc[0] \
        == pytest.approx(domingos)


def test_calendario_de_feriados():
    tiendas = pd.DataFrame({"store_nbr": [1, 2], "city": ["Quito", "Guayaquil"],
                            "state": ["Pichincha", "Guayas"]})
    feriados = pd.DataFrame({
        "date": pd.to_datetime(["2017-08-10", "2017-08-11", "2017-07-25", "2017-08-01", "2017-08-12",
                                "2017-08-13"]),
        "type": ["Holiday", "Transfer", "Additional", "Holiday", "Work Day", "Event"],
        "locale": ["National", "National", "Local", "Regional", "National", "National"],
        "locale_name": ["Ecuador", "Ecuador", "Guayaquil", "Pichincha", "Ecuador", "Ecuador"],
        "description": list("abcdef"),
        "transferred": [True, False, False, False, False, False],
    })
    fechas = pd.date_range("2017-07-25", "2017-08-13")
    b = calendario.banderas(feriados, tiendas, fechas).set_index(["store_nbr", "date"])
    assert b.loc[(1, "2017-08-10"), "feriado_nacional"] == 0     # trasladado
    assert b.loc[(2, "2017-08-11"), "feriado_nacional"] == 1     # día del traslado
    assert b.loc[(2, "2017-07-25"), "feriado_local"] == 1        # local de Guayaquil
    assert b.loc[(1, "2017-07-25"), "feriado_local"] == 0
    assert b.loc[(1, "2017-08-01"), "feriado_local"] == 1        # regional de Pichincha
    assert b.loc[(2, "2017-08-12"), "dia_laboral_compensado"] == 1
    assert b.loc[(1, "2017-08-13"), "evento"] == 1


@pytest.fixture
def ingerido(tmp_path, monkeypatch, datos, cfg):
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    ingestar.ejecutar("2017-08-31")
    return tmp_path


def test_preparar_un_corte_es_idempotente(ingerido):
    ruta = preparar.ejecutar(CORTE)
    primero = pd.read_parquet(ruta)
    preparar.ejecutar(CORTE)
    pd.testing.assert_frame_equal(pd.read_parquet(ruta), primero)
    assert primero["ventas"].isna().all()          # en operación el objetivo aún no se conoce
    assert (ingerido / "data" / "procesados" / "calidad" / f"corte={CORTE}.json").is_file()


def test_ventas_muy_atrasadas_detienen_la_preparacion(datos):
    ins = Insumos.desde(fuentes(datos))
    preparar.calidad(ins, "2017-07-17", CFG)                        # al día
    with pytest.raises(preparar.DatosInsuficientes):
        preparar.calidad(ins, "2017-08-10", CFG)                    # última venta: 2017-07-31


def test_entrenamiento_solo_con_objetivos_conocidos(ingerido):
    t = preparar.entrenamiento("2017-07-03", "2017-05-01", "2017-06-26")
    assert t["corte"].dt.day_of_week.eq(0).all()
    assert t["fecha"].max() <= pd.Timestamp("2017-07-02")
    assert t["ventas"].notna().all() and t["family"].dtype == "category"
