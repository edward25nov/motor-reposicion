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
