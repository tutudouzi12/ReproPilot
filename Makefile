# ReproPilot Python development helpers

.PHONY: help install lint build test coverage evaluation-scenarios run-backend run-frontend run-sandbox docker-up docker-down clean

help:
	@echo "ReproPilot Python commands:"
	@echo "  make install       - Install Python and frontend dependencies"
	@echo "  make lint          - Run frontend lint"
	@echo "  make build         - Build frontend and compile Python modules"
	@echo "  make test          - Run backend and sandbox Python tests"
	@echo "  make coverage      - Measure backend and sandbox branch coverage"
	@echo "  make evaluation-scenarios - Run fixed AutoResearch governance scenarios"
	@echo "  make run-backend   - Start FastAPI backend"
	@echo "  make run-sandbox   - Start Python Docker sandbox"
	@echo "  make run-frontend  - Start React frontend"

install:
	python3 -m pip install -e './backend[dev]'
	python3 -m pip install -e './docker-sandbox[dev]'
	cd frontend && npm install

lint:
	cd frontend && npm run lint

build:
	cd frontend && npm run build
	cd backend && python3 -m compileall -q app
	cd docker-sandbox && python3 -m compileall -q app

test:
	cd backend && python3 -m pytest -q
	cd docker-sandbox && python3 -m pytest -q

coverage:
	cd backend && python3 -m pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
	python3 scripts/coverage_summary.py Backend backend/coverage.json --min-line 83 --min-branch 68
	cd docker-sandbox && python3 -m pytest -q --cov=app --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
	python3 scripts/coverage_summary.py Sandbox docker-sandbox/coverage.json --min-line 88 --min-branch 80

evaluation-scenarios:
	python3 scripts/run_evaluation_scenarios.py --mode scripted

run-sandbox:
	./scripts/unix/start-sandbox.sh

run-backend:
	./scripts/unix/start-backend.sh

run-frontend:
	./scripts/unix/start-frontend.sh

docker-up:
	./scripts/unix/docker-up.sh

docker-down:
	./scripts/unix/docker-down.sh

clean:
	rm -rf frontend/dist backend/.pytest_cache docker-sandbox/.pytest_cache
