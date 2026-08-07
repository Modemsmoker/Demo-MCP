-include .env
export

.PHONY: help install lint fmt test check build up down restart logs ps watch shell health health-unauth health-github metrics dashboard token env register unregister clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime and dev dependencies locally
	pip install -r requirements.txt pytest pytest-asyncio ruff

lint: ## Static analysis and format check
	ruff check .
	ruff format --check .

fmt: ## Auto-format and auto-fix
	ruff format .
	ruff check --fix .

test: ## Run the test suite
	MCP_AUTH_TOKEN=test-token pytest

check: lint test ## Full verification gate; must pass before any commit

build: ## Build the image
	docker compose build

up: ## Build and start the container in the background
	docker compose up -d --build

down: ## Stop and remove the container
	docker compose down

restart: down up ## Restart the container

logs: ## Follow container logs
	docker compose logs -f demo-mcp

ps: ## Show container status
	docker compose ps

watch: ## Live-reload the server on source edits
	docker compose watch

shell: ## Open a shell in the running container
	docker compose exec demo-mcp /bin/bash

health: ## Smoke-check the MCP endpoint responds (with auth)
	curl -isS -X POST http://localhost:8000/mcp -H "Authorization: Bearer $(MCP_AUTH_TOKEN)"

health-unauth: ## Smoke-check the MCP endpoint without a token; expect 401
	curl -isS -X POST http://localhost:8000/mcp

health-github: ## Call github_repo_overview against a known public repo through the running container
	python3 scripts/health_github.py octocat/Hello-World

metrics: ## Print the current /metrics output
	curl -sS http://localhost:8000/metrics

dashboard: ## Print the Grafana dashboard URL
	@echo "http://localhost:3000"

token: ## Generate a value for MCP_AUTH_TOKEN in .env
	@openssl rand -hex 32

env: ## Create .env with a generated MCP_AUTH_TOKEN if one doesn't exist yet (used by CI)
	@test -f .env || { printf "MCP_AUTH_TOKEN=%s\n" "$$(openssl rand -hex 32)" > .env; echo "Wrote .env with a generated MCP_AUTH_TOKEN"; }

register: ## Register this server with the local Claude Code CLI
	@if [ -z "$(MCP_AUTH_TOKEN)" ]; then echo "MCP_AUTH_TOKEN is not set; run 'make token' and put it in .env" >&2; exit 1; fi
	claude mcp add --transport http demo-mcp http://localhost:8000/mcp \
	  --header "Authorization: Bearer $(MCP_AUTH_TOKEN)"

unregister: ## Remove this server from the local Claude Code CLI
	claude mcp remove demo-mcp

clean: ## Stop the container and remove volumes and local images
	docker compose down -v --rmi local
