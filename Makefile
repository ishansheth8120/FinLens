.DEFAULT_GOAL := help
SHELL := /bin/bash

VENV         ?= .venv
PY           := $(VENV)/bin/python
PIP          := $(VENV)/bin/pip
DBT          := $(CURDIR)/$(VENV)/bin/dbt
DBT_DIR      := finlens/warehouse
SPARK_MASTER ?= local[*]
DEMO_LIMIT   ?= 25

export FINLENS_DBT_DIR := $(CURDIR)/$(DBT_DIR)

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- setup -------------------------------------------------------------------

.PHONY: setup
setup: ## Create the venv and install everything needed for development
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e '.[all]'
	@echo
	@echo "done. Next: cp .env.example .env and set FINLENS_SEC_USER_AGENT"

.PHONY: setup-spark
setup-spark: ## Add PySpark (needs Java 11+)
	$(PIP) install --quiet -e '.[spark]'

.PHONY: setup-warehouse
setup-warehouse: ## Add dbt and install its packages
	$(PIP) install --quiet -e '.[warehouse]'
	cd $(DBT_DIR) && $(DBT) deps

# --- quality -----------------------------------------------------------------

.PHONY: test
test: ## Unit tests (no network, no JVM, no API key)
	$(VENV)/bin/pytest -m "not integration"

.PHONY: test-all
test-all: ## Every test, including integration
	$(VENV)/bin/pytest

.PHONY: lint
lint: ## Lint and format check
	$(VENV)/bin/ruff check finlens tests
	$(VENV)/bin/ruff format --check finlens tests

.PHONY: fmt
fmt: ## Format and autofix
	$(VENV)/bin/ruff format finlens tests
	$(VENV)/bin/ruff check --fix finlens tests

.PHONY: typecheck
typecheck: ## Type check
	$(VENV)/bin/mypy finlens

.PHONY: check
check: lint test ## Lint and test - what CI runs

# --- pipeline ----------------------------------------------------------------

.PHONY: scope
scope: ## Show the configured structured and text universes
	$(VENV)/bin/finlens-ingest scope

.PHONY: ingest
ingest: ## Land EDGAR data for both layers
	$(VENV)/bin/finlens-ingest structured --limit $(DEMO_LIMIT)
	$(VENV)/bin/finlens-ingest text

.PHONY: spark
spark: ## raw -> bronze -> silver (needs Java)
	$(PY) -m finlens.spark.jobs.bronze_submissions --master '$(SPARK_MASTER)'
	$(PY) -m finlens.spark.jobs.bronze_companyfacts --master '$(SPARK_MASTER)'
	$(PY) -m finlens.spark.jobs.silver_entities --master '$(SPARK_MASTER)'
	$(PY) -m finlens.spark.jobs.silver_facts --master '$(SPARK_MASTER)'
	$(PY) -m finlens.spark.jobs.silver_sections --master '$(SPARK_MASTER)'

.PHONY: warehouse
warehouse: ## Build the dbt marts, run their tests, refresh the manifest
	cd $(DBT_DIR) && $(DBT) seed
	cd $(DBT_DIR) && $(DBT) build
	# The manifest is what the text-to-SQL prompt reads column descriptions
	# from. Stale manifest, stale prompt, worse SQL.
	cd $(DBT_DIR) && $(DBT) docs generate

.PHONY: dbt-test
dbt-test: ## Warehouse data tests only
	cd $(DBT_DIR) && $(DBT) test

.PHONY: index
index: ## Chunk and embed filing text
	$(VENV)/bin/finlens-embed build --rebuild
	$(VENV)/bin/finlens-embed stats

.PHONY: demo
demo: ingest spark warehouse index ## Full pipeline over a small universe
	@echo
	@echo "ready. try:"
	@echo "  $(VENV)/bin/finlens-ask ask \"What was Apple's revenue in fiscal 2023?\""
	@echo "  make api    # then open http://localhost:8000/"

# --- serving -----------------------------------------------------------------

.PHONY: api
api: ## Run the API and UI with reload
	$(VENV)/bin/uvicorn finlens.api.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: eval
eval: ## Run the golden set (uses free-tier LLM quota)
	$(VENV)/bin/finlens-eval run

.PHONY: eval-quick
eval-quick: ## Run only the adversarial cases
	$(VENV)/bin/finlens-eval run --tags adversarial

# --- docker ------------------------------------------------------------------

.PHONY: docker-api
docker-api: ## Build and run the API container
	docker compose -f finlens/docker/docker-compose.yml up --build api

.PHONY: docker-pipeline
docker-pipeline: ## Bring up Spark and Airflow too
	docker compose -f finlens/docker/docker-compose.yml --profile pipeline up --build

.PHONY: docker-space
docker-space: ## Build the Hugging Face Spaces image
	docker build -f finlens/docker/Dockerfile.space -t finlens-space .

# --- housekeeping ------------------------------------------------------------

.PHONY: clean
clean: ## Remove derived data; keep the raw zone and the EDGAR cache
	rm -rf data/lake/curated data/warehouse data/index
	rm -rf $(DBT_DIR)/target $(DBT_DIR)/logs
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache

.PHONY: clean-all
clean-all: clean ## Also remove the raw zone, the cache and the venv
	rm -rf data $(VENV)
