.PHONY: test test-trade test-agent test-analytics test-supply test-integration
.PHONY: dev up down logs lint

# ─── 测试 ───

test: test-trade test-agent test-analytics test-supply test-integration
	@echo "\n✓ All tests passed"

test-trade:
	@echo "=== tx-trade ==="
	@PYTHONPATH=. python3 -m pytest services/tx-trade/src/tests/ -q

test-agent:
	@echo "=== tx-agent ==="
	@cd services/tx-agent && python3 -m pytest src/tests/ -q

test-analytics:
	@echo "=== tx-analytics ==="
	@cd services/tx-analytics && python3 -m pytest src/tests/ -q

test-supply:
	@echo "=== tx-supply ==="
	@cd services/tx-supply && python3 -m pytest src/tests/ -q

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

migrate-up:
	cd shared/db-migrations && alembic upgrade head

migrate-gen:
	cd shared/db-migrations && alembic revision --autogenerate -m "$(msg)"

# ─── 新店上线 ───

new-store:
	./scripts/new_store_setup.sh $(ARGS)

# ─── Agent 验证 ───

verify-agents:
	@cd services/tx-agent/src && python3 -c "\
	import sys; sys.path.insert(0, '.'); \
	from agents.skills import ALL_SKILL_AGENTS; \
	import asyncio; \
	total=0; ok=0; \
	for cls in ALL_SKILL_AGENTS: \
	    a=cls(tenant_id='test'); \
	    for act in a.get_supported_actions(): \
	        r=asyncio.run(a.execute(act, {})); \
	        total+=1; ok+=1 if r.success or 'Unsupported' not in (r.error or '') else 0; \
	print(f'Agent actions: {ok}/{total} ({round(ok/total*100)}%)'); \
	"
