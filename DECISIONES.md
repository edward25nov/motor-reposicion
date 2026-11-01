# Decisiones técnicas y de producto

Cada decisión tiene su contexto, las alternativas consideradas y la justificación. Las decisiones
sobre disponibilidad de la información en el tiempo, validación de datos y manejo de correcciones
están marcadas con su tema.

## Índice

- **Infraestructura y versionado**
  - D1. Remoto de DVC en DagsHub
  - D2. El producto se reconstruye desde los CSV originales de Kaggle
  - D3. Sin MLflow en este laboratorio
- **Sistema de origen simulado**
  - D4. La carpeta de la bandeja indica cuándo llegó cada archivo — *disponibilidad en el tiempo*
  - D5. Corte entre carga histórica y bandeja: `inicio_bandeja = 2017-06-01` — *disponibilidad en el tiempo*
  - D6. Frecuencia y anticipación de cada fuente — *disponibilidad en el tiempo*
  - D7. Incidentes simulados en la bandeja — *validación de datos y manejo de correcciones*
  - D8. Generación determinista e idempotente
- **Ingesta y validación**
  - D9. La ingesta procesa todo lo pendiente hasta el corte, no solo lo del día — *disponibilidad en el tiempo*
  - D10. Errores contra advertencias — *validación de datos*
  - D11. Un archivo inválido no hace fallar la ingesta; una carga histórica inválida sí — *validación de datos*
  - D12. Tipos de llegada y detección de correcciones — *manejo de correcciones*
  - D13. Lectura "as-of" desde el registro — *disponibilidad en el tiempo y manejo de correcciones*
- **Preparación de datos para el modelo**
  - D14. Corte semanal los lunes y horizonte de 14 días
  - D15. La disponibilidad esperada de cada fuente es configuración del producto — *disponibilidad en el tiempo*
  - D16. Features directas por horizonte, sin pronóstico recursivo
  - D17. Datos faltantes al corte: seguir si es posible, detenerse si las ventas están muy atrasadas — *validación de datos*
  - D18. Entrenamiento con cortes del pasado sobre una sola vista de los datos — *disponibilidad en el tiempo*
- **Modelado**
  - D19. Baseline: ingenuo estacional con cuantiles empíricos
  - D20. Modelo de ML: gradient boosting con pérdida cuantílica, sin deep learning
  - D21. Métrica de negocio: costo del cuantil crítico diario
  - D22. Validación temporal de origen móvil, igual para todos los modelos
  - D23. Regla explícita para reemplazar al modelo vigente
  - D24. Proceso campeón-retador y registro de modelos — *disponibilidad en el tiempo*
- **Pedido sugerido y publicación**
  - D25. El pedido es la suma de los cuantiles críticos diarios del periodo de cobertura
  - D26. Entrega a dos días y cobertura de una semana; sin inventario informado
  - D27. Publicación inmutable con manifest, y reproducción — *manejo de correcciones*
  - D28. Tiendas o categorías que el modelo no vio al entrenar
- **Orquestación con Airflow**
  - D29. Un entorno de Airflow propio y con las mismas versiones que el código
  - D30. El sistema de origen se genera antes de Airflow, una sola vez
  - D31. DAGs independientes que comparten un pool de un solo cupo
  - D32. Orden, backfill y modelo vigente "as-of" — *disponibilidad en el tiempo*
  - D33. Reentrenamiento cada 4 semanas y versionado con DVC dentro del flujo
  - D34. Los modelos se guardan con el pickler estándar, no con joblib
  - D35. Seguimiento del desempeño con las ventas conocidas a la fecha — *manejo de correcciones*
  - D36. El fin de la operación simulada se detecta por los datos, no por fechas fijas
  - D37. Límite de hilos para el entrenamiento dentro de Airflow

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

## Ingesta y validación

La ingesta (`src/inventario/ingesta/`, `make ingesta CORTE=AAAA-MM-DD`) lleva la bandeja a
`data/ingesta/`: copia inmutable de lo recibido (`recibidos/`), datos validados en Parquet
(`validos/`), un registro SQLite de cada archivo (`registro.db`) y un reporte por corte (`reportes/`).

### D9. La ingesta procesa todo lo pendiente hasta el corte, no solo lo del día *(disponibilidad en el tiempo)*
- **Decisión:** para el corte T se procesan, en orden de llegada, todos los archivos con
  `llegada ≤ T` que no estén registrados con el mismo contenido (hash MD5).
- **Alternativas:** procesar solo la carpeta `llegada=T`.
- **Justificación:** si un día no corre (caída, backfill parcial), el siguiente se pone al día solo.
  Procesar en orden de llegada hace que la clasificación de cada archivo (nuevo, corrección…) sea
  la misma corriendo día por día que de una sola vez; hay una prueba que lo verifica. Un archivo ya
  registrado con el mismo hash se salta: la ingesta es idempotente.

### D10. Errores contra advertencias *(validación de datos)*
- **Decisión:** un archivo va a **cuarentena** (no se usa nunca) si: le faltan columnas, está vacío
  o no se puede leer, tiene valores con tipo inválido o nulos en columnas obligatorias, ventas,
  promociones o transacciones negativas, filas duplicadas por su llave, fechas que no corresponden
  a su clave, ventas o transacciones de una tienda no anunciada, o familias desconocidas.
  Son **advertencias** (el archivo se usa): precio del petróleo nulo, tiendas que no reportan ese
  día, columnas de más, filas de tiendas aún no anunciadas sin actividad (se descartan) y
  promociones de una tienda aún no anunciada (se descartan esas filas).
- **Alternativas:** rechazar solo las filas malas y usar el resto del archivo; validar con una
  librería como pandera.
- **Justificación:** un archivo con negativos o duplicados indica un problema del proceso que lo
  generó; usar "lo que se salve" mezclaría datos de una versión defectuosa con datos buenos. Se
  rechaza completo y se espera el reenvío. Las advertencias corresponden a situaciones normales del
  negocio (en Kaggle, el petróleo no tiene precio algunos días y las tiendas tienen filas en cero
  antes de abrir) y por el enunciado no deben provocar fallas. Una promoción es un plan: que nombre
  una tienda que aún no existe no invalida las promociones de las demás. Las reglas son pocas y
  explícitas, así que una función propia con pruebas es más clara que una dependencia nueva.

### D11. Un archivo inválido no hace fallar la ingesta; una carga histórica inválida sí *(validación de datos)*
- **Decisión:** un archivo inválido de la bandeja queda en cuarentena, se reporta y la tarea
  termina bien. Si la carga histórica es inválida, la ingesta falla.
- **Alternativas:** fallar la tarea ante cualquier archivo inválido.
- **Justificación:** la cuarentena ya cumple "detenerse antes de contaminar"; fallar la tarea
  bloquearía también los archivos válidos del mismo día y obligaría a intervenir a mano, cuando lo
  normal es que el origen reenvíe el archivo. Sin carga histórica válida no hay con qué pronosticar:
  ahí sí hay que detenerse. Si falta un dato necesario para pronosticar se decide en la preparación
  de datos, no en la ingesta.

### D12. Tipos de llegada y detección de correcciones *(manejo de correcciones)*
- **Decisión:** cada archivo se registra con un tipo, comparando con sus versiones anteriores
  (misma fuente y clave, llegada anterior): `nuevo` (primera vez), `reenvio` (antes solo hubo
  versiones en cuarentena), `correccion` (ya había una versión válida con otro contenido) o
  `repetido` (mismo contenido que la última válida). Las correcciones se consultan con
  `registro.correcciones(desde, hasta)` para reprocesar lo que dependía del dato corregido.
- **Justificación:** distinguir un reenvío de una corrección importa: un reenvío trae un dato que
  nunca se usó, una corrección cambia un dato que ya pudo alimentar un pronóstico publicado y el
  seguimiento del desempeño.

### D13. Lectura "as-of" desde el registro *(disponibilidad en el tiempo y manejo de correcciones)*
- **Decisión:** `vigente.leer(fuente, corte)` devuelve la carga histórica más, para cada clave de la
  bandeja, la versión válida de llegada más reciente con `llegada ≤ corte`. Todo lo que se use para
  pronosticar en T se lee así.
- **Justificación:** garantiza el principio fundamental por construcción: con el mismo corte se
  obtienen siempre los mismos datos, aunque después lleguen correcciones. Así un pronóstico pasado
  se puede reproducir con lo que se sabía entonces, y una corrección cuenta solo desde el día en que
  llegó.

## Preparación de datos para el modelo

La preparación (`src/inventario/preparacion/`, `make preparar CORTE=AAAA-MM-DD`) arma, para una
fecha de corte, la tabla de features con una fila por serie (tienda, familia) y día del horizonte.
Los parámetros están en `configs/preparacion.yaml`.

### D14. Corte semanal los lunes y horizonte de 14 días
- **Decisión:** el pronóstico y el pedido se emiten cada lunes (fecha de corte T) y cubren de T+1 a
  T+14.
- **Alternativas:** corte diario; horizonte de 7 o de 16 días.
- **Justificación:** el contexto pide una sugerencia semanal. El lunes ya están las ventas del fin
  de semana (llegan en D+1). 14 días cubren la semana de pedido más el tiempo de entrega y dejan
  medir el desempeño a una y dos semanas; con 16 días las promociones del último día del horizonte
  llegarían justo el día del corte, sin margen ante un atraso.

### D15. La disponibilidad esperada de cada fuente es configuración del producto *(disponibilidad en el tiempo)*
- **Decisión:** `configs/preparacion.yaml` define cuándo espera el producto cada fuente (ventas
  T−1, transacciones T−3, petróleo T−1, promociones hasta T+16, feriados del mes siguiente). Una
  fecha D de una fuente con atraso k solo se usa en el corte T si D ≤ T − k, aunque el archivo
  haya llegado antes.
- **Alternativas:** usar todo lo que haya llegado; leer los atrasos de `configs/bandeja.yaml`.
- **Justificación:** el simulador y el producto son sistemas distintos: en una empresa real el
  producto no conoce las reglas internas del origen, solo los atrasos acordados. Aplicar el atraso
  esperado además de la lectura as-of hace que una fuente que a veces llega antes no cambie las
  features según el día, y permite aplicar exactamente las mismas reglas a los cortes del pasado
  para entrenar (D18).

### D16. Features directas por horizonte, sin pronóstico recursivo
- **Decisión:** cada fila describe una serie en el corte T y un día objetivo T+h. Las variables de
  historia se calculan sobre log(1 + ventas) hasta T−1: medias de 7, 14, 28 y 56 días, último
  valor, tendencia (media 7 − media 28), proporción de ceros en 28 días, cobertura de la última
  semana, días con ventas y media del mismo día de la semana del objetivo en las últimas 4 y 8
  semanas. Del día objetivo: h, día de la semana, día del mes, mes, quincena (día 15 o fin de mes,
  días de pago en Ecuador), promociones planificadas y feriados. De la tienda: ciudad, provincia,
  tipo y cluster; además la media de transacciones de 28 días y el precio del petróleo con su
  cambio a 28 días.
- **Feriados (reglas de Kaggle):** un Holiday con `transferred=True` no se celebra ese día; sí el
  registro Transfer. Holiday, Transfer, Additional y Bridge son días libres; Work Day es un fin de
  semana que se trabaja; Event son fechas comerciales. National aplica a todas las tiendas,
  Regional a las de la provincia y Local a las de la ciudad.
- **Alternativas:** un modelo que pronostique un día y use su propio pronóstico como entrada para
  el siguiente (recursivo); un modelo por horizonte.
- **Justificación:** un único modelo global con h como variable usa solo datos reales observados,
  no acumula errores de un día al siguiente y entrena una sola vez. Trabajar en logaritmo reduce el
  peso de las series grandes y la asimetría de las ventas.

### D17. Datos faltantes al corte: seguir si es posible, detenerse si las ventas están muy atrasadas *(validación de datos)*
- **Decisión:** las medias ignoran los días sin dato (por un archivo atrasado o en cuarentena) y la
  tabla registra `cobertura_7`. El reporte `data/procesados/calidad/corte=T.json` lista los días sin
  ventas de la última semana. Si la última venta disponible es anterior a T − 1 − 3 días, la
  preparación falla con `DatosInsuficientes` y no se pronostica.
- **Alternativas:** no pronosticar si falta cualquier día; rellenar con ceros.
- **Justificación:** que falte un día por un atraso o un reenvío es una situación esperada del
  negocio y no debe impedir el pedido semanal; rellenar con ceros simularía una caída de ventas
  que no ocurrió. Pero sin ventas de casi una semana el pedido se basaría en información vieja:
  es preferible fallar de forma visible (Airflow reintenta y alerta) que publicar una
  recomendación poco confiable. Con la bandeja simulada esto ocurre, por ejemplo, en el corte
  2017-07-03: falta el 1 de julio (archivo en cuarentena) y la preparación sigue.

### D18. Entrenamiento con cortes del pasado sobre una sola vista de los datos *(disponibilidad en el tiempo)*
- **Decisión:** `preparar.entrenamiento(snapshot, desde, hasta)` lee los datos conocidos en
  `snapshot` y calcula las features de cada lunes entre `desde` y `hasta` con las reglas de D15. Solo
  se incluyen filas cuyo objetivo ya se conocía en `snapshot`.
- **Alternativas:** guardar y releer las features de cada corte tal como se emitieron.
- **Justificación:** ninguna fila ve ventas posteriores a su corte, y el modelo se entrena con lo
  que se sabía en `snapshot`, nunca con datos que llegaron después. La única aproximación es que,
  dentro de la historia, se usa la versión ya corregida de un dato aunque en aquel corte del pasado
  todavía no se conociera la corrección; para entrenar es preferible la mejor versión conocida. Los
  pronósticos publicados, en cambio, se calculan siempre con la vista estricta del corte (D13).
- **Tiendas nuevas:** una tienda sin historia aparece con las variables de historia vacías; el
  modelo y el baseline deben poder pronosticarla con las variables de la tienda y del calendario.

## Modelado

Los modelos están en `src/inventario/modelos/` y se configuran en `configs/modelo.yaml`; los costos
de negocio, en `configs/negocio.yaml`. `make backtest SNAPSHOT=…` compara los modelos y
`make entrenar SNAPSHOT=…` entrena un retador y aplica la regla de reemplazo.

### D19. Baseline: ingenuo estacional con cuantiles empíricos
- **Decisión:** el P50 del baseline es la media (en log) de las ventas del mismo día de la semana en
  las últimas 4 semanas; si no existe, la media de 28 días; si tampoco, cero. Los demás cuantiles
  suman al P50, por familia, los cuantiles de los residuos observados en entrenamiento.
- **Alternativas:** la venta de hace 7 días; la media móvil de 7 días.
- **Justificación:** la estacionalidad semanal es el patrón más fuerte de estas ventas; promediar
  cuatro semanas la conserva y suaviza días atípicos. Es simple, se explica en una línea y produce
  cuantiles, así que se compara con las mismas métricas que el modelo de ML.

### D20. Modelo de ML: gradient boosting con pérdida cuantílica, sin deep learning
- **Decisión:** un `HistGradientBoostingRegressor` de scikit-learn por cuantil (P10, P25, P50, P75,
  P90, P95), global para todas las series, entrenado sobre log(1 + ventas) con las features de D16 y
  las variables de tienda y familia como categóricas. Se entrena con 52 semanas de cortes.
- **Alternativas:** LightGBM; un modelo por tienda o familia; deep learning (DeepAR, LSTM).
- **Justificación:** el gradient boosting de scikit-learn maneja nulos y categóricas sin
  preprocesamiento, ya está en la imagen de Airflow (no agrega dependencias) y entrena un cuantil
  sobre 1.3 millones de filas en ~10 s. Un modelo global aprovecha patrones compartidos entre
  series y puede pronosticar tiendas nuevas. Como expm1 es creciente, el cuantil de log(1 + y) se
  convierte directamente en el cuantil de y. Deep learning no se justifica en costo y beneficio:
  DeepAR (replicado en Statistical Learning II) requiere GPU o mucho más tiempo de entrenamiento y
  más infraestructura para servirlo, y con 1,782 series diarias y variables tabulares fuertes
  (promociones, feriados) los modelos de árboles suelen igualarlo o superarlo; además el enunciado
  pone la complejidad en la operación, no en el modelo.
- **Post-proceso común a ambos modelos:** los cuantiles se ordenan por fila (no se cruzan), se
  recortan en cero, y una serie sin ninguna venta en los últimos 56 días conocidos se pronostica en
  cero (en Kaggle hay familias que una tienda no vende).

### D21. Métrica de negocio: costo del cuantil crítico diario
- **Decisión:** `configs/negocio.yaml` define, por unidad, el costo de quedarse sin producto
  (0.30, margen perdido) y el de que sobre: 0.25 para perecederos (PRODUCE, DAIRY, MEATS, POULTRY,
  SEAFOOD, BREAD/BAKERY, DELI, EGGS, PREPARED FOODS) por merma, y 0.05 para el resto por
  almacenamiento. La proporción crítica Cu / (Cu + Co) es 0.55 para perecederos y 0.86 para el
  resto. La métrica de negocio interpola cada día el pronóstico en esa proporción y suma
  0.30 × faltante + Co × sobrante contra la venta real.
- **Alternativas:** evaluar solo con métricas técnicas; un costo único para todas las familias.
- **Justificación:** es el problema del vendedor de periódicos (newsvendor): con esos costos, la
  cantidad que minimiza el costo esperado es el cuantil crítico de la demanda. La métrica mide
  exactamente lo que importa al negocio (quiebres de stock en alta rotación y merma en perecederos,
  como dice el contexto) y cambia si cambian los costos, sin tocar el código. Los valores son
  supuestos razonables a falta de costos reales de Favorita; lo importante es su proporción.
- **Métricas técnicas:** WAPE y sesgo del P50, RMSLE (la métrica de la competencia de Kaggle),
  pinball promedio de los cuantiles normalizada por las ventas, y cobertura del intervalo P10–P90
  (debería rondar 80 %).

### D22. Validación temporal de origen móvil, igual para todos los modelos
- **Decisión:** con los datos conocidos en el snapshot, se toman los últimos 12 cortes con el
  horizonte completo observado y se dividen en 3 bloques de 4. Para cada bloque, cada modelo se
  entrena desde cero con las filas cuyo objetivo se conocía al inicio del bloque (52 semanas) y se
  evalúa en sus cortes. Ambos modelos usan exactamente las mismas filas y cortes.
- **Alternativas:** una sola partición entrenamiento/prueba; validación cruzada aleatoria.
- **Justificación:** reproduce cómo opera el producto (entrenar con el pasado, pronosticar las
  semanas siguientes) y da 12 cortes para comparar, no uno. Una partición aleatoria filtraría
  información del futuro.
- **Resultado (snapshot 2017-06-05, cortes del 2017-02-27 al 2017-05-15):**

| Modelo | WAPE | Sesgo | RMSLE | Pinball | Cobertura P10–P90 | Costo de negocio |
|---|---|---|---|---|---|---|
| Baseline | 0.165 | −3.4 % | 0.587 | 0.060 | 80.6 % | 4,512,780 |
| GBM | **0.153** | −3.3 % | **0.497** | 0.064 | 85.2 % | **3,920,847** |

  El GBM reduce el costo de negocio 13.1 % y gana 11 de los 12 cortes. Su pinball en unidades es
  algo peor: el modelo optimiza la pérdida en logaritmo, que pesa igual a las series chicas y a
  las grandes, mientras que la pinball en unidades la dominan las series grandes. Su intervalo
  P10–P90 es un poco más ancho de lo necesario (85 % frente al 80 % nominal), lo que favorece al
  negocio en los no perecederos, donde conviene cubrir un cuantil alto.

### D23. Regla explícita para reemplazar al modelo vigente
- **Decisión:** un retador reemplaza al vigente solo si, evaluados ambos en los mismos cortes que
  ninguno usó para entrenar: (1) su costo de negocio es al menos 2 % menor, (2) tiene menor costo en
  al menos la mitad de los cortes y (3) su cobertura P10–P90 es de al menos 70 %. Si no, se
  descarta y queda registrado con el motivo. Si el vigente se entrenó con datos posteriores al
  inicio de la evaluación, la comparación no es válida y el vigente se mantiene.
- **Alternativas:** reemplazar siempre por el más reciente; decidir solo por WAPE.
- **Justificación:** el 2 % evita cambiar de modelo por ruido; exigir ganar en la mitad de los
  cortes evita que una sola semana buena decida; la cobertura mínima evita promover un modelo que
  ahorra costo porque sus intervalos dejaron de ser confiables. La decisión se toma con la métrica
  de negocio porque es la que mide el resultado del producto. La regla es una función pura con
  pruebas (`modelos/promocion.py`).

### D24. Proceso campeón-retador y registro de modelos *(disponibilidad en el tiempo)*
- **Decisión:** `make entrenar SNAPSHOT=S` reserva los últimos 4 cortes evaluables de S, entrena el
  retador (GBM) solo con lo conocido antes de esa reserva y lo compara con el vigente en esos cortes.
  Si todavía no hay vigente, el baseline entrenado con las mismas filas es el vigente inicial. Cada
  versión queda en `models/<version>/modelo.joblib` y en `models/registro.json` con su ventana, los
  cortes de evaluación, el costo, el commit de Git, la decisión y el motivo. El modelo promovido no
  se vuelve a entrenar con los cortes reservados.
- **Alternativas:** volver a entrenar el ganador con todos los datos antes de usarlo.
- **Justificación:** el modelo que se usa es exactamente el que se evaluó, lo que hace la decisión
  trazable y reproducible. El costo es que el modelo vigente no vio las últimas ~6 semanas (4
  cortes reservados más su horizonte); con un reentrenamiento periódico ese atraso no crece. Con
  los datos reales, el primer entrenamiento (S = 2017-06-05) dejó al baseline como vigente inicial
  y promovió al GBM: 19.0 % menos costo, ganó los 4 cortes, cobertura 86.1 %.
- **Medición del costo de no reentrenar:** se comparó el mismo GBM entrenado hasta el 2017-04-23
  (como queda con esta decisión) contra uno reentrenado con todo lo conocido al 2017-06-05, en los
  9 cortes del 2017-06-05 al 2017-07-31, que ninguno vio:

| Opción | WAPE | RMSLE | Cobertura P10–P90 | Costo de negocio |
|---|---|---|---|---|
| Sin reentrenar (esta decisión) | 0.125 | 0.397 | 89.2 % | 2,301,064 |
| Reentrenado con los cortes reservados | 0.128 | 0.396 | 90.8 % | 2,269,277 |
| Baseline (referencia) | 0.138 | 0.448 | 84.4 % | 2,706,210 |

  Reentrenar baja el costo solo 1.4 %, gana 5 de 9 cortes y empeora levemente el WAPE: con la regla
  de D23 (mejora mínima de 2 %) ni siquiera calificaría como mejor. La trazabilidad vale más que
  esa diferencia. Para que el atraso no crezca, el reentrenamiento se programa cada 4 semanas.

## Pedido sugerido y publicación

`make publicar CORTE=…` aplica el modelo vigente a las features del corte y publica en
`data/publicado/corte=<fecha>/` el pronóstico, el pedido y un manifest. Los parámetros del pedido
están en `configs/negocio.yaml` (sección `pedido`).

### D25. El pedido es la suma de los cuantiles críticos diarios del periodo de cobertura
- **Decisión:** para cada tienda y familia, se interpola cada día del periodo de cobertura el
  pronóstico en la proporción crítica de la familia (D21) y se suman esos valores; se resta el
  inventario disponible y se redondea hacia arriba.
- **Alternativas:** el cuantil crítico de la demanda semanal suponiendo días independientes
  (aproximación normal); escalar el margen sobre el P50 con un factor calibrado.
- **Justificación:** sumar cuantiles es exacto si los errores de los días están perfectamente
  correlacionados y conservador si no; suponer independencia subestima el riesgo, porque cuando
  una serie se desvía suele hacerlo varios días seguidos. Se midió el nivel de servicio semanal
  real (proporción de semanas en que la venta no supera el pedido) y el costo con un factor
  k ∈ [0.5, 1] sobre el margen (pedido = P50 + k · (crítico − P50)), con un GBM entrenado hasta el
  2017-02-26 en los 12 cortes de febrero a mayo de 2017, antes de operar:

| k | Servicio no perecederos (objetivo 85.7 %) | Servicio perecederos (objetivo 54.5 %) | Costo semanal |
|---|---|---|---|
| **1.0 (esta decisión)** | 92.3 % | 54.8 % | **1,116,546** |
| 0.8 | 88.4 % | 53.2 % | 1,135,508 |
| 0.7 | 85.3 % | 52.3 % | 1,155,796 |
| 0.5 | 76.8 % | 50.7 % | 1,229,178 |

  k = 1 es el de menor costo aunque el servicio de los no perecederos quede por encima del
  objetivo: el margen extra compensa el sesgo a la baja del P50 (−3 %, D22). En junio y julio un
  factor de 0.7 habría costado 3.6 % menos, pero calibrarlo con el periodo que se evalúa sería
  usar información del futuro; no se agrega el factor.

### D26. Entrega a dos días y cobertura de una semana; sin inventario informado
- **Decisión:** el pedido del lunes T llega el miércoles (T+2) y cubre siete días, de T+2 a T+8,
  hasta que llega el pedido siguiente. Como las tiendas no informan inventario, se pide la
  cantidad completa (`inventario_disponible: 0`).
- **Alternativas:** cubrir desde T+1; estimar el inventario con pedidos y ventas anteriores.
- **Justificación:** el periodo de cobertura debe empezar cuando la mercadería está disponible y
  durar hasta la siguiente entrega; con 14 días de horizonte caben holgadamente. Estimar el
  inventario sin datos de recepción ni merma real sería inventar un dato; el parámetro permite
  conectar el inventario real cuando exista.

### D27. Publicación inmutable con manifest, y reproducción *(manejo de correcciones)*
- **Decisión:** cada corte se publica una sola vez en `data/publicado/corte=<fecha>/`:
  `pronostico.parquet`, `pedido.csv` y `manifest.json`. El manifest registra el commit de Git, la
  versión y el MD5 del modelo, el MD5 de las features y de cada archivo de configuración, y la
  huella de los datos: el hash de la lista exacta de archivos (fuente, clave, llegada, hash) que
  estaban vigentes al corte. Si el corte ya está publicado, publicar no hace nada.
  `make reproducir CORTE=…` vuelve a calcular el pronóstico con los datos as-of y el modelo del
  manifest y lo compara con lo publicado.
- **Alternativas:** volver a publicar cuando llega una corrección.
- **Justificación:** un pedido ya se envió al centro de distribución: reescribirlo con datos que
  llegaron después borraría lo que realmente se recomendó y haría imposible evaluar la decisión.
  Las correcciones se reflejan en el seguimiento y en los pronósticos siguientes, no en los
  publicados. Gracias a la lectura as-of, la huella de datos de un corte no cambia aunque lleguen
  correcciones, y la reproducción da exactamente el mismo resultado: con los datos reales, el
  corte 2017-07-03 se reproduce con diferencia 0 aunque el reenvío de las ventas del 1 de julio
  llegó el 4.

### D28. Tiendas o categorías que el modelo no vio al entrenar
- **Decisión:** una categoría desconocida (por ejemplo, una tienda nueva) entra al GBM como valor
  faltante; el pronóstico usa el resto de las variables (familia, ciudad, tipo, calendario).
- **Justificación:** el gradient boosting ya aprende qué hacer con faltantes, así que la tienda
  nueva recibe un pronóstico razonable en lugar de un error. Hay una prueba que entrena sin una
  tienda y exige pronóstico completo para ella.

## Orquestación con Airflow

Airflow 3.3.2 corre con Docker Compose desde `airflow/` (`make airflow-up`, `make operar`). Los DAGs
están en `dags/` y solo orquestan: cada tarea importa una función de `src/inventario/` y le pasa la
fecha lógica.

### D29. Un entorno de Airflow propio y con las mismas versiones que el código
- **Decisión:** el proyecto Compose se llama `motor-reposicion`, con imagen
  `motor-reposicion-airflow:3.3.2`, volumen `motor-reposicion_postgres-db` y la interfaz en el puerto
  8081. `requirements.txt` fija las versiones de pandas, numpy, scikit-learn, pyarrow, scipy,
  PyYAML y joblib a las restricciones de Airflow 3.3.2, y lo usan el entorno local, el CI y la
  imagen. El repositorio se monta completo en `/opt/motor` (fuera de `/opt/airflow`, cuyo dueño
  cambia `airflow-init`) y el sistema de origen, en `/opt/origen` en solo lectura.
- **Alternativas:** reutilizar el compose de la clase 4; dejar las versiones libres.
- **Justificación:** el compose de la clase 4 no fija `name:`, así que Docker usa el nombre de la
  carpeta (`airflow`) y dos proyectos compartirían el volumen de Postgres (comprobado: el volumen
  `airflow_postgres-db-volume` ya existía). Con versiones idénticas, un modelo serializado con
  joblib carga igual en el equipo, en el CI y en Airflow, y los resultados son reproducibles.
  Montar la bandeja en solo lectura hace cumplir, a nivel del sistema operativo, que el flujo
  nunca la modifique.

### D30. El sistema de origen se genera antes de Airflow, una sola vez
- **Decisión:** el servicio `origen` del compose genera la carga histórica y la bandeja desde
  `data/raw/kaggle/` y termina antes de que arranque Airflow. Guarda una marca con el hash de los
  CSV, la configuración y el código del generador; si al volver a levantar todo coincide, no
  regenera nada.
- **Alternativas:** un DAG que genere el origen; generarlo a mano con `make origen`.
- **Justificación:** el origen simula un sistema externo: no le corresponde a Airflow construirlo.
  Con la marca, levantar Airflow otra vez no reescribe la bandeja, ni pisa archivos que alguien
  haya agregado o cambiado a mano para probar situaciones nuevas.

### D31. DAGs independientes que comparten un pool de un solo cupo
- **Decisión:** `ingesta_validacion` corre todos los días; `pronostico_pedido` corre los lunes y
  `seguimiento_desempeno` todos los días (D35). Los dos últimos empiezan poniendo al día la
  ingesta hasta su fecha, en lugar de esperar al DAG diario con un sensor. Todas las tareas usan el
  pool `motor` de un cupo.
- **Alternativas:** un sensor entre DAGs; un solo DAG diario que pronostique los lunes; DAGs
  disparados por Assets.
- **Justificación:** como la ingesta es idempotente y procesa todo lo pendiente (D9), ningún DAG
  depende de que otro haya corrido, y no hay sensores que puedan quedar esperando
  para siempre. Las corridas disparadas por Assets no tienen fecha lógica, y aquí la fecha lógica
  es el corte. El pool de un cupo evita que dos tareas escriban a la vez el registro SQLite, los
  modelos o el caché de DVC.

### D32. Orden, backfill y modelo vigente "as-of" *(disponibilidad en el tiempo)*
- **Decisión:** todas las tareas usan `depends_on_past=True` (un corte espera al anterior) y el
  periodo se ejecuta con `airflow backfill create --reprocess-behavior failed` (corre las fechas
  pendientes y reintenta las fallidas, sin rehacer las exitosas). `make operar` crea primero los
  backfills y después activa los DAGs. Además, el modelo que usa un corte T es el vigente "as-of":
  la última versión aprobada con snapshot ≤ T (`registro.vigente_al`).
- **Alternativas:** `catchup=True`; confiar en que el backfill siempre corre en orden.
- **Justificación:** al activar un DAG con `catchup=False`, Airflow crea igual una corrida para la
  fecha más reciente; sin `depends_on_past`, esa corrida podría entrenar un modelo antes que las
  del pasado. El modelo "as-of" es la defensa de fondo: aunque algo corra fuera de orden, un pedido
  de junio nunca se calcula con un modelo entrenado con datos de julio (hay una prueba que lo
  verifica). Es el principio fundamental del enunciado aplicado también al modelo, no solo a los
  datos. Lo que pasa después del fin de los datos se resuelve en D36.

### D33. Reentrenamiento cada 4 semanas y versionado con DVC dentro del flujo
- **Decisión:** el DAG semanal entrena un retador si no hay modelo vigente o si pasaron 4 semanas
  desde el último (`configs/modelo.yaml`, `reentrenar_cada_semanas`), y aplica la regla de D23. Al
  final, `versionar` ejecuta `dvc add` de `data/ingesta`, `data/procesados`, `models` y
  `data/publicado`, y `dvc push` solo si hay credenciales del remoto en `.dvc/config.local`.
- **Alternativas:** reentrenar a mano; versionar con DVC solo desde el equipo del desarrollador.
- **Justificación:** D24 midió que el modelo pierde poco por no ver las últimas semanas; 4 semanas
  limitan ese atraso sin entrenar cada lunes. Versionar dentro del flujo cumple que los datos
  procesados, los modelos y los pronósticos publicados queden versionados sin intervención manual.
  Quien evalúa no tiene credenciales de DagsHub: en ese caso los datos quedan en el caché local de
  DVC y el flujo sigue. El flujo no hace commits a Git; fijar una versión (los punteros `.dvc`) es
  un commit del desarrollador.

### D34. Los modelos se guardan con el pickler estándar, no con joblib
- **Decisión:** `models/<version>/modelo.pkl.gz` se escribe con `pickle.dump` (el pickler en C de
  Python, protocolo más alto) dentro de un gzip sin fecha.
- **Alternativas:** `joblib.dump`, lo habitual con scikit-learn; instalar `dill` en todos los
  entornos.
- **Justificación:** al reproducir desde el equipo de desarrollo un pronóstico publicado por
  Airflow, el modelo no cargaba: *No module named 'dill'*. Airflow importa `dill` en las tareas, y
  `dill` modifica de forma global el pickler de Python puro, que es el que usa joblib; el modelo
  quedaba dependiendo de `dill` según qué se hubiera importado antes. El pickler en C no se ve
  afectado (hay una prueba que importa `dill`, guarda un modelo y verifica que el archivo no lo
  menciona). Instalar `dill` en todas partes ocultaría el problema sin resolverlo. El gzip sin
  fecha hace que el mismo modelo produzca siempre el mismo archivo y el mismo MD5 en el manifest.

### D35. Seguimiento del desempeño con las ventas conocidas a la fecha *(manejo de correcciones)*
- **Decisión:** el DAG diario `seguimiento_desempeno` (y `make seguimiento FECHA=…`) compara cada
  publicación con corte ≤ T con las ventas tal como se conocen en T, incluidas las correcciones que
  ya llegaron. Del pronóstico calcula, sobre los días con venta conocida, WAPE, sesgo, RMSLE,
  pinball, cobertura P10–P90 y costo diario, por corte y por semana del horizonte. El pedido se
  evalúa cuando hay ventas de **todos** los días de su cobertura (no basta con que haya pasado la
  fecha: un día atrasado o en cuarentena todavía no se conoce): nivel de servicio, faltante,
  sobrante y costo, por grupo (perecederos y no perecederos), y contra una regla de referencia que
  imita al gerente sin modelo: pedir lo vendido la semana anterior al corte. Escribe
  `data/reportes/seguimiento/al=<T>/` con tres CSV y `reporte.html`.
- **Alternativas:** evaluar solo una vez, cuando termina el horizonte; comparar solo con el baseline.
- **Justificación:** el contexto pide informar "qué tan acertadas fueron las sugerencias
  anteriores" a medida que se conocen las ventas, así que la evaluación se actualiza cada día y
  cambia si llega una corrección (los pronósticos publicados no cambian; su evaluación sí). La
  regla de referencia responde la pregunta de negocio: ¿el sistema ordena mejor que la práctica
  actual? Como cada reporte depende solo de lo publicado hasta T y de los datos conocidos en T, es
  reproducible.

### D36. El fin de la operación simulada se detecta por los datos, no por fechas fijas
- **Decisión:** cada DAG empieza con una tarea `en_operacion` (`@task.short_circuit`). La ingesta y
  el seguimiento se omiten si la fecha es posterior a la última llegada de la bandeja; el pronóstico
  se omite si el origen nunca llegó a tener ventas lo bastante recientes para el corte
  (`operacion.hay_ventas_para_corte`). Una corrida omitida termina en *skipped*, no en error. Dentro
  del periodo, si faltan ventas que sí debían llegar, la preparación sigue fallando con
  `DatosInsuficientes` (D17).
- **Alternativas:** `end_date` fijo en los DAGs, leído de una variable de entorno.
- **Justificación:** se probó primero con `end_date` por variable de entorno y falló de dos formas
  observadas: el backfill de Airflow ignora el `end_date` (creó el corte del 2017-08-21, sin ventas)
  y, al recrear los contenedores, hubo un momento en que el DAG ya leía una variable que el
  contenedor aún no tenía, quedó sin `end_date` y Airflow programó una corrida con fecha
  2026-10-26 que intentó entrenar. La guarda por datos no depende de la configuración ni de cómo se
  dispare la corrida (backfill, programada o manual) y sirve para cualquier periodo que se ejecute.
  Distingue "ya no hay más datos en el origen" (se omite) de "faltan datos que debían llegar" (se
  alerta). En producción la bandeja no termina y la guarda no omitiría nada.

### D37. Límite de hilos para el entrenamiento dentro de Airflow
- **Decisión:** el compose fija `OMP_NUM_THREADS=4` y sube
  `AIRFLOW__SCHEDULER__TASK_INSTANCE_HEARTBEAT_TIMEOUT` de 300 a 1200 segundos.
- **Alternativas:** dejar los valores por defecto y confiar en los reintentos.
- **Justificación:** en la corrida final, el entrenamiento del 2017-07-31 dejó de enviar su
  *heartbeat* por más de 5 minutos: el scheduler lo dio por muerto, lo terminó con SIGKILL y el
  reintento (`retries: 1`) lo completó. El gradient boosting de scikit-learn usa por defecto todos
  los núcleos (18 en el equipo de desarrollo) y deja sin CPU al resto de los procesos de Airflow.
  Medido dentro del contenedor, con 4 hilos un cuantil se entrena en 7.9 s frente a 9 s sin
  límite: el límite no cuesta tiempo y deja CPU libre. El reintento resolvió el síntoma, pero
  depender de él haría que en un equipo con menos recursos la tarea fallara de forma repetida. Los
  resultados no cambian: el pronóstico usa el modelo ya guardado.
