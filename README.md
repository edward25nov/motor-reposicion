# Motor de reposición de inventario

Producto de ML que cada semana transforma las ventas que llegan a diario en un pedido sugerido por tienda y familia de producto para el centro de distribución. Integra Git, DVC y Apache Airflow para que cada resultado publicado pueda rastrearse hasta el código, los datos y el modelo que lo produjeron.

Datos: Corporación Favorita (Kaggle *Store Sales – Time Series Forecasting*). Laboratorio 1 del curso Product Development.

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

Las instrucciones para levantar y ejecutar el producto se agregarán en este archivo.
