# One-command workflow. Run `make help` to list targets.
PYTHON ?= python

.PHONY: help install build check export insights model all test lint format clean

help:  ## List available targets
	@grep -E '^[a-z]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-9s %s\n", $$1, $$2}'

install:  ## Install the pipeline and dev tools in editable mode
	$(PYTHON) -m pip install -e ".[dev,analysis,ml]"

build:  ## Run the ELT: bronze -> silver -> gold
	$(PYTHON) -m spotify_pipeline build

check:  ## Run the data-quality suite and regenerate docs/data_quality_report.md
	$(PYTHON) -m spotify_pipeline check

export:  ## Write gold tables to exports/ as Parquet and CSV
	$(PYTHON) -m spotify_pipeline export

insights:  ## Run the analyses and regenerate docs/insights.md and docs/figures/
	$(PYTHON) -m spotify_pipeline insights

model:  ## Survival analysis + longevity model; regenerates docs/model_report.md
	$(PYTHON) -m spotify_pipeline model

all:  ## build + check + export
	$(PYTHON) -m spotify_pipeline all

test:  ## Run unit and integration tests
	$(PYTHON) -m pytest

lint:  ## Lint with ruff
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format:  ## Auto-format with ruff
	$(PYTHON) -m ruff format src tests
	$(PYTHON) -m ruff check --fix src tests

clean:  ## Remove the warehouse and exports
	rm -rf warehouse exports
