"""Entrena un retador y decide si reemplaza al modelo vigente.

Con los datos conocidos en `snapshot`:
1. reserva los últimos `semanas_evaluacion` cortes evaluables (horizonte completo observado);
2. entrena el retador (GBM) solo con filas conocidas al inicio de esa reserva;
3. si no hay vigente al snapshot, el baseline entrenado con las mismas filas pasa a ser el vigente
   inicial;
4. evalúa retador y vigente (el vigente al snapshot, registro.vigente_al) en los cortes reservados
   y aplica la regla de promoción.

El modelo no se vuelve a entrenar con los cortes reservados: el que se usa es exactamente el que
se evaluó. Es idempotente: si la versión del snapshot ya está registrada, no hace nada.

Uso:
    make entrenar SNAPSHOT=2017-06-05
"""

import sys

import pandas as pd

from inventario import config
from inventario.modelos import metricas, promocion, registro
from inventario.modelos.baseline import Baseline
from inventario.modelos.evaluacion import cortes_evaluables, filas_entrenamiento
from inventario.modelos.gbm import GBMCuantiles
from inventario.preparacion.preparar import entrenamiento

_FECHA = "%Y-%m-%d"


def _evaluar(modelo, tabla, cfg_m, cfg_n) -> pd.DataFrame:
    return metricas.por_corte(metricas.detalle(tabla, modelo.predecir(tabla), cfg_m["cuantiles"], cfg_n))


def _entrada(tipo, snapshot, hasta, cortes, por_corte) -> dict:
    total = por_corte.agg({"costo_negocio": "sum"}).to_dict()
    return {
        "tipo": tipo,
        "snapshot": snapshot,
        "entrenado_hasta": hasta.strftime(_FECHA),
        "cortes_evaluacion": [c.strftime(_FECHA) for c in cortes],
        "costo_evaluacion": round(total["costo_negocio"], 2),
        "wape_evaluacion": round(float((por_corte["wape"] * por_corte["filas"]).sum() / por_corte["filas"].sum()), 4),
        "git_commit": registro.commit_git(),
    }


def ejecutar(snapshot: str, cfg_m: dict | None = None) -> dict:
    snapshot = pd.Timestamp(snapshot).strftime(_FECHA)
    cfg_m = cfg_m or config.cargar("modelo")
    cfg_p, cfg_n = config.cargar("preparacion"), config.cargar("negocio")
    reg = registro.cargar()
    version = f"gbm-{snapshot}"
    if version in reg["versiones"]:
        print(f"entrenar {snapshot}: {version} ya está registrado ({reg['versiones'][version]['decision']})")
        return reg

    cortes = cortes_evaluables(snapshot, cfg_m["entrenamiento"]["semanas_evaluacion"], cfg_p)
    desde = cortes[0] - pd.Timedelta(weeks=cfg_m["entrenamiento"]["ventana_semanas"])
    tabla = entrenamiento(snapshot, desde.strftime(_FECHA), cortes[-1].strftime(_FECHA))
    entreno = filas_entrenamiento(tabla, cortes[0], cfg_m, cfg_p)
    evaluar = tabla[tabla["corte"].isin(cortes)]
    hasta = entreno["fecha"].max()

    if registro.vigente_al(snapshot, reg) is None:
        base = Baseline(cfg_m["cuantiles"]).ajustar(entreno)
        nombre_base = f"baseline-{snapshot}"
        registro.guardar_modelo(nombre_base, base)
        reg["versiones"][nombre_base] = {
            **_entrada("baseline", snapshot, hasta, cortes, _evaluar(base, evaluar, cfg_m, cfg_n)),
            "decision": "vigente inicial", "motivo": "no había modelo vigente: el baseline es el piso",
        }

    nombre_vigente = registro.vigente_al(snapshot, reg)
    vigente = registro.cargar_modelo(nombre_vigente)
    retador = GBMCuantiles(cfg_m["cuantiles"], cfg_m["gbm"]).ajustar(entreno)
    pc_retador = _evaluar(retador, evaluar, cfg_m, cfg_n)

    if pd.Timestamp(reg["versiones"][nombre_vigente]["entrenado_hasta"]) > hasta:
        promueve, motivo = False, f"{nombre_vigente} se entrenó con datos posteriores a la evaluación"
    else:
        promueve, motivo = promocion.decidir(pc_retador, _evaluar(vigente, evaluar, cfg_m, cfg_n),
                                             cfg_m["promocion"])
    registro.guardar_modelo(version, retador)
    reg["versiones"][version] = {
        **_entrada("gbm", snapshot, hasta, cortes, pc_retador),
        "comparado_con": nombre_vigente,
        "decision": "promovido" if promueve else "descartado",
        "motivo": motivo,
    }
    reg["vigente"] = registro.vigente_al(pd.Timestamp.max, reg)   # el más reciente, como referencia
    registro.guardar(reg)
    print(f"entrenar {snapshot}: {version} vs {nombre_vigente}: {motivo}. Vigente: {reg['vigente']}")
    return reg


if __name__ == "__main__":
    ejecutar(sys.argv[1])
