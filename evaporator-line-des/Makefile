# evaporator-line-des (v2) - reproducible pipeline (illustrative, anonymised data)
#   make all        full pipeline (300 replications), see README for runtime
#   make quick      same pipeline with 30 replications -> results/quick/
#   make dashboard  Streamlit app

PYTHON ?= python
export PYTHONPATH := $(CURDIR)/src
EVAPSIM = $(PYTHON) -m evapsim
Q = $(if $(QUICK),--quick,)

.PHONY: help setup lint test data handcalc analytic input baseline validate uncertainty \
        scenarios vsm sweep sensitivity report notebook dashboard all quick clean-quick

help:
	@echo "Targets: setup lint test data baseline scenarios sweep sensitivity report notebook dashboard all quick"

setup:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

lint:
	ruff check .

test:
	$(PYTHON) -m pytest

data:
	$(EVAPSIM) data

handcalc:
	$(EVAPSIM) handcalc
	$(EVAPSIM) analytic

input:
	$(EVAPSIM) input

# Phases 1-6: hand calculation, input analysis, baseline Monte Carlo, validation, two-level MC
baseline: handcalc input
	$(EVAPSIM) baseline $(Q)
	$(EVAPSIM) validate $(Q)
	$(EVAPSIM) uncertainty $(Q)

validate:
	$(EVAPSIM) validate $(Q)

uncertainty:
	$(EVAPSIM) uncertainty $(Q)

# Phases 7-8: scenarios S0-S7 at 3 and 5 EVA/week, then the VSM diagrams
scenarios:
	$(EVAPSIM) scenarios $(Q)
	$(EVAPSIM) vsm $(Q)

vsm:
	$(EVAPSIM) vsm $(Q)

sweep:
	$(EVAPSIM) sweep $(Q)

sensitivity:
	$(EVAPSIM) sensitivity $(Q)

report:
	$(EVAPSIM) report

notebook:
	$(PYTHON) -m jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=900 notebooks/analysis.ipynb

dashboard:
	streamlit run app/dashboard.py

all: setup lint test data baseline scenarios sweep sensitivity report notebook

quick:
	$(MAKE) lint test
	$(MAKE) baseline scenarios sweep sensitivity QUICK=1

clean-quick:
	rm -rf results/quick
