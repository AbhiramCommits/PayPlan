PYTHON ?= .venv/bin/python
MANAGE = $(PYTHON) backend/manage.py
COMPOSE = docker compose

.PHONY: help up down build migrate makemigrations seed test cov lint fmt simulate frontend-install lock

help:
	@echo "PayPlan targets: up down migrate seed test cov lint fmt simulate"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

build:
	$(COMPOSE) build

migrate:
	$(MANAGE) migrate

makemigrations:
	$(MANAGE) makemigrations

seed:
	$(MANAGE) seed_demo

test:
	$(PYTHON) -m pytest -q

cov:
	$(PYTHON) -m pytest -q --cov=apps --cov-report=term-missing --cov-report=xml:coverage.xml

lint:
	$(PYTHON) -m ruff check backend
	$(PYTHON) -m black --check backend

fmt:
	$(PYTHON) -m ruff check --fix backend
	$(PYTHON) -m black backend

simulate:
	$(MANAGE) simulate_portfolio --members 500 --days 120 --seed 42
