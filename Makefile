PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python)
export PYTHONPATH := src

.PHONY: test origen ingesta preparar

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
