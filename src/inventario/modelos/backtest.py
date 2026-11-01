"""Comparación de modelos con validación de origen móvil.

Con los datos conocidos en `snapshot`, toma los últimos pliegues × semanas_evaluacion cortes
evaluables y los divide en bloques consecutivos. Para cada bloque, cada modelo se entrena desde
cero con las filas conocidas al inicio del bloque y se evalúa en sus cortes. Todos los modelos usan
exactamente los mismos bloques, filas y cortes.

Escribe en data/reportes/backtest/snapshot=<fecha>/:
    por_corte.csv    métricas de cada modelo en cada corte
    resumen.json     métricas agregadas y la decisión de la regla de promoción (gbm vs baseline)

Uso:
    make backtest SNAPSHOT=2017-06-05
"""

import json
import sys

import pandas as pd

from inventario import config, rutas
from inventario.modelos import metricas, promocion
from inventario.modelos.baseline import Baseline
from inventario.modelos.evaluacion import cortes_evaluables, filas_entrenamiento
from inventario.modelos.gbm import GBMCuantiles
from inventario.preparacion.preparar import entrenamiento


def modelos(cfg_modelo: dict) -> dict:
    q = cfg_modelo["cuantiles"]
    return {"baseline": lambda: Baseline(q), "gbm": lambda: GBMCuantiles(q, cfg_modelo["gbm"])}


def ejecutar(snapshot: str, cfg_m: dict | None = None) -> dict:
    snapshot = pd.Timestamp(snapshot).strftime("%Y-%m-%d")
    cfg_m = cfg_m or config.cargar("modelo")
    cfg_p, cfg_n = config.cargar("preparacion"), config.cargar("negocio")
    semanas = cfg_m["entrenamiento"]["semanas_evaluacion"]
    cortes = cortes_evaluables(snapshot, cfg_m["backtest"]["pliegues"] * semanas, cfg_p)
    bloques = [cortes[i:i + semanas] for i in range(0, len(cortes), semanas)]
    desde = cortes[0] - pd.Timedelta(weeks=cfg_m["entrenamiento"]["ventana_semanas"])
    tabla = entrenamiento(snapshot, desde.strftime("%Y-%m-%d"), cortes[-1].strftime("%Y-%m-%d"))

    detalles = {nombre: [] for nombre in modelos(cfg_m)}
    for i, bloque in enumerate(bloques, start=1):
        entreno = filas_entrenamiento(tabla, bloque[0], cfg_m, cfg_p)
        evaluar = tabla[tabla["corte"].isin(bloque)]
        for nombre, crear in modelos(cfg_m).items():
            pred = crear().ajustar(entreno).predecir(evaluar)
            d = metricas.detalle(evaluar, pred, cfg_m["cuantiles"], cfg_n)
            detalles[nombre].append(d.assign(pliegue=i))
            print(f"backtest {snapshot}: pliegue {i}, {nombre}: "
                  f"costo {d['costo'].sum():,.0f}, WAPE {metricas.resumir(d)['wape']:.3f}")

    por_corte = {n: metricas.por_corte(pd.concat(ds)) for n, ds in detalles.items()}
    promueve, motivo = promocion.decidir(por_corte["gbm"], por_corte["baseline"], cfg_m["promocion"])
    resumen = {
        "snapshot": snapshot,
        "cortes_evaluados": [c.strftime("%Y-%m-%d") for c in cortes],
        "pliegues": [[c.strftime("%Y-%m-%d") for c in b] for b in bloques],
        "modelos": {n: metricas.resumir(pd.concat(ds)) for n, ds in detalles.items()},
        "decision_gbm_vs_baseline": {"promueve": promueve, "motivo": motivo},
    }

    destino = rutas.reportes() / "backtest" / f"snapshot={snapshot}"
    destino.mkdir(parents=True, exist_ok=True)
    (pd.concat([pc.assign(modelo=n) for n, pc in por_corte.items()])
     .assign(corte=lambda d: d["corte"].dt.strftime("%Y-%m-%d"))
     .to_csv(destino / "por_corte.csv", index=False))
    (destino / "resumen.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    print(f"backtest {snapshot}: {motivo}")
    return resumen


if __name__ == "__main__":
    ejecutar(sys.argv[1])
