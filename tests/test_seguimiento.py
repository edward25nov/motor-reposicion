import pandas as pd
import pytest

from inventario.ingesta import ingestar
from inventario.modelos import entrenar
from inventario.origen.generar import generar
from inventario.preparacion import preparar
from inventario.publicacion import publicar
from inventario.seguimiento import seguimiento
from tests.test_modelos import cfg_rapido

CORTES = ["2017-07-03", "2017-07-10", "2017-07-17"]


@pytest.fixture
def operado(tmp_path, monkeypatch, datos, cfg):
    """Tres cortes publicados con la información disponible en cada uno."""
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    ingestar.ejecutar("2017-07-03")
    entrenar.ejecutar("2017-07-03", cfg_rapido())
    for corte in CORTES:
        ingestar.ejecutar(corte)
        preparar.ejecutar(corte)
        publicar.ejecutar(corte)
    return tmp_path


def leer(destino, nombre):
    return pd.read_csv(f"{destino}/{nombre}.csv")


def test_solo_evalua_lo_que_ya_se_conoce(operado):
    ingestar.ejecutar("2017-07-11")
    destino = seguimiento.ejecutar("2017-07-11")
    por_corte = leer(destino, "pronostico_por_corte")
    # El 07-17 aún no se publicaba y del 07-10 todavía no se conoce ningún día de su horizonte.
    assert por_corte["corte"].tolist() == ["2017-07-03"]
    # Al 07-11 se conocen, como mucho, las ventas hasta el 07-10: 7 días del horizonte del corte 07-03.
    assert por_corte.set_index("corte").loc["2017-07-03", "dias_observados"] <= 7
    # La cobertura del pedido del 07-03 termina el 07-11, cuya venta llega el 07-12.
    pedidos = leer(destino, "pedido_por_corte")
    assert pedidos.empty and "nivel_servicio" in pedidos.columns


def test_evalua_el_pedido_cuando_la_semana_esta_completa(operado, datos):
    ingestar.ejecutar("2017-08-31")
    destino = seguimiento.ejecutar("2017-08-31")
    pedidos = leer(destino, "pedido_por_corte")
    assert set(pedidos["corte"]) == set(CORTES)
    total = pedidos[pedidos["grupo"] == "total"].set_index("corte")
    # La venta real de la semana es la de Kaggle (después de todas las correcciones).
    tr = datos["train"]
    real = tr[tr["date"].between("2017-07-05", "2017-07-11")]["sales"].sum()
    assert total.loc["2017-07-03", "unidades_vendidas"] == pytest.approx(real)
    assert total["nivel_servicio"].between(0, 1).all()


def test_un_dia_faltante_posterga_la_evaluacion_del_pedido(operado, monkeypatch):
    """Si falta un día de la cobertura (atraso o cuarentena), el pedido todavía no se evalúa."""
    ingestar.ejecutar("2017-08-31")
    ventas = seguimiento._ventas(pd.Timestamp("2017-08-31"))
    sin_un_dia = ventas[ventas["fecha"] != "2017-07-07"]
    assert seguimiento.pedido(pd.Timestamp("2017-07-03"), sin_un_dia, seguimiento.config.cargar("negocio")) is None
    assert seguimiento.pedido(pd.Timestamp("2017-07-03"), ventas, seguimiento.config.cargar("negocio")) is not None


def test_es_idempotente_y_no_toca_lo_publicado(operado):
    ingestar.ejecutar("2017-08-31")
    publicado = {p: p.read_bytes() for p in (operado / "data" / "publicado").rglob("*") if p.is_file()}
    destino = seguimiento.ejecutar("2017-08-31")
    primero = {n: leer(destino, n) for n in ("pronostico_por_corte", "pedido_por_corte")}
    seguimiento.ejecutar("2017-08-31")
    for n, df in primero.items():
        pd.testing.assert_frame_equal(leer(destino, n), df)
    assert {p: p.read_bytes() for p in (operado / "data" / "publicado").rglob("*") if p.is_file()} == publicado
    html = (operado / "data" / "reportes" / "seguimiento" / "al=2017-08-31" / "reporte.html").read_text()
    assert "Seguimiento del desempeño" in html and "Pedido sugerido" in html
