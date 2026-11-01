import copy
import json

import numpy as np
import pandas as pd
import pytest

from inventario import config, negocio
from inventario.ingesta import ingestar
from inventario.modelos import backtest, entrenar, metricas, promocion, registro
from inventario.modelos.baseline import Baseline
from inventario.modelos.evaluacion import cortes_evaluables, filas_entrenamiento
from inventario.modelos.gbm import GBMCuantiles
from inventario.origen.generar import generar
from inventario.preparacion.preparar import entrenamiento

CFG_M = config.cargar("modelo")
CFG_P = config.cargar("preparacion")
CFG_N = config.cargar("negocio")
Q = CFG_M["cuantiles"]


def cfg_rapido():
    """Misma configuración con un GBM pequeño, para que las pruebas sean rápidas."""
    cfg = copy.deepcopy(CFG_M)
    cfg["gbm"].update(max_iter=15, max_leaf_nodes=8, min_samples_leaf=5)
    cfg["backtest"]["pliegues"] = 2
    cfg["entrenamiento"]["semanas_evaluacion"] = 2
    return cfg


@pytest.fixture
def proyecto(tmp_path, monkeypatch, datos, cfg):
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    ingestar.ejecutar("2017-08-31")
    return tmp_path


@pytest.fixture
def tabla(proyecto):
    return entrenamiento("2017-07-31", "2017-04-03", "2017-07-10")


# --- negocio y métricas -------------------------------------------------------

def test_costos_por_grupo_y_por_defecto():
    c = negocio.costos(pd.Series(["PRODUCE", "BEVERAGES"]), CFG_N)
    assert c.loc[0, "proporcion_critica"] == pytest.approx(0.30 / 0.55)
    assert c.loc[1, "proporcion_critica"] == pytest.approx(0.30 / 0.35)
    otro = {"por_defecto": {"costo_faltante": 1, "costo_sobrante": 1}}
    assert negocio.costos(pd.Series(["BEVERAGES"]), otro).loc[0, "proporcion_critica"] == 0.5


def test_cantidad_critica_interpola_entre_cuantiles():
    pred = pd.DataFrame([[10, 20, 30, 40, 50, 60]], columns=["p10", "p25", "p50", "p75", "p90", "p95"])
    assert metricas.cantidad_critica(pred, Q, pd.Series([0.5]))[0] == 30
    assert metricas.cantidad_critica(pred, Q, pd.Series([0.6]))[0] == pytest.approx(34)
    assert metricas.cantidad_critica(pred, Q, pd.Series([0.99]))[0] == 60      # se recorta al mayor


def test_costo_de_negocio():
    costos = pd.DataFrame({"costo_faltante": [0.3, 0.3], "costo_sobrante": [0.05, 0.05]})
    costo = metricas.costo_negocio(pd.Series([10.0, 10.0]), np.array([7.0, 14.0]), costos)
    assert costo.tolist() == pytest.approx([0.9, 0.2])


# --- regla de promoción -------------------------------------------------------

def por_corte(costos, cobertura=0.8):
    return pd.DataFrame({"corte": pd.date_range("2017-05-01", periods=len(costos), freq="7D"),
                         "costo_negocio": costos, "cobertura_p10_p90": cobertura, "filas": 100})


REGLA = CFG_M["promocion"]


def test_promueve_si_cumple_las_tres_condiciones():
    ok, motivo = promocion.decidir(por_corte([90, 95, 90, 99]), por_corte([100] * 4), REGLA)
    assert ok and motivo.startswith("se promueve")


@pytest.mark.parametrize("retador, cobertura, falla", [
    ([99, 99, 99, 99.5], 0.8, "mejora de costo"),
    ([60, 101, 101, 101], 0.8, "gana 25%"),
    ([90, 90, 90, 90], 0.6, "cobertura"),
])
def test_descarta_si_falla_una_condicion(retador, cobertura, falla):
    ok, motivo = promocion.decidir(por_corte(retador, cobertura), por_corte([100] * 4), REGLA)
    assert not ok and falla in motivo


def test_no_compara_cortes_distintos():
    otro = por_corte([90] * 4).assign(corte=lambda d: d["corte"] + pd.Timedelta(days=1))
    assert promocion.decidir(otro, por_corte([100] * 4), REGLA) == \
        (False, "los modelos no se evaluaron en los mismos cortes")


# --- esquema temporal ---------------------------------------------------------

def test_cortes_evaluables_tienen_el_horizonte_observado():
    cortes = cortes_evaluables("2017-07-31", 3, CFG_P)
    # Con snapshot 2017-07-31 se conoce hasta el 07-30; el último corte con 14 días observados es el 07-10.
    assert [c.strftime("%Y-%m-%d") for c in cortes] == ["2017-06-26", "2017-07-03", "2017-07-10"]


def test_entrenamiento_no_ve_los_cortes_evaluados(tabla):
    inicio = pd.Timestamp("2017-06-26")
    entreno = filas_entrenamiento(tabla, inicio, CFG_M, CFG_P)
    assert entreno["fecha"].max() <= inicio - pd.Timedelta(days=1)


# --- modelos ------------------------------------------------------------------

@pytest.mark.parametrize("crear", [lambda: Baseline(Q), lambda: GBMCuantiles(Q, cfg_rapido()["gbm"])])
def test_predicciones_validas(tabla, crear):
    entreno, prueba = tabla[tabla["corte"] < "2017-06-26"], tabla[tabla["corte"] >= "2017-06-26"]
    pred = crear().ajustar(entreno).predecir(prueba)
    assert list(pred.columns) == ["p10", "p25", "p50", "p75", "p90", "p95"]
    assert (pred.to_numpy() >= 0).all()
    assert (np.diff(pred.to_numpy(), axis=1) >= 0).all()          # cuantiles sin cruces
    inactiva = prueba.assign(media_56=0.0)
    assert (crear().ajustar(entreno).predecir(inactiva).to_numpy() == 0).all()


# --- procesos completos -------------------------------------------------------

def test_entrenar_registra_vigente_inicial_y_decision(proyecto):
    reg = entrenar.ejecutar("2017-07-31", cfg_rapido())
    assert set(reg["versiones"]) == {"baseline-2017-07-31", "gbm-2017-07-31"}
    assert reg["versiones"]["baseline-2017-07-31"]["decision"] == "vigente inicial"
    gbm = reg["versiones"]["gbm-2017-07-31"]
    assert gbm["decision"] in {"promovido", "descartado"} and gbm["comparado_con"] == "baseline-2017-07-31"
    assert reg["vigente"] == ("gbm-2017-07-31" if gbm["decision"] == "promovido" else "baseline-2017-07-31")
    assert registro.vigente()[0] == reg["vigente"]

    antes = (proyecto / "models" / "registro.json").read_text()
    entrenar.ejecutar("2017-07-31", cfg_rapido())                  # idempotente
    assert (proyecto / "models" / "registro.json").read_text() == antes


def test_backtest_compara_en_los_mismos_cortes(proyecto):
    resumen = backtest.ejecutar("2017-07-31", cfg_rapido())
    assert len(resumen["cortes_evaluados"]) == 4 and len(resumen["pliegues"]) == 2
    assert set(resumen["modelos"]) == {"baseline", "gbm"}
    pc = pd.read_csv(proyecto / "data" / "reportes" / "backtest" / "snapshot=2017-07-31" / "por_corte.csv")
    cortes = pc.groupby("modelo")["corte"].apply(tuple)
    assert cortes["baseline"] == cortes["gbm"]                      # mismos cortes para ambos
    assert json.loads((proyecto / "data" / "reportes" / "backtest" / "snapshot=2017-07-31" /
                       "resumen.json").read_text())["decision_gbm_vs_baseline"]["motivo"]


def test_gbm_pronostica_una_tienda_que_no_vio_al_entrenar(tabla):
    entreno = tabla[(tabla["corte"] < "2017-06-26") & (tabla["store_nbr"] != 3)]
    prueba = tabla[tabla["corte"] >= "2017-06-26"]
    pred = GBMCuantiles(Q, cfg_rapido()["gbm"]).ajustar(entreno).predecir(prueba)
    assert pred.loc[prueba["store_nbr"] == 3].notna().all().all()
