# One-command workflow. Run `make help` to list targets.
PYTHON ?= python

.PHONY: help install build check export insights model powerbi web serve e2e screenshots all test lint format clean

help:  ## List available targets
	@grep -E '^[a-z0-9]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-12s %s\n", $$1, $$2}'

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

powerbi:  ## Generate the Power BI project (powerbi/*.pbip) and its data files
	$(PYTHON) -m spotify_pipeline powerbi

web:  ## Export the warehouse for the web dashboard (site/data) and copy the figures
	$(PYTHON) -m spotify_pipeline web

serve:  ## Serve the web dashboard at http://localhost:8000
	$(PYTHON) -m http.server --directory site 8000

e2e:  ## Click through every dashboard page in Chromium and check every number with SQL
	$(PYTHON) -m pytest tests/test_web_e2e.py -v

screenshots:  ## Capture README screenshots of the web dashboard (needs `make serve` running)
	node site/tests/screenshots.cjs http://localhost:8000/ screenshots/web

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
