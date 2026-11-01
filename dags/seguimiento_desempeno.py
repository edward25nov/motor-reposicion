"""Seguimiento diario del desempeño de lo publicado.

1. en_operacion: omite la corrida si la fecha es posterior a la última llegada de la bandeja.
2. ingestar: pone al día la bandeja hasta la fecha lógica (idempotente).
3. seguimiento: compara cada pronóstico y pedido publicado con las ventas reales conocidas a la
   fecha (incluidas las correcciones que ya llegaron) y escribe el reporte en
   data/reportes/seguimiento/al=<fecha>/ (CSV y reporte.html).

Cada día es independiente (lee lo publicado y las ventas conocidas a la fecha), así que no
espera a la corrida anterior. Lógica en src/inventario/seguimiento/.
"""

from datetime import datetime, timedelta

from airflow.sdk import dag, task


@dag(
    dag_id="seguimiento_desempeno",
    schedule="@daily",
    start_date=datetime(2017, 6, 6),   # el día siguiente al primer corte publicado
    catchup=False,  # el pasado se procesa con backfill (make operar)
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1), "pool": "motor"},
    tags=["motor-reposicion"],
    doc_md=__doc__,
)
def seguimiento_desempeno():
    @task.short_circuit
    def en_operacion(fecha: str) -> bool:
        from inventario import operacion

        return operacion.hay_bandeja(fecha)

    @task
    def ingestar(fecha: str) -> int:
        from inventario.ingesta import ingestar

        return ingestar.ejecutar(fecha)["archivos"]

    @task
    def seguimiento(fecha: str, _ingesta: int) -> str:
        from inventario.seguimiento import seguimiento

        return seguimiento.ejecutar(fecha)

    fecha = "{{ ds }}"
    ingesta = ingestar(fecha)
    en_operacion(fecha) >> ingesta
    seguimiento(fecha, ingesta)


seguimiento_desempeno()
