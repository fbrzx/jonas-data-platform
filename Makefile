.DEFAULT_GOAL := help
.PHONY: help install build test lint up down reset logs shell seed

# ── Colours ──────────────────────────────────────────────────────────────────
BOLD  := $(shell tput bold 2>/dev/null)
RESET := $(shell tput sgr0 2>/dev/null)
CYAN  := $(shell tput setaf 6 2>/dev/null)

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "$(BOLD)Jonas Data Platform$(RESET)"
	@echo ""
	@echo "$(CYAN)Setup$(RESET)"
	@echo "  make install     Install all dependencies (pnpm + pip)"
	@echo "  make seed        Generate sample data files"
	@echo ""
	@echo "$(CYAN)Development$(RESET)"
	@echo "  make up          Build and start Docker services"
	@echo "  make down        Stop Docker services"
	@echo "  make reset       Wipe data volumes and restart fresh"
	@echo "  make logs        Tail API container logs"
	@echo "  make shell       Open a shell in the API container"
	@echo ""
	@echo "$(CYAN)Quality$(RESET)"
	@echo "  make build       TypeScript compile + Vite production build"
	@echo "  make test        Run Python tests"
	@echo "  make lint        Run ruff (Python) + eslint (TypeScript)"
	@echo ""

# ── Setup ─────────────────────────────────────────────────────────────────────
install:
	pnpm install
	cd services/api && pip install -e ".[dev]" -q

seed:
	cd services/api && python scripts/seed_data.py
	cd services/api && python scripts/reset_demo.py

# ── Docker ────────────────────────────────────────────────────────────────────
up:
	docker compose up --build -d
	@echo "$(BOLD)API$(RESET) → http://localhost:8000/health"
	@echo "$(BOLD)Dashboard$(RESET) → run 'make dev' in apps/dashboard"

down:
	docker compose down

reset:
	docker compose down -v
	rm -rf data/db data/parquet
	mkdir -p data/db data/parquet
	docker compose up --build -d
	@echo "$(BOLD)Reset complete.$(RESET) Data volumes wiped and services restarted."

logs:
	docker compose logs -f api

shell:
	docker compose exec api /bin/sh

# ── Build / Quality ───────────────────────────────────────────────────────────
build:
	cd apps/dashboard && pnpm run build

test:
	cd services/api && python -m pytest

lint:
	cd services/api && python -m ruff check src
	cd apps/dashboard && pnpm run lint
