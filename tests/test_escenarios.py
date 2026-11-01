"""Escenarios de operación de punta a punta con el origen simulado."""

import json
import shutil

import pandas as pd

from inventario.ingesta import ingestar
from inventario.modelos import entrenar
from inventario.origen.generar import generar
from inventario.preparacion import preparar
from inventario.publicacion import publicar
from inventario.seguimiento import seguimiento
from tests.test_modelos import cfg_rapido


def retener_ventas(origen, desde: str, hasta: str, nueva_llegada: str) -> None:
    """Simula un corte del origen: las ventas que llegaban entre desde y hasta llegan todas juntas después."""
    destino = origen / "bandeja" / f"llegada={nueva_llegada}"
    destino.mkdir(exist_ok=True)
    for carpeta in sorted((origen / "bandeja").glob("llegada=*")):
        llegada = carpeta.name.removeprefix("llegada=")
        if desde <= llegada <= hasta:
            for archivo in carpeta.glob("ventas_*.csv"):
                shutil.move(archivo, destino / archivo.name)


def test_una_semana_sin_ventas_no_publica_y_luego_se_recupera(tmp_path, monkeypatch, datos, cfg):
    monkeypatch.setenv("MOTOR_RAIZ", str(tmp_path))
    monkeypatch.delenv("MOTOR_ORIGEN", raising=False)
    generar(datos, cfg, tmp_path / "origen")
    retener_ventas(tmp_path / "origen", "2017-07-04", "2017-07-11", "2017-07-12")
    ingestar.ejecutar("2017-07-03")
    entrenar.ejecutar("2017-07-03", cfg_rapido())

    # Corte 07-10: la última venta disponible es la del 07-02; el corte se omite, no falla.
    ingestar.ejecutar("2017-07-10")
    assert preparar.verificar("2017-07-10") is False
    calidad = json.loads((tmp_path / "data" / "procesados" / "calidad" / "corte=2017-07-10.json").read_text())
    assert calidad["publicado"] is False and "2017-07-02" in calidad["motivo"]

    # Las ventas retenidas llegan el 07-12: el corte siguiente se publica con normalidad.
    ingestar.ejecutar("2017-07-17")
    assert preparar.verificar("2017-07-17") is True
    preparar.ejecutar("2017-07-17")
    publicar.ejecutar("2017-07-17")
    assert (tmp_path / "data" / "publicado" / "corte=2017-07-17" / "manifest.json").is_file()
    assert not (tmp_path / "data" / "publicado" / "corte=2017-07-10").exists()

    # El seguimiento deja visible el corte que no se publicó.
    ingestar.ejecutar("2017-07-20")
    destino = seguimiento.ejecutar("2017-07-20")
    omitidos = pd.read_csv(f"{destino}/cortes_sin_publicacion.csv")
    assert omitidos["corte"].tolist() == ["2017-07-10"]
    assert "Cortes sin publicación" in (tmp_path / "data" / "reportes" / "seguimiento" / "al=2017-07-20" /
                                        "reporte.html").read_text()
