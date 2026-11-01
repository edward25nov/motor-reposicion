import pytest

from inventario import config, operacion
from inventario.ingesta import ingestar
from inventario.modelos import entrenar, registro
from inventario.origen.generar import generar
from inventario.preparacion import preparar
from inventario.publicacion import publicar
from tests.test_modelos import cfg_rapido

CFG_M = config.cargar("modelo")


def version(snapshot, tipo, decision):
    return {"snapshot": snapshot, "tipo": tipo, "decision": decision}


REG = {"vigente": "gbm-2017-07-03", "versiones": {
    "gbm-2017-06-05": version("2017-06-05", "gbm", "promovido"),
    "baseline-2017-06-05": version("2017-06-05", "baseline", "vigente inicial"),
    "gbm-2017-07-03": version("2017-07-03", "gbm", "descartado"),
    "gbm-2017-07-31": version("2017-07-31", "gbm", "promovido"),
}}


@pytest.mark.parametrize("corte, esperado", [
    ("2017-06-04", None),                     # antes de cualquier entrenamiento
    ("2017-06-05", "gbm-2017-06-05"),         # baseline inicial y luego el gbm promovido
    ("2017-07-24", "gbm-2017-06-05"),         # el retador de julio se descartó
    ("2017-07-31", "gbm-2017-07-31"),
])
def test_vigente_al_corte(corte, esperado):
    assert registro.vigente_al(corte, REG) == esperado


@pytest.mark.parametrize("corte, toca", [
    ("2017-06-05", False), ("2017-06-26", False), ("2017-07-03", False),  # ya hay retador del 07-03
    ("2017-07-10", False), ("2017-08-28", True),
])
def test_toca_reentrenar_cada_cuatro_semanas(corte, toca):
    assert operacion.toca_reentrenar(corte, REG, CFG_M) is toca


def test_toca_reentrenar_sin_vigente():
    assert operacion.toca_reentrenar("2017-06-05", {"vigente": None, "versiones": {}}, CFG_M)


def test_un_corte_no_usa_un_modelo_entrenado_despues(tmp_path, monkeypatch, datos, cfg):
    """Aunque se entrene primero con un snapshot posterior, un corte anterior no lo usa."""
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    ingestar.ejecutar("2017-07-31")
    entrenar.ejecutar("2017-07-31", cfg_rapido())
    preparar.ejecutar("2017-07-17")
    with pytest.raises(RuntimeError, match="No hay modelo vigente al 2017-07-17"):
        publicar.ejecutar("2017-07-17")
