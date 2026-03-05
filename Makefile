.DEFAULT_GOAL := help
.PHONY: help install build test lint up down reset logs shell seed dev demo

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
	@echo "  make seed        Generate and load all sample data"
	@echo ""
	@echo "$(CYAN)Development$(RESET)"
	@echo "  make up          Build and start Docker services"
	@echo "  make dev         Start dashboard dev server (:5173)"
	@echo "  make demo        Full demo: up + seed (one command)"
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

dev:
	cd apps/dashboard && pnpm dev

demo: up
	@echo "Waiting for API to be ready..."
	@sleep 3
	cd services/api && python scripts/seed_data.py
	cd services/api && python scripts/reset_demo.py
	@echo ""
	@echo "$(BOLD)Demo ready!$(RESET)"
	@echo "  API      → http://localhost:8000"
	@echo "  Dashboard → run 'make dev' in another terminal"
	@echo ""
	@echo "Tokens: admin-token · analyst-token · viewer-token"

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
