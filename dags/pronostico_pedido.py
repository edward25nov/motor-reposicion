"""Pronóstico y pedido sugerido semanal (cada lunes).

1. en_operacion: omite el corte si el origen ya no tiene ventas para él (fin de la operación
   simulada).
2. ingestar: pone al día la bandeja hasta el corte (idempotente; no depende del DAG diario).
3. datos_suficientes: si las ventas están demasiado atrasadas, el corte no se publica: queda
   omitido, con su motivo en el reporte de calidad y en el seguimiento. El lunes siguiente se
   vuelve a intentar con lo que haya llegado.
4. entrenar_si_corresponde: entrena un retador si no hay modelo vigente o si pasaron 4 semanas
   desde el último, y aplica la regla de reemplazo.
5. preparar: features con los datos tal como se conocían en el corte.
6. publicar: pronóstico, pedido y manifest; un corte ya publicado no se modifica.
7. versionar: dvc add de ingesta, procesados, modelos, publicaciones y reportes (push si hay
   credenciales).

Solo ingestar y entrenar_si_corresponde esperan a la corrida anterior (depends_on_past): el
registro de ingesta y el de modelos dependen del orden. El resto lee "as-of" y no lo necesita, así
una semana omitida no bloquea las siguientes.

Lógica en src/inventario/.
"""

from datetime import datetime, timedelta

from airflow.sdk import dag, task


@dag(
    dag_id="pronostico_pedido",
    schedule="0 0 * * 1",  # lunes a las 00:00: la fecha lógica es el propio lunes
    start_date=datetime(2017, 6, 5),
    catchup=False,  # el pasado se procesa con backfill (make operar)
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2), "pool": "motor",
                  "execution_timeout": timedelta(minutes=45)},
    tags=["motor-reposicion"],
    doc_md=__doc__,
)
def pronostico_pedido():
    @task.short_circuit
    def en_operacion(fecha: str) -> bool:
        from inventario import operacion

        return operacion.hay_ventas_para_corte(fecha)

    @task(depends_on_past=True)
    def ingestar(fecha: str) -> int:
        from inventario.ingesta import ingestar

        return ingestar.ejecutar(fecha)["archivos"]

    @task.short_circuit
    def datos_suficientes(fecha: str, _ingesta: int) -> bool:
        from inventario.preparacion import preparar

        return preparar.verificar(fecha)

    @task(depends_on_past=True)
    def entrenar_si_corresponde(fecha: str) -> str:
        from inventario import operacion

        return operacion.entrenar_si_corresponde(fecha)

    @task
    def preparar(fecha: str, _modelo: str) -> str:
        from inventario.preparacion import preparar

        return preparar.ejecutar(fecha)

    @task
    def publicar(fecha: str, _features: str) -> str:
        from inventario.publicacion import publicar

        return publicar.ejecutar(fecha)

    @task
    def versionar(_publicacion: str) -> dict:
        from inventario import versionado

        return versionado.ejecutar()

    fecha = "{{ ds }}"
    ingesta = ingestar(fecha)
    en_operacion(fecha) >> ingesta
    modelo = entrenar_si_corresponde(fecha)
    datos_suficientes(fecha, ingesta) >> modelo
    versionar(publicar(fecha, preparar(fecha, modelo)))


pronostico_pedido()
