PYTHON ?= $(shell command -v python3 2>/dev/null || command -v python)
export PYTHONPATH := src

.PHONY: test

test:
	$(PYTHON) -m pytest -q
