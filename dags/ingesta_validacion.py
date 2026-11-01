"""Ingesta y validación diaria de la bandeja.

1. en_operacion: omite la corrida si la fecha es posterior a la última llegada de la bandeja.
2. ingestar: procesa todo lo que llegó hasta la fecha lógica (inclusive): copia inmutable,
   validación, cuarentena de archivos inválidos y registro de correcciones. Un archivo inválido
   no hace fallar la tarea (queda en cuarentena); una carga histórica inválida sí.

Lógica en src/inventario/.
"""

from datetime import datetime, timedelta

from airflow.sdk import dag, task


@dag(
    dag_id="ingesta_validacion",
    schedule="@daily",
    start_date=datetime(2017, 6, 1),
    catchup=False,  # el pasado se procesa con backfill (make operar)
    max_active_runs=1,
    default_args={"depends_on_past": True, "retries": 2, "retry_delay": timedelta(minutes=1), "pool": "motor"},
    tags=["motor-reposicion"],
    doc_md=__doc__,
)
def ingesta_validacion():
    @task.short_circuit
    def en_operacion(fecha: str) -> bool:
        from inventario import operacion

        return operacion.hay_bandeja(fecha)

    @task
    def ingestar(fecha: str) -> dict:
        from inventario.ingesta import ingestar

        reporte = ingestar.ejecutar(fecha)
        return {"llegaron": reporte["archivos"], "cuarentena": len(reporte["cuarentena"]),
                "correcciones": len(reporte["correcciones"]), "por_tipo": reporte["por_tipo"]}

    fecha = "{{ ds }}"
    en_operacion(fecha) >> ingestar(fecha)


ingesta_validacion()
