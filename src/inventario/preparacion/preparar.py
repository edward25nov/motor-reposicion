"""Preparación de los datos del modelo para una fecha de corte.

Lee cada fuente tal como se conocía en el corte (vigente.leer), revisa que haya datos suficientes
para pronosticar (`verificar`, que también reporta la frescura de las demás fuentes y los totales
atípicos) y escribe:
    data/procesados/features/corte=<AAAA-MM-DD>.parquet   una fila por serie y día del horizonte
    data/procesados/calidad/corte=<AAAA-MM-DD>.json       qué datos había y qué faltaba

Es idempotente: reescribe los archivos del corte con el mismo contenido.

Uso:
    PYTHONPATH=src python -m inventario.preparacion.preparar 2017-07-17
"""

import json
import sys

import numpy as np
import pandas as pd

from inventario import config, rutas
from inventario.ingesta import vigente
from inventario.preparacion import calendario
from inventario.preparacion.features import Insumos, features_corte

FUENTES = ("ventas", "promociones", "transacciones", "petroleo", "feriados", "tiendas")


class DatosInsuficientes(Exception):
    """Faltan datos recientes de ventas: pronosticar así no es confiable."""


def datos_al_corte(corte: str) -> dict[str, pd.DataFrame]:
    return {f: vigente.leer(f, corte) for f in FUENTES}


def _fecha(f) -> str | None:
    return f.strftime("%Y-%m-%d") if f is not None and not pd.isna(f) else None


def frescura(ins: Insumos, T: pd.Timestamp, cfg: dict) -> tuple[dict, list[str]]:
    """Última fecha disponible de las fuentes secundarias frente a la esperada, con advertencias."""
    disp, H = cfg["disponibilidad"], cfg["corte"]["horizonte_dias"]
    horizonte = pd.date_range(T + pd.Timedelta(days=1), periods=H)
    con_promo = ins.fechas[~np.all(np.isnan(ins.promos), axis=0)]
    cobertura_promo = float(np.isin(horizonte, con_promo).mean())
    trans = ins.transacciones.columns[ins.transacciones.notna().any(axis=0)]
    ultima_trans = trans.max() if len(trans) else None
    ultimo_petroleo = ins.petroleo.index[ins.petroleo.index <= T].max() if len(ins.petroleo) else None
    detalle = {
        "promociones_cobertura_horizonte": round(cobertura_promo, 3),
        "transacciones_ultima": _fecha(ultima_trans),
        "transacciones_esperada": _fecha(T - pd.Timedelta(days=disp["transacciones_atraso"])),
        "petroleo_ultimo": _fecha(ultimo_petroleo),
    }
    avisos = []
    if cobertura_promo < 1:
        avisos.append(f"promociones: solo {cobertura_promo:.0%} del horizonte tiene datos (el resto queda vacío)")
    tolerancia = pd.Timedelta(days=disp["transacciones_atraso"] + disp["tolerancia_atraso_ventas"])
    if ultima_trans is None or ultima_trans < T - tolerancia:
        avisos.append(f"transacciones atrasadas: última {detalle['transacciones_ultima']}")
    if ultimo_petroleo is None or ultimo_petroleo < T - pd.Timedelta(days=7):
        avisos.append(f"petróleo atrasado: último precio {detalle['petroleo_ultimo']}")
    return detalle, avisos


def atipicos(ins: Insumos, T: pd.Timestamp, cfg: dict) -> list[dict]:
    """Totales diarios por tienda de la última semana muy lejos de su mismo día de la semana.

    Compara con la mediana del mismo día de la semana en las 8 semanas previas; un feriado de la
    tienda no se revisa (es normal que venda distinto).
    """
    k = cfg["calidad"]["factor_atipico"]
    esperada = T - pd.Timedelta(days=cfg["disponibilidad"]["ventas_atraso"])
    hasta = ins.fechas.searchsorted(esperada, side="right")
    desde = max(hasta - 7 * 9, 0)
    fechas = ins.fechas[desde:hasta]
    unidades = np.expm1(ins.ventas[:, desde:hasta])
    tiendas = ins.series["store_nbr"].to_numpy()
    totales = (pd.DataFrame(unidades, columns=fechas).assign(store_nbr=tiendas)
               .groupby("store_nbr").sum(min_count=1))
    cal = calendario.banderas(ins.feriados, ins.tiendas, fechas[-7:]).set_index(["store_nbr", "date"])
    hallazgos = []
    for fecha in fechas[-7:]:
        previas = [f for f in fechas[:-7] if f.day_of_week == fecha.day_of_week]
        referencia = totales[previas].median(axis=1)
        for tienda, total in totales[fecha].dropna().items():
            base = referencia.get(tienda)
            if base is None or pd.isna(base) or base <= 0:
                continue
            feriado = cal.loc[(tienda, fecha), ["feriado_nacional", "feriado_local"]].any() \
                if (tienda, fecha) in cal.index else False
            if feriado:
                continue
            if total > k * base or total < base / k:
                hallazgos.append({"fecha": fecha.strftime("%Y-%m-%d"), "tienda": int(tienda),
                                  "total": round(float(total), 1), "referencia": round(float(base), 1)})
    return hallazgos


def calidad(ins: Insumos, corte: str, cfg: dict) -> dict:
    """Resumen de los datos disponibles al corte y si alcanzan para publicar.

    `suficiente` es falso si la última venta disponible es anterior a T - atraso - tolerancia; en
    ese caso `motivo` dice por qué. Las demás observaciones son advertencias: no impiden publicar.
    """
    T = pd.Timestamp(corte)
    disp = cfg["disponibilidad"]
    esperada = T - pd.Timedelta(days=disp["ventas_atraso"])
    con_dato = ins.fechas[~np.all(np.isnan(ins.ventas), axis=0)]
    con_dato = con_dato[con_dato <= esperada]
    ultima = con_dato.max() if len(con_dato) else None
    ultimos_7 = pd.date_range(esperada - pd.Timedelta(days=6), esperada)
    detalle_fuentes, advertencias = frescura(ins, T, cfg)
    raros = atipicos(ins, T, cfg)
    if raros:
        advertencias.append(f"{len(raros)} totales diarios por tienda atípicos (ver 'atipicos')")
    resumen = {
        "corte": T.strftime("%Y-%m-%d"),
        "ultima_venta_esperada": esperada.strftime("%Y-%m-%d"),
        "ultima_venta_disponible": _fecha(ultima),
        "dias_sin_ventas_ultimos_7": [d.strftime("%Y-%m-%d") for d in ultimos_7 if d not in set(con_dato)],
        "series": len(ins.series),
        "tiendas": int(ins.series["store_nbr"].nunique()),
        "fuentes": detalle_fuentes,
        "atipicos": raros,
        "advertencias": advertencias,
        "suficiente": True,
        "motivo": None,
    }
    limite = esperada - pd.Timedelta(days=disp["tolerancia_atraso_ventas"])
    if ultima is None or ultima < limite:
        resumen["suficiente"] = False
        resumen["motivo"] = (f"la última venta disponible es {resumen['ultima_venta_disponible']} y se necesita "
                             f"al menos {limite:%Y-%m-%d}")
    return resumen


def _guardar_calidad(resumen: dict) -> None:
    ruta = rutas.raiz() / "data" / "procesados" / "calidad" / f"corte={resumen['corte']}.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(resumen, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def verificar(corte: str) -> bool:
    """Revisa si hay datos para publicar el corte y deja el reporte de calidad.

    Si no los hay, el corte no se publica: el reporte queda con publicado = false y su motivo, y el
    seguimiento lo lista como corte sin publicación. No es un error del flujo: el lunes siguiente
    se vuelve a intentar con lo que haya llegado.
    """
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    resumen = calidad(Insumos.desde(datos_al_corte(corte)), corte, config.cargar("preparacion"))
    resumen["publicado"] = resumen["suficiente"]
    _guardar_calidad(resumen)
    for aviso in resumen["advertencias"]:
        print(f"calidad {corte}: ADVERTENCIA, {aviso}")
    if not resumen["suficiente"]:
        print(f"calidad {corte}: DATOS INSUFICIENTES, el corte no se publica: {resumen['motivo']}")
    return resumen["suficiente"]


def ejecutar(corte: str) -> str:
    corte = pd.Timestamp(corte).strftime("%Y-%m-%d")
    cfg = config.cargar("preparacion")
    ins = Insumos.desde(datos_al_corte(corte))
    resumen = calidad(ins, corte, cfg)
    if not resumen["suficiente"]:
        raise DatosInsuficientes(f"Corte {corte}: {resumen['motivo']}. No se pronostica con datos tan atrasados.")
    tabla = features_corte(ins, corte, cfg)
    resumen["filas"] = len(tabla)
    resumen["publicado"] = True

    destino = rutas.raiz() / "data" / "procesados" / "features" / f"corte={corte}.parquet"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tabla.to_parquet(tmp, index=False)
    tmp.replace(destino)
    _guardar_calidad(resumen)
    print(f"preparacion {corte}: {len(tabla)} filas; última venta {resumen['ultima_venta_disponible']}; "
          f"días sin ventas en la última semana: {resumen['dias_sin_ventas_ultimos_7'] or 'ninguno'}")
    return str(destino)


def cortes_semanales(desde: str, hasta: str, cfg: dict) -> list[pd.Timestamp]:
    """Fechas de corte (el día de la semana configurado) entre desde y hasta, inclusive."""
    dias = pd.date_range(desde, hasta)
    return list(dias[dias.day_of_week == cfg["corte"]["dia_semana"]])


def entrenamiento(snapshot: str, desde: str, hasta: str) -> pd.DataFrame:
    """Filas de features con su venta real para los cortes semanales entre desde y hasta.

    Usa una sola vista de los datos: la conocida en `snapshot` (vigente.leer). Cada corte del
    pasado aplica sus propias reglas de disponibilidad, así ninguna fila ve ventas posteriores a
    su corte. Solo se incluyen filas cuyo objetivo ya se conocía en el snapshot.
    """
    cfg = config.cargar("preparacion")
    ins = Insumos.desde(datos_al_corte(snapshot))
    tablas = [features_corte(ins, c, cfg) for c in cortes_semanales(desde, hasta, cfg)]
    tabla = pd.concat(tablas, ignore_index=True)
    conocido = pd.Timestamp(snapshot) - pd.Timedelta(days=cfg["disponibilidad"]["ventas_atraso"])
    tabla = tabla[tabla["ventas"].notna() & (tabla["fecha"] <= conocido)].reset_index(drop=True)
    texto = ["family", "city", "state", "tipo_tienda"]
    reales = [c for c in tabla.select_dtypes("float64").columns if c != "ventas"]
    return tabla.astype({**{c: "category" for c in texto}, **{c: "float32" for c in reales}})


if __name__ == "__main__":
    ejecutar(sys.argv[1])
