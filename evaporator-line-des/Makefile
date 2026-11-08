# evaporator-line-des - reproducible pipeline
#   make all          full pipeline (500 replications per scenario, ~22 min on 4 cores)
#   make quick        same pipeline in quick mode (50 replications, ~5 min) -> results/quick/
#   make dashboard    launch the Streamlit app

PYTHON ?= python
export PYTHONPATH := $(CURDIR)/src
EVAPSIM = $(PYTHON) -m evapsim
QUICKFLAG = $(if $(QUICK),--quick,)

.PHONY: help setup lint test data input capacity baseline validate scenarios sensitivity \
        conwip vsm report notebook dashboard all quick clean-quick

help:
	@echo "Targets: setup lint test data baseline scenarios report notebook dashboard all quick"

setup:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

lint:
	ruff check .

test:
	$(PYTHON) -m pytest

data:
	$(EVAPSIM) data

input:
	$(EVAPSIM) input

capacity:
	$(EVAPSIM) capacity

# Phases 2, 4, 5, 6: input analysis, baseline Monte Carlo, convergence, validation
baseline: input capacity
	$(EVAPSIM) baseline $(QUICKFLAG)
	$(EVAPSIM) validate $(QUICKFLAG)

# Phases 7, 8: scenarios S0-S6, sensitivity, VSM diagrams
scenarios:
	$(EVAPSIM) scenarios $(QUICKFLAG)
	$(EVAPSIM) sensitivity $(QUICKFLAG)
	$(EVAPSIM) conwip $(QUICKFLAG)
	$(EVAPSIM) vsm $(QUICKFLAG)

validate:
	$(EVAPSIM) validate $(QUICKFLAG)

sensitivity:
	$(EVAPSIM) sensitivity $(QUICKFLAG)

conwip:
	$(EVAPSIM) conwip $(QUICKFLAG)

vsm:
	$(EVAPSIM) vsm $(QUICKFLAG)

# Regenerate the README result tables from results/*.csv
report:
	$(EVAPSIM) report

notebook:
	$(PYTHON) -m jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=900 notebooks/analysis.ipynb

dashboard:
	streamlit run app/dashboard.py

all: setup lint test data baseline scenarios report notebook

quick:
	$(MAKE) lint test
	$(MAKE) baseline scenarios QUICK=1

clean-quick:
	rm -rf results/quick
