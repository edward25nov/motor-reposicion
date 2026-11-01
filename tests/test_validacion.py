import pandas as pd
import pytest

from inventario.ingesta.validacion import Contexto, validar

CONTEXTO = Contexto(tiendas={1, 2}, familias={"BEVERAGES", "PRODUCE"})


def ventas(**cambios):
    df = pd.DataFrame({
        "date": ["2017-07-03"] * 4,
        "store_nbr": [1, 1, 2, 2],
        "family": ["BEVERAGES", "PRODUCE"] * 2,
        "sales": [10.0, 0.0, 5.5, 3.0],
    })
    for col, valores in cambios.items():
        df[col] = valores
    return df


def test_archivo_correcto():
    r = validar("ventas", "2017-07-03", ventas(), CONTEXTO)
    assert r.valido and not r.advertencias
    assert r.datos["date"].dtype.kind == "M" and r.datos["store_nbr"].dtype == "int64"


@pytest.mark.parametrize("df, mensaje", [
    (ventas().rename(columns={"sales": "venta"}), "faltan columnas: sales"),
    (ventas().iloc[0:0], "no tiene filas"),
    (ventas(sales=[10.0, -1.0, 5.5, 3.0]), "negativos"),
    (pd.concat([ventas(), ventas().iloc[[0]]]), "duplicadas"),
    (ventas(date=["2017-07-03", "2017-07-04", "2017-07-03", "2017-07-03"]), "fecha distinta"),
    (ventas(sales=["10", "abc", "1", "2"]), "tipo inválido"),
    (ventas(sales=[10.0, None, 5.5, 3.0]), "valores nulos"),
])
def test_errores_van_a_cuarentena(df, mensaje):
    r = validar("ventas", "2017-07-03", df, CONTEXTO)
    assert not r.valido and r.datos is None
    assert any(mensaje in e for e in r.errores), r.errores


def test_tienda_no_anunciada_se_guarda_con_advertencia():
    """Una tienda nueva con ventas no invalida el día: sus filas se guardan para usarlas al anunciarse."""
    df = pd.concat([ventas(), ventas(store_nbr=[9, 9, 10, 10], sales=[5.0, 1.0, 0.0, 2.0])])
    r = validar("ventas", "2017-07-03", df, CONTEXTO)
    assert r.valido and set(r.datos["store_nbr"]) == {1, 2, 9, 10}
    assert any("tiendas aún no anunciadas (4 filas, se guardan): 9, 10" in a for a in r.advertencias)


def test_promocion_de_tienda_no_anunciada_se_guarda():
    df = ventas(store_nbr=[1, 1, 3, 3]).rename(columns={"sales": "onpromotion"})
    df["onpromotion"] = [0, 2, 1, 0]
    r = validar("promociones", "2017-07-03", df, CONTEXTO)
    assert r.valido and set(r.datos["store_nbr"]) == {1, 3}


def test_familia_nueva_es_advertencia():
    r = validar("ventas", "2017-07-03", ventas(family=["BEVERAGES", "LIQUOR", "BEVERAGES", "PRODUCE"]), CONTEXTO)
    assert r.valido and r.advertencias == ["familias nuevas: LIQUOR"]


def test_tienda_que_no_reporta_es_advertencia():
    r = validar("ventas", "2017-07-03", ventas().iloc[:2], CONTEXTO)
    assert r.valido and r.advertencias == ["tiendas sin datos: 2"]


def test_petroleo_nulo_es_situacion_esperada():
    r = validar("petroleo", "2017-07-03", pd.DataFrame({"date": ["2017-07-03"], "dcoilwtico": [None]}),
                CONTEXTO)
    assert r.valido and r.advertencias == ["dcoilwtico: 1 valores nulos"]


def test_feriados_se_validan_por_mes():
    df = pd.DataFrame({"date": ["2017-08-10", "2017-08-11"], "type": "Holiday", "locale": "National",
                       "locale_name": "Ecuador", "description": ["A", "B"], "transferred": [True, False]})
    assert validar("feriados", "2017-08", df, CONTEXTO).valido
    assert not validar("feriados", "2017-09", df, CONTEXTO).valido


def test_columnas_de_mas_son_advertencia():
    r = validar("ventas", "2017-07-03", ventas(id=[1, 2, 3, 4]), CONTEXTO)
    assert r.valido and r.advertencias == ["columnas ignoradas: id"]
    assert "id" not in r.datos.columns
