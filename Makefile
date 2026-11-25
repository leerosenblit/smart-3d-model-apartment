# Convenience targets (on Windows without make, use ./dev.sh in Git Bash or .\dev.ps1)
PY ?= $(shell test -x backend/.venv/Scripts/python.exe && echo backend/.venv/Scripts/python.exe || echo backend/.venv/bin/python)

.PHONY: install dev test build seed
install:
	python3 -m venv backend/.venv || py -3.12 -m venv backend/.venv
	$(PY) -m pip install -r backend/requirements.txt
	cd frontend && npm install

dev:
	./dev.sh

test:
	cd backend && ../$(PY) -m pytest -q

build:
	cd frontend && npm run build

seed:
	cd backend && ../$(PY) -m scripts.seed
