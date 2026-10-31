.PHONY: install test test-fast lint format typecheck model eval demo api worker web-install web-build bicep all

PY ?= python

install:
	$(PY) -m pip install -e ".[api,azure,pdf,dev]"

test:
	$(PY) -m pytest

test-fast:
	$(PY) -m pytest -m "not slow"

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy

model:            ## train + gate + package the risk model on synthetic data (~3 min)
	claimlens train

eval:             ## evaluation report -> reports/eval_report.md
	claimlens eval

demo: model       ## load 25 synthetic claims, process them, print the reviewer queue
	CLAIMLENS_DATA_DIR=.claimlens claimlens demo

api:              ## API on :8000 with inline processing (no worker needed)
	CLAIMLENS_INLINE_PROCESSING=true uvicorn claimlens_api.main:app --reload --port 8000

worker:
	claimlens worker

web-install:
	cd apps/web && npm ci

web-build:
	cd apps/web && npm run lint && npm test && npm run build

bicep:
	bicep build infra/main.bicep --stdout > /dev/null && bicep lint infra/main.bicep

all: lint typecheck test web-build bicep
