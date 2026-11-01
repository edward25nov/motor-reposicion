# Motor de reposición de inventario

Producto de ML que, en cada fecha de corte, entrega por tienda y familia de producto: pronóstico de ventas diario con cuantiles, pedido sugerido y seguimiento del desempeño de los pronósticos ya publicados.
Datos: Corporación Favorita (Kaggle *Store Sales*): train, stores, holidays_events, oil y transactions. Laboratorio 1 del curso Product Development.

## Comandos
- `make test`: ejecuta las pruebas.
- `make ingesta CORTE=AAAA-MM-DD`: procesa la bandeja hasta el corte (valida, cuarentena, registro).
- `make preparar CORTE=AAAA-MM-DD`: features del corte en `data/procesados/` (lectura as-of).
- `make backtest SNAPSHOT=AAAA-MM-DD` y `make entrenar SNAPSHOT=AAAA-MM-DD`: comparación de modelos y campeón-retador.
- `make publicar CORTE=AAAA-MM-DD` y `make reproducir CORTE=AAAA-MM-DD`: publicación inmutable del pronóstico y pedido, y su reproducción.
- `make airflow-up` / `make airflow-down`: Airflow 3.3.2 en Docker (http://localhost:8081, airflow/airflow).
- `make operar DESDE=AAAA-MM-DD HASTA=AAAA-MM-DD`: backfill de los tres DAGs (primero crea las corridas, luego activa los DAGs).
- `make reiniciar`: borra la base de Airflow y todo lo generado (no toca Kaggle ni origen/).
- `make seguimiento FECHA=AAAA-MM-DD`: reporte de desempeño de lo publicado con las ventas conocidas a la fecha.
- `make origen`: construye la carga histórica y la bandeja en `origen/` a partir de `data/raw/kaggle/`.
- Sin make: `PYTHONPATH=src python -m pytest -q` y `PYTHONPATH=src python -m inventario.origen.generar`.

## Estructura
- `src/inventario/`: toda la lógica, en módulos de Python con pruebas. Las rutas salen de `rutas.py` (la raíz se cambia con `MOTOR_RAIZ`, lo usan las pruebas).
- `src/inventario/origen/`: sistema de origen simulado (carga histórica + bandeja) construido desde Kaggle.
- `src/inventario/ingesta/`: `validacion.py` (reglas puras), `registro.py` (SQLite), `ingestar.py` (proceso por corte), `vigente.py` (lectura as-of).
- `src/inventario/preparacion/`: `calendario.py` (feriados), `features.py` (features por corte, función pura), `preparar.py` (corte en operación y conjunto de entrenamiento).
- `src/inventario/modelos/`: `baseline.py`, `gbm.py` (misma interfaz `ajustar`/`predecir` con columnas p10…p95), `metricas.py`, `promocion.py` (regla pura), `evaluacion.py` (esquema temporal común), `backtest.py`, `entrenar.py`, `registro.py`.
- `src/inventario/publicacion/`: `pedido.py` (pronóstico y pedido, funciones puras), `publicar.py` (publicación con manifest), `reproducir.py`.
- `data/publicado/`: publicaciones por corte; no va a Git.
- `models/`: versiones entrenadas y `registro.json` (vigente, anterior, decisiones); no va a Git.
- `data/procesados/`: features y reportes de calidad por corte, no va a Git.
- `data/ingesta/`: generado por la ingesta (recibidos, validos, registro.db, reportes), no va a Git.
- `origen/`: generado por `make origen`, no se versiona en Git. `bandeja/llegada=<AAAA-MM-DD>/<fuente>_<clave>.csv`: la carpeta es el día en que el archivo está disponible.
- `dags/`: DAGs de Airflow 3. Solo orquestan: llaman funciones de `src/inventario/`.
- `configs/`: configuración versionada (siempre se lee del repositorio, aunque cambie `MOTOR_RAIZ`) (costos de negocio, modelo, fuentes).
- `airflow/`: `docker-compose.yaml` (proyecto `motor-reposicion`, puerto 8081, repo en `/opt/motor`, origen en `/opt/origen:ro`), `Dockerfile`, `.env.example`.
- `src/inventario/seguimiento/`: `seguimiento.py` (métricas de lo publicado) y `reporte.py` (HTML).
- `src/inventario/operacion.py` (cuándo reentrenar y guardas de fin de operación) y `src/inventario/versionado.py` (dvc add/push del flujo).
- `tests/`: pruebas con pytest; corren en cada Pull Request (GitHub Actions).
- `docs/evidencias/`: capturas de Airflow, comparación de modelos, seguimiento y reproducción con DVC (copias pequeñas de reportes; la fuente es DVC).
- `DECISIONES.md`: decisiones técnicas y de producto, con alternativas y justificación. **Toda decisión nueva se agrega ahí** (numerada D1, D2, ...) en el mismo Pull Request que la implementa.

## Reglas de disponibilidad de la información
- Toda predicción se construye solo con la información disponible en el momento en que se emite (fecha de corte).
- La disponibilidad se mide por la llegada del archivo a la bandeja, no por la fecha de los datos que contiene.
- La bandeja es un sistema externo: se lee, nunca se modifica (se monta en solo lectura).
- Todo dato que alimente un pronóstico con corte T se lee con `vigente.leer(fuente, T)`: nunca directo de la bandeja ni de `validos/`.
- `origen/incidentes_simulados.csv` es la hoja de respuestas de la simulación: el flujo nunca la lee; solo la usan las pruebas y la evidencia.
- Los pronósticos publicados son inmutables (`publicar` no reescribe un corte ya publicado); una corrección de datos reprocesa la preparación y el seguimiento, no la publicación.
- Las features de un corte T solo usan cada fuente hasta T − atraso (`configs/preparacion.yaml`); hay una prueba que altera las ventas posteriores al corte y exige features idénticas.
- La validación temporal usa los mismos cortes para todos los modelos comparados; nunca split aleatorio.

## Reglas del modelo
- Todos los modelos comparados usan los mismos cortes y las mismas filas de entrenamiento (`modelos/evaluacion.py`).
- Un modelo solo se entrena con filas cuyo objetivo se conocía al inicio de su evaluación.
- El reemplazo del vigente lo decide solo `promocion.decidir` con la métrica de negocio; nunca a mano.
- La variable objetivo es log(1 + ventas); las predicciones se devuelven en unidades, ordenadas y no negativas.

## Reglas de Airflow
- Cada tarea usa `logical_date` (`{{ ds }}`), nunca la fecha de hoy.
- Todas las tareas usan el pool `motor` (1 cupo). Solo la ingesta y `entrenar_si_corresponde` usan `depends_on_past=True` (dependen del orden); el resto lee as-of. El backfill necesita `--reprocess-behavior failed`.
- Datos insuficientes al corte no son un error: `datos_suficientes` omite el corte y deja `publicado: false` con su motivo (D17). No volver a lanzar excepciones ahí: con `depends_on_past` bloquearían los lunes siguientes.
- Cada DAG empieza con `en_operacion` (`@task.short_circuit`): fuera de los datos del origen se omite. No usar `end_date` (el backfill lo ignora).
- Un corte T usa el modelo vigente as-of (`registro.vigente_al(T)`), nunca uno con snapshot posterior.
- El compose fija `OMP_NUM_THREADS=4` y un heartbeat de 1200 s: sin eso el entrenamiento deja sin CPU a Airflow (D37).
- Los modelos se guardan con `registro.guardar_modelo` (pickle en C + gzip), nunca con joblib: Airflow importa `dill` y contamina el pickler de joblib.
- Las versiones de `requirements.txt` están fijadas a las restricciones de Airflow 3.3.2: no cambiarlas sin cambiar la imagen.
- Las tareas son idempotentes: cada fecha escribe en su propia carpeta y reemplaza su resultado (borrar e insertar en una transacción).
- XCom solo lleva valores pequeños (rutas, conteos); los datos van a disco.
- Los datos inválidos detienen el flujo antes de contaminar el resultado; las situaciones esperadas del negocio (feriados, tiendas cerradas, tiendas o familias nuevas, archivos atrasados) no provocan fallas: son advertencias.

## Reglas de datos
- Ningún dato ni modelo se guarda en Git: se versionan con DVC (`dvc add` y `dvc push`).
- En Git solo van los punteros `.dvc` y los `.gitignore` de datos.
- Si cambian los datos, hacer `dvc add` y `dvc push` antes de commitear los punteros `.dvc`.
- Remoto de DVC: `origin` en DagsHub (https://dagshub.com/edward25nov/motor-reposicion.dvc). Las credenciales van solo en `.dvc/config.local`, nunca en Git.
- Los CSV originales de Kaggle viven en `data/raw/kaggle/` (versionados con DVC). Todo el producto debe poder reconstruirse a partir de ellos sin acceso al remoto: así lo evalúa el docente.
- Los costos de negocio viven en `configs/`; cambiarlos debe cambiar el pedido sin tocar código.

## Reglas de Git
- Nunca se trabaja en main: todo cambio va en una rama (feat/..., fix/..., docs/..., chore/...) y entra por Pull Request.
- Commits pequeños con un solo cambio lógico cada uno.
- Mensajes con Conventional Commits en español: `tipo: descripción` (feat, fix, docs, refactor, test, chore, ci, build).
- Nunca hacer force push (`--force` ni `--force-with-lease`) ni borrar tags.
