# Thin wrapper over scripts/pipeline.py, which also works on Windows without make.
PY ?= python
RUN = $(PY) scripts/pipeline.py
DBT = cd dbt_finance && DBT_PROFILES_DIR=. dbt

.PHONY: setup up down seed advance ingest load transform reconcile quality publish test lint docs \
        dashboard demo incremental reset benchmark backfill close-period

setup:        ; $(RUN) setup
up:           ; $(RUN) up
down:         ; $(RUN) down
seed:         ; $(RUN) seed
advance:      ; $(RUN) advance
ingest:       ; $(RUN) ingest
load:         ; $(RUN) load
transform:    ; $(RUN) transform
reconcile:    ; $(DBT) build --select intermediate.reconciliation+ mart_intercompany_reconciliation mart_bank_reconciliation
quality:      ; $(DBT) test && $(DBT) source freshness
publish:      ; $(RUN) publish
test:         ; $(RUN) test
lint:         ; $(RUN) lint
docs:         ; $(RUN) docs
dashboard:    ; $(RUN) dashboard
demo:         ; $(RUN) demo
incremental:  ; $(RUN) incremental
benchmark:    ; $(PY) benchmarks/run_benchmarks.py
backfill:     ; $(DBT) build --select fact_general_ledger+ --full-refresh
close-period: ; $(DBT) build --select mart_financial_close+ && cd .. && $(RUN) publish

# DESTRUCTIVE - deletes local pipeline state. Requires explicit confirmation: make reset CONFIRM=yes
reset:
	@if [ "$(CONFIRM)" != "yes" ]; then echo "Refusing: run 'make reset CONFIRM=yes' to delete local state"; exit 1; fi
	$(RUN) reset --yes
