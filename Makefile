.PHONY: help build up down restart logs ps watch shell health register unregister clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

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

health: ## Smoke-check the MCP endpoint responds
	curl -isS -X POST http://localhost:8000/mcp

register: ## Register this server with the local Claude Code CLI
	claude mcp add --transport http demo-mcp http://localhost:8000/mcp

unregister: ## Remove this server from the local Claude Code CLI
	claude mcp remove demo-mcp

clean: ## Stop the container and remove volumes and local images
	docker compose down -v --rmi local
