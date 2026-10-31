import hashlib
import json

import pandas as pd
import pytest

from inventario.ingesta import ingestar, registro, vigente
from inventario.origen.generar import generar


@pytest.fixture
def proyecto(tmp_path, monkeypatch, datos, cfg):
    """Raíz temporal con el origen simulado generado a partir de los datos sintéticos."""
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    return tmp_path


def incidentes(proyecto):
    return pd.read_csv(proyecto / "origen" / "incidentes_simulados.csv")


def archivos(proyecto):
    con = registro.conectar()
    try:
        return registro.tabla(con)
    finally:
        con.close()


def huellas(directorio):
    return {p: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(directorio.rglob("*"))
            if p.is_file()}


def test_es_idempotente(proyecto):
    ingestar.ejecutar("2017-07-15")
    antes = archivos(proyecto)
    reporte = (proyecto / "data" / "ingesta" / "reportes" / "2017-07-15.json").read_text()
    ingestar.ejecutar("2017-07-15")
    pd.testing.assert_frame_equal(archivos(proyecto), antes)
    assert (proyecto / "data" / "ingesta" / "reportes" / "2017-07-15.json").read_text() == reporte


def test_dia_a_dia_da_lo_mismo_que_de_una_vez(proyecto, tmp_path_factory, monkeypatch):
    for dia in pd.date_range("2017-06-01", "2017-07-31").strftime("%Y-%m-%d"):
        ingestar.ejecutar(dia)
    dia_a_dia = archivos(proyecto)

    otra = tmp_path_factory.mktemp("otra")
    monkeypatch.setenv("MOTOR_RAIZ", str(otra))
    monkeypatch.setenv("MOTOR_ORIGEN", str(proyecto / "origen"))
    ingestar.ejecutar("2017-07-31")
    pd.testing.assert_frame_equal(archivos(otra), dia_a_dia)


def test_la_bandeja_no_se_modifica(proyecto):
    antes = huellas(proyecto / "origen")
    ingestar.ejecutar("2017-08-31")
    assert huellas(proyecto / "origen") == antes


def test_invalidos_a_cuarentena_y_reenvio_valido(proyecto):
    ingestar.ejecutar("2017-08-31")
    t = archivos(proyecto)
    for inc in incidentes(proyecto).query("tipo == 'invalido'").itertuples():
        versiones = t[(t["fuente"] == inc.fuente) & (t["clave"] == inc.clave)].set_index("llegada")
        assert versiones.loc[inc.llegada_esperada, "estado"] == "cuarentena"
        assert json.loads(versiones.loc[inc.llegada_esperada, "errores"])
        assert versiones.loc[inc.llegada_version_final, ["estado", "tipo"]].tolist() == ["valido", "reenvio"]


def test_detecta_correcciones(proyecto):
    ingestar.ejecutar("2017-08-31")
    t = archivos(proyecto)
    detectadas = set(t.loc[t["tipo"] == "correccion", ["clave", "llegada"]].itertuples(index=False))
    simuladas = set(incidentes(proyecto).query("tipo == 'correccion'")
                    [["clave", "llegada_version_final"]].itertuples(index=False))
    assert detectadas == simuladas


def test_lectura_as_of_respeta_la_llegada(proyecto, datos):
    ingestar.ejecutar("2017-08-31")
    inc = incidentes(proyecto).query("tipo == 'correccion'").iloc[0]
    train = datos["train"]
    # Antes de su anuncio (2017-06-13) las filas en cero de la tienda 5 se descartan con advertencia.
    anunciada = (train["store_nbr"] != 5) | (train["date"] >= "2017-06-13")
    real = (train.loc[(train["date"] == inc.clave) & anunciada, ["store_nbr", "family", "sales"]]
            .sort_values(["store_nbr", "family"]).reset_index(drop=True))

    def ventas_del_dia(corte):
        v = vigente.leer("ventas", corte)
        return (v.loc[v["date"] == inc.clave, ["store_nbr", "family", "sales"]]
                .sort_values(["store_nbr", "family"]).reset_index(drop=True))

    dia_antes = (pd.Timestamp(inc.llegada_esperada) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    assert ventas_del_dia(dia_antes).empty                              # aún no había llegado
    assert not ventas_del_dia(inc.llegada_esperada).equals(real)       # versión con error
    pd.testing.assert_frame_equal(ventas_del_dia(inc.llegada_version_final), real)  # corregida


def test_un_archivo_en_cuarentena_nunca_se_usa(proyecto):
    ingestar.ejecutar("2017-08-31")
    inc = incidentes(proyecto).query("tipo == 'invalido'").iloc[0]
    v = vigente.leer("ventas", inc.llegada_esperada)
    assert not (v["date"] == inc.clave).any()


def test_carga_historica_invalida_detiene_la_ingesta(proyecto):
    ruta = proyecto / "origen" / "historico" / "ventas.csv"
    df = pd.read_csv(ruta)
    df.loc[0, "sales"] = -5
    df.to_csv(ruta, index=False)
    with pytest.raises(ValueError, match="Carga histórica de ventas inválida"):
        ingestar.ejecutar("2017-06-10")


def test_archivo_ilegible_va_a_cuarentena(proyecto, monkeypatch, tmp_path_factory):
    origen = tmp_path_factory.mktemp("origen_roto")
    import shutil
    shutil.copytree(proyecto / "origen", origen, dirs_exist_ok=True)
    roto = origen / "bandeja" / "llegada=2017-06-05" / "ventas_2017-06-04.csv"
    roto.write_bytes(b"")
    monkeypatch.setenv("MOTOR_ORIGEN", str(origen))
    ingestar.ejecutar("2017-06-05")
    t = archivos(proyecto).set_index(["fuente", "clave", "llegada"])
    fila = t.loc[("ventas", "2017-06-04", "2017-06-05")]
    assert fila["estado"] == "cuarentena" and "no se pudo leer" in fila["errores"]
