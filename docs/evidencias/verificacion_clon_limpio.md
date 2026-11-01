# Verificación desde un clon limpio

Simulación de la evaluación del docente sobre `main` en el commit `88f7fb1` (merge del PR #11).

## Preparación

```bash
make reiniciar                                   # en la copia de desarrollo: base de Airflow y estado
docker image rm motor-reposicion-airflow:3.3.2   # también la imagen
git clone https://github.com/edward25nov/motor-reposicion.git && cd motor-reposicion
cp <descarga de Kaggle>/{train,stores,holidays_events,oil,transactions}.csv data/raw/kaggle/
make airflow-up
make operar
```

Sin `.dvc/config.local`: el clon no tiene credenciales de DagsHub, como el equipo docente.

## Resultados

| Verificación | Resultado |
|---|---|
| Los CSV colocados son los originales | `dvc add data/raw/kaggle && git diff --exit-code data/raw/kaggle.dvc`: sin diferencias (con un CSV alterado sí aparece la diferencia) |
| Origen generado por el servicio `origen` | 293 archivos de bandeja, del 2017-06-01 al 2017-08-22, 22 incidentes |
| Orden de tareas de `pronostico_pedido` | `en_operacion → ingestar → datos_suficientes → entrenar_si_corresponde → preparar → publicar → versionar`; `depends_on_past` solo en `ingestar` y `entrenar_si_corresponde` |
| Ejecuciones | 181 exitosas, 0 fallidas, **0 reintentos** (el entrenamiento del 2017-07-31, que antes de D37 necesitó un reintento, terminó al primer intento) |
| Corte 2017-08-21 y corrida programada de 2026 | `en_operacion` exitosa y el resto de las tareas *skipped* |
| Publicaciones | 11 cortes; los manifests registran `88f7fb1` y `git_cambios_sin_commit: false` |
| Decisiones de modelos | baseline inicial; GBM promovido el 2017-06-05 (−19.5 %) y el 2017-07-03 (−8.4 %); retador del 2017-07-31 descartado (0.5 % < 2 %): idénticas a la corrida anterior |
| Unidades sugeridas por corte | idénticas a la corrida anterior |
| Seguimiento al 2017-08-22 | 10 pedidos evaluados; costo 802,555 frente a 1,085,265 de la referencia (26.0 % de ahorro): idéntico |
| Reporte de calidad | 11 cortes publicados, 0 atípicos; advertencia de promociones faltantes en los cortes 2017-08-07 (57 % del horizonte) y 2017-08-14 (7 %) |
| `make operar` por segunda vez | código de salida 0; ninguna corrida nueva (84, 13 y 84, todas exitosas); los archivos de `data/` y `models/` quedan idénticos byte a byte |
