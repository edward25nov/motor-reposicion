"""Seguimiento del desempeño: compara lo publicado con las ventas reales a medida que se conocen.

Para una fecha T toma todas las publicaciones con corte <= T y las ventas tal como se conocen en T
(vigente.leer: incluye las correcciones que ya llegaron) y calcula:
- pronóstico: WAPE, sesgo, RMSLE, pinball, cobertura P10–P90 y costo de negocio diario, por corte
  y por semana del horizonte, solo sobre los días cuya venta ya se conoce;
- pedido: para los cortes cuyo periodo de cobertura ya terminó, venta real de la semana contra la
  cantidad sugerida (nivel de servicio, faltante, sobrante, costo) y contra una regla de referencia
  (pedir lo vendido la semana anterior), separado en perecederos y no perecederos.

Escribe en data/reportes/seguimiento/al=<T>/: pronostico_por_corte.csv,
pronostico_por_semana.csv, pedido_por_corte.csv, cortes_sin_publicacion.csv y reporte.html. Es idempotente y reproducible: el
resultado depende solo de lo publicado hasta T y de los datos conocidos en T.

Uso:
    PYTHONPATH=src python -m inventario.seguimiento.seguimiento 2017-08-14
"""

import json
import sys

import numpy as np
import pandas as pd

from inventario import config, negocio, rutas
from inventario.ingesta import registro as registro_ingesta
from inventario.ingesta import vigente
from inventario.modelos import metricas
from inventario.seguimiento import reporte

LLAVE = ["store_nbr", "family"]
# Columnas de cada tabla, para escribir archivos legibles aunque todavía no haya filas.
METRICAS = ["wape", "sesgo", "rmsle", "pinball", "cobertura_p10_p90", "costo_negocio", "filas"]
COLUMNAS_PRONOSTICO = ["corte", "modelo", "dias_observados", *METRICAS]
COLUMNAS_PEDIDO = ["corte", "grupo", "cobertura", "unidades_pedidas", "unidades_vendidas", "nivel_servicio",
                   "objetivo_servicio", "faltante", "sobrante", "costo_pedido", "costo_referencia",
                   "ahorro_vs_referencia"]


def publicaciones(hasta: pd.Timestamp) -> list[pd.Timestamp]:
    base = rutas.raiz() / "data" / "publicado"
    cortes = [pd.Timestamp(p.name.removeprefix("corte=")) for p in base.glob("corte=*")
              if (p / "manifest.json").is_file()]
    return sorted(c for c in cortes if c <= hasta)


def _ventas(fecha: pd.Timestamp) -> pd.DataFrame:
    v = vigente.leer("ventas", fecha.strftime("%Y-%m-%d"))
    return v[["date", *LLAVE, "sales"]].rename(columns={"date": "fecha", "sales": "ventas"})


def _correcciones(fecha: pd.Timestamp) -> pd.DataFrame:
    con = registro_ingesta.conectar()
    try:
        c = registro_ingesta.correcciones(con, "0000-00-00", fecha.strftime("%Y-%m-%d"))
    finally:
        con.close()
    return c[c["fuente"] == "ventas"]


def pronostico(corte: pd.Timestamp, ventas: pd.DataFrame, cuantiles, cfg_n) -> pd.DataFrame | None:
    """Filas del pronóstico del corte cuya venta real ya se conoce, con sus métricas por fila."""
    pron = pd.read_parquet(rutas.raiz() / "data" / "publicado" / f"corte={corte:%Y-%m-%d}" / "pronostico.parquet")
    tabla = pron.merge(ventas, on=["fecha", *LLAVE], how="inner")
    if tabla.empty:
        return None
    d = metricas.detalle(tabla, tabla, cuantiles, cfg_n)
    d["fecha"] = tabla["fecha"].to_numpy()
    d["semana"] = np.where(tabla["h"] <= 7, "semana 1 (h 1-7)", "semana 2 (h 8-14)")
    d["modelo"] = tabla["modelo"].to_numpy()
    return d


def pedido(corte: pd.Timestamp, ventas: pd.DataFrame, cfg_n: dict) -> pd.DataFrame | None:
    """Evaluación del pedido del corte si ya hay ventas de todos los días de su cobertura.

    No basta con que haya pasado la fecha: un día atrasado o en cuarentena todavía no se conoce.
    """
    ped = pd.read_csv(rutas.raiz() / "data" / "publicado" / f"corte={corte:%Y-%m-%d}" / "pedido.csv",
                      parse_dates=["corte", "entrega", "cobertura_hasta"])
    desde, hasta = ped["entrega"].iloc[0], ped["cobertura_hasta"].iloc[0]
    if not set(pd.date_range(desde, hasta)) <= set(ventas["fecha"].unique()):
        return None
    real = (ventas[ventas["fecha"].between(desde, hasta)].groupby(LLAVE, as_index=False)["ventas"].sum()
            .rename(columns={"ventas": "real"}))
    # Referencia: lo que haría un gerente sin modelo, pedir lo vendido la semana anterior al corte.
    previa = (ventas[ventas["fecha"].between(corte - pd.Timedelta(days=7), corte - pd.Timedelta(days=1))]
              .groupby(LLAVE, as_index=False)["ventas"].sum().rename(columns={"ventas": "referencia"}))
    t = ped.merge(real, on=LLAVE, how="left").merge(previa, on=LLAVE, how="left").fillna({"real": 0.0, "referencia": 0.0})
    costos = negocio.costos(t["family"], cfg_n)
    t["grupo"] = negocio.grupo(t["family"], cfg_n).to_numpy()
    for nombre, cantidad in (("pedido", t["cantidad_sugerida"]), ("referencia", t["referencia"])):
        t[f"costo_{nombre}"] = metricas.costo_negocio(t["real"], cantidad.to_numpy(), costos)
    t["cubierto"] = (t["real"] <= t["cantidad_sugerida"]).astype(float)
    t["faltante"] = np.clip(t["real"] - t["cantidad_sugerida"], 0, None)
    t["sobrante"] = np.clip(t["cantidad_sugerida"] - t["real"], 0, None)
    filas = []
    for grupo, g in [("total", t), *t.groupby("grupo")]:
        filas.append({
            "corte": corte, "grupo": grupo, "cobertura": f"{desde:%Y-%m-%d} a {hasta:%Y-%m-%d}",
            "unidades_pedidas": g["cantidad_sugerida"].sum(), "unidades_vendidas": g["real"].sum(),
            "nivel_servicio": g["cubierto"].mean(),
            "objetivo_servicio": negocio.costos(g["family"], cfg_n)["proporcion_critica"].mean(),
            "faltante": g["faltante"].sum(), "sobrante": g["sobrante"].sum(),
            "costo_pedido": g["costo_pedido"].sum(), "costo_referencia": g["costo_referencia"].sum(),
        })
    r = pd.DataFrame(filas)
    r["ahorro_vs_referencia"] = 1 - r["costo_pedido"] / r["costo_referencia"]
    return r


def sin_publicacion(hasta: pd.Timestamp) -> pd.DataFrame:
    """Cortes que no se publicaron (datos insuficientes al corte), con su motivo."""
    filas = []
    for ruta in sorted((rutas.raiz() / "data" / "procesados" / "calidad").glob("corte=*.json")):
        c = json.loads(ruta.read_text(encoding="utf-8"))
        if pd.Timestamp(c["corte"]) <= hasta and c.get("publicado") is False:
            filas.append({"corte": c["corte"], "motivo": c["motivo"],
                          "ultima_venta_disponible": c["ultima_venta_disponible"]})
    return pd.DataFrame(filas, columns=["corte", "motivo", "ultima_venta_disponible"])


def _resumen(d: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    filas = []
    for clave, g in d.groupby(por):
        clave = clave if isinstance(clave, tuple) else (clave,)
        filas.append({**dict(zip(por, clave)), "modelo": g["modelo"].iloc[0], "dias_observados": g["fecha"].nunique(),
                      **metricas.resumir(g)})
    return pd.DataFrame(filas)


def ejecutar(fecha: str) -> str:
    T = pd.Timestamp(fecha)
    cfg_m, cfg_n, cfg_p = config.cargar("modelo"), config.cargar("negocio"), config.cargar("preparacion")
    conocido = T - pd.Timedelta(days=cfg_p["disponibilidad"]["ventas_atraso"])
    ventas = _ventas(T)
    ventas = ventas[ventas["fecha"] <= conocido]

    detalles, pedidos = [], []
    for corte in publicaciones(T):
        d = pronostico(corte, ventas, cfg_m["cuantiles"], cfg_n)
        if d is not None:
            detalles.append(d)
        p = pedido(corte, ventas, cfg_n)
        if p is not None:
            pedidos.append(p)

    destino = rutas.reportes() / "seguimiento" / f"al={T:%Y-%m-%d}"
    destino.mkdir(parents=True, exist_ok=True)
    correcciones = _correcciones(T)
    if detalles:
        todo = pd.concat(detalles, ignore_index=True)
        por_corte = _resumen(todo, ["corte"])
        por_semana = _resumen(todo, ["corte", "semana"])
    else:
        por_corte = pd.DataFrame(columns=COLUMNAS_PRONOSTICO)
        por_semana = pd.DataFrame(columns=["corte", "semana", *COLUMNAS_PRONOSTICO[1:]])
    por_pedido = pd.concat(pedidos, ignore_index=True) if pedidos else pd.DataFrame(columns=COLUMNAS_PEDIDO)
    omitidos = sin_publicacion(T)
    for nombre, tabla in (("pronostico_por_corte", por_corte), ("pronostico_por_semana", por_semana),
                          ("pedido_por_corte", por_pedido), ("cortes_sin_publicacion", omitidos)):
        tabla.to_csv(destino / f"{nombre}.csv", index=False, date_format="%Y-%m-%d", float_format="%.6g")
    (destino / "reporte.html").write_text(
        reporte.html(T, por_corte, por_semana, por_pedido, len(correcciones), omitidos), encoding="utf-8")
    print(f"seguimiento al {T:%Y-%m-%d}: {len(por_corte)} cortes con ventas conocidas, "
          f"{len(por_pedido[por_pedido['grupo'] == 'total']) if len(por_pedido) else 0} pedidos evaluados, "
          f"{len(correcciones)} correcciones de ventas incorporadas, "
          f"{len(omitidos)} cortes sin publicación")
    return str(destino)


if __name__ == "__main__":
    ejecutar(sys.argv[1])
