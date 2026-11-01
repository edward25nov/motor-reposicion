PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python)
export PYTHONPATH := src

.PHONY: test origen ingesta preparar backtest entrenar publicar reproducir airflow-up airflow-down operar

test:
	$(PYTHON) -m pytest -q

origen:
	$(PYTHON) -m inventario.origen.generar

# Ingesta de la bandeja hasta un corte: make ingesta CORTE=2017-07-15
ingesta:
	$(PYTHON) -m inventario.ingesta.ingestar $(CORTE)

# Features del modelo para un corte: make preparar CORTE=2017-07-17
preparar:
	$(PYTHON) -m inventario.preparacion.preparar $(CORTE)

# Comparación de modelos con origen móvil: make backtest SNAPSHOT=2017-06-05
backtest:
	$(PYTHON) -m inventario.modelos.backtest $(SNAPSHOT)

# Retador contra vigente con la regla de promoción: make entrenar SNAPSHOT=2017-06-05
entrenar:
	$(PYTHON) -m inventario.modelos.entrenar $(SNAPSHOT)

# Pronóstico y pedido sugerido del corte con el modelo vigente: make publicar CORTE=2017-07-17
publicar:
	$(PYTHON) -m inventario.publicacion.publicar $(CORTE)

# Recalcula una publicación y la compara con la publicada: make reproducir CORTE=2017-07-17
reproducir:
	$(PYTHON) -m inventario.publicacion.reproducir $(CORTE)

# --- Airflow (Docker Compose) ---------------------------------------------------------------
COMPOSE := docker compose -f airflow/docker-compose.yaml
DESDE ?= 2017-06-01
HASTA ?= 2017-08-14

# Construye la imagen, genera el origen desde data/raw/kaggle/ y levanta Airflow en localhost:8081.
airflow-up:
	@test -f airflow/.env || echo "AIRFLOW_UID=$$(id -u)" > airflow/.env
	$(COMPOSE) up -d --build --wait

airflow-down:
	$(COMPOSE) down

# Ejecuta el periodo DESDE..HASTA con backfill: make operar DESDE=2017-06-01 HASTA=2017-08-14
# Primero crea las corridas y después activa los DAGs: así ninguna corrida programada se adelanta.
operar:
	$(COMPOSE) exec airflow-scheduler airflow backfill create --dag-id ingesta_validacion \
		--from-date $(DESDE) --to-date $(HASTA) --max-active-runs 1 --reprocess-behavior failed
	$(COMPOSE) exec airflow-scheduler airflow backfill create --dag-id pronostico_pedido \
		--from-date $(DESDE) --to-date $(HASTA) --max-active-runs 1 --reprocess-behavior failed
	$(COMPOSE) exec airflow-scheduler airflow dags unpause ingesta_validacion
	$(COMPOSE) exec airflow-scheduler airflow dags unpause pronostico_pedido
