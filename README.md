# Motor de reposición de inventario

Producto de ML que cada semana transforma las ventas que llegan a diario en un pedido sugerido por tienda y familia de producto para el centro de distribución. Integra Git, DVC y Apache Airflow para que cada resultado publicado pueda rastrearse hasta el código, los datos y el modelo que lo produjeron.

Datos: Corporación Favorita (Kaggle *Store Sales – Time Series Forecasting*). Laboratorio 1 del curso Product Development.

## Levantar y ejecutar el producto desde cero

Requisitos: Docker Desktop (o Docker Engine con Compose v2), `make` y unos 6 GB de memoria para
Docker.

1. Clonar el repositorio y colocar los CSV de Kaggle en `data/raw/kaggle/` (ver *Datos de entrada*).
2. Levantar Airflow. Construye la imagen, genera el sistema de origen (carga histórica y bandeja)
   a partir de los CSV y deja la interfaz en <http://localhost:8081> (usuario `airflow`, clave
   `airflow`):

   ```bash
   make airflow-up
   ```

3. Ejecutar la operación sobre un periodo con backfill (por defecto, del 2017-06-01 al
   2017-08-22, todo el periodo de la bandeja):

   ```bash
   make operar DESDE=2017-06-01 HASTA=2017-08-22
   ```

   Corre tres DAGs: `ingesta_validacion` (diario), `pronostico_pedido` (cada lunes: pone al día
   la ingesta, entrena un retador cada 4 semanas, prepara los datos, publica el pronóstico y el
   pedido y los versiona con DVC) y `seguimiento_desempeno` (diario: compara lo publicado con las
   ventas reales). Cada fecha espera a la anterior. Las fechas sin datos en el origen terminan como
   omitidas (*skipped*), no como error. El avance se ve en la vista *Grid* de cada DAG.

4. Detener: `make airflow-down` (conserva la base de metadatos de Airflow).

Los resultados quedan en el repositorio: `data/ingesta/` (registro y cuarentena),
`data/procesados/`, `models/`, `data/publicado/corte=<fecha>/` y el seguimiento en
`data/reportes/seguimiento/al=<fecha>/reporte.html`.

En Linux, `make airflow-up` crea `airflow/.env` con tu usuario (`AIRFLOW_UID`) para que los
contenedores puedan escribir en `data/`. Los nombres del proyecto Compose (`motor-reposicion`), la
imagen, el volumen y el puerto 8081 son propios, para no chocar con otros Airflow del equipo.

## Datos de entrada

El producto se reconstruye desde los archivos originales de Kaggle. Descárgalos de
<https://www.kaggle.com/competitions/store-sales-time-series-forecasting/data> y copia estos cinco
archivos, sin cambiarles el nombre, en `data/raw/kaggle/`:

```
data/raw/kaggle/
├── train.csv
├── stores.csv
├── holidays_events.csv
├── oil.csv
└── transactions.csv
```

`test.csv` y `sample_submission.csv` no se usan.

## Versionado de datos (DVC)

Los datos, modelos y pronósticos publicados se versionan con DVC. El remoto está en DagsHub:
`https://dagshub.com/edward25nov/motor-reposicion.dvc`.

**Para evaluar el producto no hace falta acceso al remoto.** Basta con colocar los archivos de Kaggle
en `data/raw/kaggle/` como se indica arriba: todo lo demás se reconstruye a partir de ellos. Si los
archivos son los originales, su hash coincide con la versión registrada en `data/raw/kaggle.dvc`
(se puede comprobar con `dvc status data/raw/kaggle.dvc`).

DagsHub exige iniciar sesión incluso en repositorios públicos, así que `dvc pull` requiere una cuenta
de DagsHub con acceso al repositorio. Con ella:

```bash
dvc remote modify origin --local auth basic
dvc remote modify origin --local user <usuario-dagshub>
dvc remote modify origin --local password <token-dagshub>
dvc pull
```

## Sistema de origen simulado

A partir de los CSV de Kaggle se construyen la carga histórica inicial y la bandeja que simula el
sistema de origen (un archivo por fuente y fecha, con atrasos, correcciones y archivos inválidos):

```bash
make origen
```

El resultado queda en `origen/historico/` y `origen/bandeja/llegada=<AAAA-MM-DD>/`. Los parámetros
están en `configs/bandeja.yaml` y las decisiones detrás de ellos en `DECISIONES.md` (D4 a D8).

## Ingesta y validación

La ingesta lee la bandeja hasta una fecha de corte, valida cada archivo y deja en cuarentena los
inválidos (sin hacer fallar el proceso):

```bash
make ingesta CORTE=2017-07-15
```

El resultado queda en `data/ingesta/`: copia de lo recibido, datos validados, el registro
`registro.db` con el estado y tipo de cada archivo (nuevo, corrección, reenvío, repetido) y un
reporte por corte en `reportes/<corte>.json`. Las reglas de validación están en `DECISIONES.md`
(D9 a D13).

## Preparación de datos para el modelo

Para una fecha de corte (lunes) se arma la tabla de features con lo que se conocía ese día:

```bash
make preparar CORTE=2017-07-17
```

Escribe `data/procesados/features/corte=<fecha>.parquet` (una fila por tienda, familia y día del
horizonte de 14 días) y `data/procesados/calidad/corte=<fecha>.json`. Si las ventas están demasiado
atrasadas, se detiene con `DatosInsuficientes`. Decisiones en `DECISIONES.md` (D14 a D18).

## Modelos

```bash
make backtest SNAPSHOT=2017-06-05   # compara baseline y GBM con validación de origen móvil
make entrenar SNAPSHOT=2017-06-05   # entrena un retador y aplica la regla de reemplazo
```

El backtest deja en `data/reportes/backtest/snapshot=<fecha>/` las métricas por corte y un resumen;
`make entrenar` guarda cada versión en `models/` y la decisión en `models/registro.json`. Los
cuantiles, la ventana y la regla de reemplazo están en `configs/modelo.yaml`; los costos de
negocio, en `configs/negocio.yaml`. Decisiones y resultados en `DECISIONES.md` (D19 a D24).

## Pronóstico y pedido sugerido

```bash
make publicar CORTE=2017-07-17     # requiere make preparar del corte y un modelo vigente
make reproducir CORTE=2017-07-17   # recalcula y compara con lo publicado
```

Cada corte se publica una sola vez en `data/publicado/corte=<fecha>/`: `pronostico.parquet`
(cuantiles P10 a P95 por tienda, familia y día), `pedido.csv` (cantidad sugerida por tienda y
familia para la semana de miércoles a martes) y `manifest.json` (commit, modelo, configuración y
huella de los datos usados). Decisiones en `DECISIONES.md` (D25 a D28).

## Seguimiento del desempeño

```bash
make seguimiento FECHA=2017-08-22
```

Compara cada pronóstico y pedido publicado con las ventas conocidas a esa fecha (incluidas las
correcciones) y escribe `data/reportes/seguimiento/al=<fecha>/`: `pronostico_por_corte.csv`,
`pronostico_por_semana.csv`, `pedido_por_corte.csv` y `reporte.html`. El pedido se compara también
con una regla de referencia (pedir lo vendido la semana anterior). Decisiones en `DECISIONES.md`
(D35 y D36).

## Comandos sin Docker

Cada paso también se puede ejecutar fuera de Airflow con Python 3.12 o superior:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test PYTHON=.venv/bin/python
make origen PYTHON=.venv/bin/python
make ingesta CORTE=2017-07-17 PYTHON=.venv/bin/python
make entrenar SNAPSHOT=2017-06-05 PYTHON=.venv/bin/python
make preparar CORTE=2017-07-17 PYTHON=.venv/bin/python
make publicar CORTE=2017-07-17 PYTHON=.venv/bin/python
```
