.PHONY: help init up down logs ps restart migrate revision seed test test-be test-fe lint fmt shell psql redis clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

init: ## Create .env from the template and generate real secrets
	@test -f .env && echo ".env already exists — not overwriting." && exit 0 || true
	@cp .env.example .env
	@python3 - <<'PY'
import re, secrets, pathlib
from base64 import urlsafe_b64encode
p = pathlib.Path(".env"); t = p.read_text()
vals = {
    "JWT_SECRET": secrets.token_hex(32),
    "CREDENTIAL_ENCRYPTION_KEY": urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    "INTERNAL_SERVICE_TOKEN": secrets.token_hex(32),
    "N8N_ENCRYPTION_KEY": secrets.token_hex(32),
    "POSTGRES_PASSWORD": secrets.token_hex(16),
}
for k, v in vals.items():
    t = re.sub(rf"^{k}=.*$", f"{k}={v}", t, flags=re.M)
t = t.replace("postgresql+asyncpg://omni:change_me_locally@", f"postgresql+asyncpg://omni:{vals['POSTGRES_PASSWORD']}@")
p.write_text(t)
print("Wrote .env with freshly generated secrets. Add your OPENAI_API_KEY next.")
PY

up: ## Start the whole stack
	docker compose up -d --build
	@echo "Dashboard  http://localhost:8080"
	@echo "API docs   http://localhost:8000/docs"
	@echo "n8n        http://localhost:5678"

down: ## Stop the stack (volumes preserved)
	docker compose down

logs: ## Tail logs (make logs s=backend)
	docker compose logs -f $(s)

ps:
	docker compose ps

restart:
	docker compose restart $(s)

migrate: ## Apply database migrations
	docker compose exec backend alembic upgrade head

revision: ## Autogenerate a migration (make revision m="add leads")
	docker compose exec backend alembic revision --autogenerate -m "$(m)"

seed: ## Load demo organization, users and conversations
	docker compose exec backend python -m app.cli seed

test: test-be test-fe

test-be:
	docker compose exec backend pytest -q

test-fe:
	docker compose exec frontend npm run test -- --run

lint:
	docker compose exec backend ruff check app tests
	docker compose exec frontend npm run lint

fmt:
	docker compose exec backend ruff format app tests

shell:
	docker compose exec backend bash

psql:
	docker compose exec postgres psql -U omni -d omni

redis:
	docker compose exec redis redis-cli

clean: ## Stop and DELETE all data volumes
	docker compose down -v
