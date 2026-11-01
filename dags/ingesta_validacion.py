"""Ingesta y validación diaria de la bandeja.

Cada día procesa todo lo que llegó a la bandeja hasta la fecha lógica (inclusive): copia
inmutable, validación, cuarentena de archivos inválidos y registro de correcciones. Un archivo
inválido no hace fallar la tarea (queda en cuarentena); una carga histórica inválida sí.
Lógica en src/inventario/ingesta/.
"""

import os
from datetime import datetime, timedelta

from airflow.sdk import dag, task

# Última fecha de operación (fin de los datos de Kaggle). Evita que al activar el DAG Airflow cree
# una corrida con la fecha de hoy, para la que no hay datos. En producción se quitaría.
FIN = os.environ.get("MOTOR_FIN_OPERACION")


@dag(
    dag_id="ingesta_validacion",
    schedule="@daily",
    start_date=datetime(2017, 6, 1),
    end_date=datetime.fromisoformat(FIN) if FIN else None,
    catchup=False,  # el pasado se procesa con backfill (make operar)
    max_active_runs=1,
    default_args={"depends_on_past": True, "retries": 2, "retry_delay": timedelta(minutes=1), "pool": "motor"},
    tags=["motor-reposicion"],
    doc_md=__doc__,
)
def ingesta_validacion():
    @task
    def ingestar(fecha: str) -> dict:
        from inventario.ingesta import ingestar

        reporte = ingestar.ejecutar(fecha)
        return {"llegaron": reporte["archivos"], "cuarentena": len(reporte["cuarentena"]),
                "correcciones": len(reporte["correcciones"]), "por_tipo": reporte["por_tipo"]}

    ingestar("{{ ds }}")


ingesta_validacion()
