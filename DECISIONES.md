# Decisiones técnicas y de producto

Cada decisión tiene su contexto, las alternativas consideradas y la justificación. Las decisiones
sobre disponibilidad de la información en el tiempo, validación de datos y manejo de correcciones
están marcadas con su tema.

## Infraestructura y versionado

### D1. Remoto de DVC en DagsHub
- **Decisión:** el remoto `origin` de DVC está en DagsHub (`https://dagshub.com/edward25nov/motor-reposicion.dvc`).
  Las credenciales van solo en `.dvc/config.local`, que no se sube a Git.
- **Alternativas:** carpeta local (como en clase), Amazon S3, Google Cloud Storage, Google Drive.
- **Justificación:** es gratuito, se conecta al repositorio de GitHub y guarda una copia de los datos
  fuera del equipo de desarrollo; con una carpeta local, perder el disco es perder el historial de
  versiones. S3 y GCS piden una cuenta con facturación; Google Drive pide autenticación OAuth en el
  navegador. El docente aprobó DagsHub.
- **Consecuencia:** DagsHub exige iniciar sesión incluso en repositorios públicos, así que `dvc pull`
  sin cuenta devuelve 401 (comprobado desde un clon limpio). No afecta la evaluación: el producto se
  reconstruye desde los CSV de Kaggle (D2) y el remoto solo sirve para reproducir versiones pasadas.

### D2. El producto se reconstruye desde los CSV originales de Kaggle
- **Decisión:** los cinco CSV se colocan en `data/raw/kaggle/` y todo lo demás (carga histórica,
  bandeja, datos procesados, modelos y pronósticos) se genera a partir de ellos. Ese mismo directorio
  está versionado con DVC (`data/raw/kaggle.dvc`).
- **Alternativas:** una ruta fuera del repositorio configurada por variable de entorno.
- **Justificación:** es como evalúa el docente. Usar el mismo directorio que versiona DVC permite
  comprobar con `dvc status data/raw/kaggle.dvc` que los archivos colocados son los originales.

### D3. Sin MLflow en este laboratorio
- **Decisión:** la comparación de modelos y la regla de reemplazo se registran en archivos de métricas
  versionados y en una función de Python con pruebas, sin servidor de MLflow.
- **Alternativas:** MLflow Tracking y Model Registry con alias `@champion`, como en la sesión 4.
- **Justificación:** el enunciado no lo pide y agrega un servicio más que levantar y mantener durante
  la evaluación. La regla de reemplazo es la misma idea (función pura que compara en un periodo común);
  solo cambia dónde se guarda el resultado.

## Sistema de origen simulado

El enunciado pide construir, a partir de Kaggle, una carga histórica inicial y una bandeja que simule
el sistema de origen. Lo hace `src/inventario/origen/` (`make origen`), con los parámetros de
`configs/bandeja.yaml`. El flujo trata la bandeja como externa: la lee, nunca la modifica.

### D4. La carpeta de la bandeja indica cuándo llegó cada archivo *(disponibilidad en el tiempo)*
- **Decisión:** cada archivo vive en `origen/bandeja/llegada=<AAAA-MM-DD>/<fuente>_<clave>.csv`.
  La clave es la fecha de los datos (en feriados, el mes `AAAA-MM`; en tiendas, el día del anuncio).
  Un archivo con la misma fuente y clave en una llegada posterior reemplaza al anterior: es una
  corrección o un reenvío.
- **Alternativas:** usar la fecha de modificación del archivo; una columna `fecha_llegada` dentro del
  archivo; un número de versión en el nombre (`_v2`).
- **Justificación:** la fecha de modificación no es confiable (cambia al copiar o clonar). Con la
  llegada en la ruta, la información disponible en un corte T es exactamente la de las carpetas con
  `llegada ≤ T`, sin abrir ningún archivo, y la versión vigente de cada dato es la de llegada más
  reciente. Un número de versión no dice cuándo estuvo disponible. Es el mismo patrón `fecha=...`
  usado en el landing de la sesión 2.

### D5. Corte entre carga histórica y bandeja: `inicio_bandeja = 2017-06-01` *(disponibilidad en el tiempo)*
- **Decisión:** se calcula, para cada archivo, cuándo habría llegado. Lo que llega antes del
  2017-06-01 forma la carga histórica (un CSV consolidado por fuente en `origen/historico/`); lo que
  llega desde esa fecha va a la bandeja. La bandeja termina con la última entrega de ventas
  (con los datos completos de Kaggle, el 2017-08-22).
- **Alternativas:** cortar por la fecha de los datos (todo lo anterior a T en la carga histórica);
  una bandeja más larga.
- **Justificación:** cortar por llegada es coherente con el principio fundamental: por ejemplo, las
  ventas del 31 de mayo llegan el 1 de junio y por eso están en la bandeja, y las promociones del 16 de
  junio ya se conocían y por eso están en la carga histórica. Junio a mediados de agosto da unas 11
  fechas de corte semanales para operar y hacer seguimiento, y deja más de cuatro años de historia
  para entrenar. La fecha es configurable y el generador funciona con CSV más cortos o más largos.

### D6. Frecuencia y anticipación de cada fuente *(disponibilidad en el tiempo)*

| Fuente | Sale de | Llega | Por qué |
|---|---|---|---|
| `ventas` | `train.csv` (sin `onpromotion`) | Diario, D+1 | El cierre de ventas del día se consolida durante la noche. El 25 de diciembre no hay archivo: las tiendas cierran. |
| `promociones` | `onpromotion` de `train.csv` | D−16 | Las promociones se planifican; separarlas como fuente anticipada permite usarlas en todo el horizonte del pronóstico sin fuga de información. 16 días es el horizonte que usa la competencia de Kaggle. |
| `transacciones` | `transactions.csv` | D+3 | Fuente lenta (conteo de tickets del punto de venta). Solo puede usarse como rezago. |
| `petroleo` | `oil.csv` | D+1, solo días hábiles | Precio de mercado publicado al cierre. Los fines de semana no hay archivo y algunos valores son nulos: es una situación esperada, no un error. |
| `feriados` | `holidays_events.csv` | El mes M se publica el día 1 del mes M−1 | El calendario de feriados se conoce con anticipación. |
| `tiendas` | `stores.csv` | 7 días antes de la primera venta | Una tienda nueva se anuncia antes de abrir; las que ya operaban están en la carga histórica. |

- **Alternativas para promociones:** dejarlas dentro del archivo de ventas (D+1) y no usarlas como
  variable del horizonte; usarlas sin restricción (fuga de información).
- **Justificación:** las promociones son una de las variables que más explican las ventas en este
  conjunto de datos. Modelarlas como un calendario comercial que se conoce antes es realista y conserva
  su valor sin violar el principio fundamental.

### D7. Incidentes simulados en la bandeja *(validación de datos y manejo de correcciones)*
- **Decisión:** el generador inyecta, con semilla fija, incidentes solo en la bandeja (la carga
  histórica está limpia). Cada archivo recibe a lo sumo uno:

| Incidente | Fuentes | Probabilidad | Qué llega |
|---|---|---|---|
| Corrección | ventas | 10 % | Primero una versión incompleta (faltan 3 tiendas: variante `parcial`) o con 5 % de ventas subestimadas (`valores`); entre 3 y 7 días después, la versión correcta. |
| Inválido | ventas | 4 % | Primero un archivo que no debe procesarse: ventas negativas (`negativas`), filas duplicadas (`duplicadas`) o una columna renombrada (`esquema`); 1 o 2 días después, el reenvío válido. |
| Atraso | ventas, transacciones | 5 % | El archivo llega entre 1 y 3 días más tarde de lo normal. |

- **Alternativas:** bandeja limpia y probar los incidentes solo en pytest; incidentes que dejan datos
  falsos de forma permanente.
- **Justificación:** con incidentes activos, las ejecuciones de Airflow que se entregan como evidencia
  muestran cómo reacciona el flujo (cuarentena, reprocesamiento, espera de datos atrasados). La última
  versión de cada archivo siempre coincide con el dato real de Kaggle, así que el seguimiento del
  desempeño mide contra la verdad. Una corrección solo puede afectar datos que ya se usaron, por eso
  las alteraciones de la variante `valores` subestiman ventas (el caso típico de un cierre incompleto).
- **Hoja de respuestas:** `origen/incidentes_simulados.csv` lista cada incidente. Sirve para pruebas
  y para la evidencia; el flujo nunca la lee: tiene que detectar los incidentes por sí mismo.

### D8. Generación determinista e idempotente
- **Decisión:** la misma semilla y los mismos CSV producen exactamente los mismos archivos. El
  generador escribe en `origen.tmp/` y reemplaza `origen/` al final.
- **Justificación:** reproducibilidad (cualquiera obtiene la misma bandeja) y que ejecutarlo dos veces
  dé el mismo resultado que una. `origen/` no se versiona en Git porque se reconstruye desde Kaggle y
  `configs/bandeja.yaml`.
