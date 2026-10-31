import hashlib

import pandas as pd
import pytest

from inventario.origen import kaggle
from inventario.origen.entregas import alterar, programa_base, tablas
from inventario.origen.generar import generar


def leer_bandeja(origen):
    """Todas las entregas escritas: fuente, clave, llegada y contenido."""
    filas = []
    for archivo in sorted((origen / "bandeja").glob("llegada=*/*.csv")):
        fuente, clave = archivo.stem.split("_", 1)
        filas.append({"fuente": fuente, "clave": clave,
                      "llegada": archivo.parent.name.removeprefix("llegada="), "ruta": archivo})
    return pd.DataFrame(filas)


def huellas(directorio):
    return {p.relative_to(directorio): hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(directorio.rglob("*.csv"))}


def test_llegada_de_cada_fuente(datos, cfg):
    programa = programa_base(tablas(datos, cfg), cfg).set_index(["fuente", "clave"])["llegada"]
    assert programa[("ventas", "2017-06-10")] == pd.Timestamp("2017-06-11")
    assert programa[("promociones", "2017-06-30")] == pd.Timestamp("2017-06-14")
    assert programa[("transacciones", "2017-06-10")] == pd.Timestamp("2017-06-13")
    assert programa[("petroleo", "2017-06-09")] == pd.Timestamp("2017-06-10")
    assert programa[("feriados", "2017-08")] == pd.Timestamp("2017-07-01")


def test_petroleo_sin_fines_de_semana(datos, cfg):
    programa = programa_base(tablas(datos, cfg), cfg)
    fechas = pd.to_datetime(programa.loc[programa["fuente"] == "petroleo", "clave"])
    assert (fechas.dt.day_of_week < 5).all()


def test_historico_solo_tiene_lo_que_llego_antes_del_inicio(datos, cfg, tmp_path):
    generar(datos, cfg, tmp_path / "origen")
    hist = tmp_path / "origen" / "historico"
    maximo = {f: pd.read_csv(hist / f"{f}.csv")["date"].max()
              for f in ("ventas", "promociones", "transacciones", "petroleo")}
    assert maximo["ventas"] == "2017-05-30"          # las de 05-31 llegan el 06-01
    assert maximo["promociones"] == "2017-06-16"     # se conocen 16 días antes
    assert maximo["transacciones"] == "2017-05-28"   # llegan con 3 días de atraso
    assert maximo["petroleo"] <= "2017-05-30"


def test_bandeja_entre_inicio_y_ultima_llegada_de_ventas(datos, cfg, tmp_path):
    resumen = generar(datos, cfg, tmp_path / "origen")
    bandeja = leer_bandeja(tmp_path / "origen")
    assert bandeja["llegada"].min() >= cfg["inicio_bandeja"]
    assert bandeja["llegada"].max() == resumen["ultima_llegada"]


def test_la_ultima_version_de_ventas_es_el_dato_real(datos, cfg, tmp_path):
    generar(datos, cfg, tmp_path / "origen")
    bandeja = leer_bandeja(tmp_path / "origen")
    ventas = bandeja[bandeja["fuente"] == "ventas"].sort_values("llegada")
    finales = ventas.groupby("clave").tail(1)
    real = datos["train"].assign(clave=datos["train"]["date"].dt.strftime("%Y-%m-%d"))
    for f in finales.itertuples():
        obtenido = pd.read_csv(f.ruta).sort_values(["store_nbr", "family"]).reset_index(drop=True)
        esperado = (real.loc[real["clave"] == f.clave, ["store_nbr", "family", "sales"]]
                    .sort_values(["store_nbr", "family"]).reset_index(drop=True))
        pd.testing.assert_frame_equal(obtenido[["store_nbr", "family", "sales"]], esperado,
                                      check_dtype=False)


def test_cada_correccion_e_invalido_tiene_dos_entregas(datos, cfg, tmp_path):
    generar(datos, cfg, tmp_path / "origen")
    registro = pd.read_csv(tmp_path / "origen" / "incidentes_simulados.csv")
    bandeja = leer_bandeja(tmp_path / "origen")
    assert {"correccion", "invalido", "atraso"} <= set(registro["tipo"])
    for r in registro.itertuples():
        entregas = bandeja[(bandeja["fuente"] == r.fuente) & (bandeja["clave"] == r.clave)]
        if r.tipo == "atraso":
            assert entregas["llegada"].tolist() == [r.llegada_version_final]
        else:
            assert sorted(entregas["llegada"]) == [r.llegada_esperada, r.llegada_version_final]
        assert r.llegada_version_final > r.llegada_esperada


def test_tienda_nueva_se_anuncia_antes_de_abrir(datos, cfg, tmp_path):
    generar(datos, cfg, tmp_path / "origen")
    anuncio = tmp_path / "origen" / "bandeja" / "llegada=2017-06-13" / "tiendas_2017-06-13.csv"
    assert pd.read_csv(anuncio)["store_nbr"].tolist() == [5]
    assert 5 not in pd.read_csv(tmp_path / "origen" / "historico" / "tiendas.csv")["store_nbr"].values


def test_es_determinista_e_idempotente(datos, cfg, tmp_path):
    generar(datos, cfg, tmp_path / "a")
    generar(datos, cfg, tmp_path / "a")
    generar(datos, cfg, tmp_path / "b")
    assert huellas(tmp_path / "a") == huellas(tmp_path / "b")
    assert not (tmp_path / "a.tmp").exists()
    generar(datos, {**cfg, "semilla": cfg["semilla"] + 1}, tmp_path / "c")
    assert huellas(tmp_path / "a") != huellas(tmp_path / "c")


@pytest.mark.parametrize("variante", ["parcial", "valores", "negativas", "duplicadas", "esquema"])
def test_variantes_alteran_el_archivo(datos, cfg, variante):
    dia = datos["train"].loc[datos["train"]["date"] == "2017-07-03",
                             ["date", "store_nbr", "family", "sales"]].reset_index(drop=True)
    alterado = alterar(dia, variante, 123, cfg["incidentes"])
    if variante == "parcial":
        assert alterado["store_nbr"].nunique() == dia["store_nbr"].nunique() - 2
    elif variante == "valores":
        assert (alterado["sales"] <= dia["sales"]).all() and not alterado.equals(dia)
    elif variante == "negativas":
        assert (alterado["sales"] < 0).any()
    elif variante == "duplicadas":
        assert alterado.duplicated(["store_nbr", "family"]).any()
    else:
        assert "sales" not in alterado.columns


def test_faltan_archivos_de_kaggle(tmp_path):
    with pytest.raises(FileNotFoundError, match="train.csv"):
        kaggle.leer(tmp_path)
