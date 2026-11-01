import copy
import json

import numpy as np
import pandas as pd
import pytest

from inventario import config
from inventario.ingesta import ingestar, registro as registro_ingesta
from inventario.modelos import entrenar
from inventario.origen.generar import generar
from inventario.preparacion import preparar
from inventario.publicacion import pedido, publicar, reproducir
from tests.test_modelos import cfg_rapido

CFG_N = config.cargar("negocio")
Q = config.cargar("modelo")["cuantiles"]
CORTE = "2017-07-17"


def pronostico_fijo(familias=("BEVERAGES", "PRODUCE"), valor=10.0):
    """Pronóstico de 14 días con cuantiles 10, 12, 14, 16, 18 y 20 cada día (p50 = 14)."""
    fechas = pd.date_range("2017-07-18", periods=14)
    filas = [(pd.Timestamp(CORTE), f, h, 1, fam) for h, f in enumerate(fechas, 1) for fam in familias]
    p = pd.DataFrame(filas, columns=["corte", "fecha", "h", "store_nbr", "family"])
    for i, q in enumerate(["p10", "p25", "p50", "p75", "p90", "p95"]):
        p[q] = valor + 2 * i
    return p.assign(modelo="prueba")


def test_pedido_suma_el_cuantil_critico_del_periodo_de_cobertura():
    ped = pedido.calcular(pronostico_fijo(), Q, CFG_N, 14).set_index("family")
    assert ped["entrega"].iloc[0] == pd.Timestamp("2017-07-19")
    assert ped["cobertura_hasta"].iloc[0] == pd.Timestamp("2017-07-25")
    assert ped.loc["BEVERAGES", "demanda_p50"] == pytest.approx(7 * 14)
    # proporción 0.857: entre p75 (16) y p90 (18) -> 16 + 2 * (0.857 - 0.75) / 0.15 = 17.43 por día
    assert ped.loc["BEVERAGES", "cantidad_sugerida"] == np.ceil(round(7 * (16 + 2 * (0.3 / 0.35 - 0.75) / 0.15), 6))
    # perecedero, proporción 0.545: entre p50 (14) y p75 (16)
    assert ped.loc["PRODUCE", "cantidad_sugerida"] == np.ceil(round(7 * (14 + 2 * (0.3 / 0.55 - 0.5) / 0.25), 6))


def test_cambiar_los_costos_cambia_el_pedido_sin_tocar_codigo():
    base = pedido.calcular(pronostico_fijo(), Q, CFG_N, 14).set_index("family")["cantidad_sugerida"]
    caro = copy.deepcopy(CFG_N)
    caro["por_defecto"]["costo_sobrante"] = 0.30          # sobrar cuesta lo mismo que faltar
    otro = pedido.calcular(pronostico_fijo(), Q, caro, 14).set_index("family")["cantidad_sugerida"]
    assert otro["BEVERAGES"] == 7 * 14 and otro["BEVERAGES"] < base["BEVERAGES"]
    assert otro["PRODUCE"] == base["PRODUCE"]


def test_inventario_disponible_y_ceros():
    cfg = copy.deepcopy(CFG_N)
    cfg["pedido"]["inventario_disponible"] = 1000
    ped = pedido.calcular(pronostico_fijo(), Q, cfg, 14)
    assert (ped["cantidad_sugerida"] == 0).all()
    assert not np.signbit(ped["cantidad_sugerida"]).any()           # sin -0.0


def test_cobertura_debe_caber_en_el_horizonte():
    with pytest.raises(ValueError, match="no cabe"):
        pedido.periodo_cobertura(CORTE, CFG_N, horizonte=7)


@pytest.fixture
def operado(tmp_path, monkeypatch, datos, cfg):
    """Origen generado, ingesta hasta el corte, modelo entrenado antes del corte y corte preparado."""
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    ingestar.ejecutar(CORTE)
    entrenar.ejecutar("2017-07-03", cfg_rapido())
    preparar.ejecutar(CORTE)
    return tmp_path


def test_publicacion_con_manifest(operado):
    destino = publicar.carpeta(CORTE)
    publicar.ejecutar(CORTE)
    m = json.loads((destino / "manifest.json").read_text())
    assert m["corte"] == CORTE and m["modelo"]["version"] in {"gbm-2017-07-03", "baseline-2017-07-03"}
    assert m["datos"]["ultima_llegada"] <= CORTE and m["periodo_cobertura"] == ["2017-07-19", "2017-07-25"]
    ped = pd.read_csv(destino / "pedido.csv")
    assert len(ped) == m["filas_pedido"] == 10 and (ped["cantidad_sugerida"] >= 0).all()
    assert len(pd.read_parquet(destino / "pronostico.parquet")) == 10 * 14


def test_una_publicacion_no_se_modifica(operado):
    destino = publicar.carpeta(CORTE)
    publicar.ejecutar(CORTE)
    antes = {p.name: p.read_bytes() for p in destino.iterdir()}
    ingestar.ejecutar("2017-08-31")              # llegan correcciones posteriores
    preparar.ejecutar(CORTE)
    publicar.ejecutar(CORTE)
    assert {p.name: p.read_bytes() for p in destino.iterdir()} == antes


def test_reproduce_aunque_lleguen_correcciones(operado):
    publicar.ejecutar(CORTE)
    ingestar.ejecutar("2017-08-31")
    r = reproducir.ejecutar(CORTE)
    assert r["reproducido"] and r["max_dif_pronostico"] == 0 and r["pedidos_distintos"] == 0


def test_huella_de_datos_depende_solo_de_lo_llegado_al_corte(operado):
    con = registro_ingesta.conectar()
    try:
        antes = registro_ingesta.huella_entradas(con, CORTE)
        ingestar.ejecutar("2017-08-31")
        despues = registro_ingesta.huella_entradas(con, CORTE)
        otro = registro_ingesta.huella_entradas(con, "2017-07-24")
    finally:
        con.close()
    assert antes == despues and otro["hash"] != antes["hash"]


def test_publicar_sin_features_o_sin_modelo_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="features"):
        publicar.ejecutar(CORTE)
