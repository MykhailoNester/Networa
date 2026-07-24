# Local quality gate. `make check-all` is the same gate CI runs.
# Activate the virtualenv (.venv) before running these targets.

.PHONY: install install-dev seed-demo format lint typecheck test check-all

install:
	pip install -r requirements.txt

install-dev: install
	pip install -r requirements-dev.txt

# (Re)build the synthetic demo database at data/demo.db.
seed-demo:
	python scripts/seed_demo.py

# Auto-format the codebase.
format:
	ruff format .

# Formatting + lint checks (no changes made).
lint:
	ruff format --check .
	ruff check .

# Static type checking.
typecheck:
	mypy app/

# Test suite.
test:
	pytest -q

# Full gate: lint + types + tests. Run this before opening a PR.
check-all: lint typecheck test
	@echo "All checks passed."
