.PHONY: test test-trade test-agent test-analytics test-supply test-integration
.PHONY: dev up down logs lint
.PHONY: mcp-server test-mcp

# ─── 测试 ───

test: test-trade test-agent test-analytics test-supply test-menu test-ops test-member test-finance test-org test-mcp test-integration
	@echo "\n✓ All tests passed"

test-trade:
	@echo "=== tx-trade ==="
	@PYTHONPATH=. python3 -m pytest services/tx-trade/src/tests/ -q

test-agent:
	@echo "=== tx-agent ==="
	@cd services/tx-agent && python3 -m pytest src/tests/ -q

test-analytics:
	@echo "=== tx-analytics ==="
	@cd services/tx-analytics && PYTHONPATH=src:../../ python3 -m pytest src/tests/ -q

test-supply:
	@echo "=== tx-supply ==="
	@cd services/tx-supply && PYTHONPATH=src:../../ python3 -m pytest src/tests/ -q

test-menu:
	@echo "=== tx-menu ==="
	@cd services/tx-menu && PYTHONPATH=src:../../ python3 -m pytest src/tests/ -q

test-member:
	@echo "=== tx-member ==="
	@cd services/tx-member && PYTHONPATH=src:../../ python3 -m pytest src/tests/ -q

test-finance:
	@echo "=== tx-finance ==="
	@cd services/tx-finance && PYTHONPATH=src:../../ python3 -m pytest src/tests/ -q

test-org:
	@echo "=== tx-org ==="
	@cd services/tx-org && PYTHONPATH=src:../../ python3 -m pytest src/tests/ -q

test-ops:
	@echo "=== tx-ops ==="
	@cd services/tx-ops && python3 -m pytest src/tests/ -q

test-integration:
	@echo "=== integration ==="
	@python3 -m pytest tests/test_cross_domain_integration.py -q

# ─── Docker ───

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

up-prod:
	docker-compose -f docker-compose.prod.yml up -d

up-staging:
	docker-compose -f docker-compose.staging.yml --env-file .env.staging up -d

down-staging:
	docker-compose -f docker-compose.staging.yml down

logs-staging:
	docker-compose -f docker-compose.staging.yml logs -f

# ─── 开发 ───

dev-pos:
	cd apps/web-pos && pnpm dev

dev-admin:
	cd apps/web-admin && pnpm dev

dev-gateway:
	PYTHONPATH=. uvicorn services.gateway.src.main:app --reload --port 8000

dev-trade:
	PYTHONPATH=. uvicorn services.tx-trade.src.main:app --reload --port 8001

# ─── 代码质量 ───

lint:
	ruff check services/*/src/ edge/*/src/ shared/*/src/ --ignore E501

# ─── 数据库 ───

migrate-check:
	@./scripts/migrate.sh check

migrate-up:
	@./scripts/migrate.sh up --no-backup

migrate-up-safe:
	@./scripts/migrate.sh up

migrate-rollback:
	@./scripts/migrate.sh rollback

migrate-history:
	@./scripts/migrate.sh history

migrate-gen:
	cd shared/db-migrations && alembic revision --autogenerate -m "$(msg)"

# ─── 部署 ───

deploy-staging:
	@./scripts/deploy.sh staging

deploy-prod:
	@./scripts/deploy.sh prod

# ─── 新店上线 ───

new-store:
	./scripts/new_store_setup.sh $(ARGS)

# ─── Agent 验证 ───

verify-agents:
	@python3 scripts/verify_agents.py 2>&1 | grep -v "\[info\]"

smoke:
	@bash scripts/smoke_test.sh

# ─── 监控 ───

monitor:
	@./scripts/monitor.sh check

monitor-install:
	@./scripts/monitor.sh install

monitor-uninstall:
	@./scripts/monitor.sh uninstall

# ─── MCP Server ───

mcp-server:
	@echo "=== Starting MCP Server ==="
	@cd services/mcp-server && PYTHONPATH=src:../tx-agent/src python3 -m src.server

test-mcp:
	@echo "=== mcp-server ==="
	@cd services/mcp-server && PYTHONPATH=src:../tx-agent/src python3 -m pytest src/tests/ -q
