# 集成测试框架

连接真实 PostgreSQL 的集成测试。

## 前提条件

1. Docker（运行测试数据库）
2. Python 3.10+（测试代码使用 PEP 604 类型注解）

## 快速开始

```bash
# 1. 启动测试数据库
docker compose -f infra/docker/docker-compose.integration-test.yml up -d

# 2. 运行 Alembic 迁移（首次使用）
DATABASE_URL="postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test" \
  alembic -c shared/db-migrations/alembic.ini upgrade head

# 3. 运行集成测试
INTEGRATION_DATABASE_URL="postgresql+asyncpg://tunxiang:changeme_test@localhost:15432/tunxiang_os_test" \
  pytest tests/integration/ -v -m integration
```

## 测试策略

| 测试类型 | 位置 | 数据库 | 速度 |
|---------|------|--------|------|
| 单元测试 | `services/*/tests/` | Mock (AsyncMock) | 毫秒级 |
| 集成测试 | `tests/integration/` | 真实 PostgreSQL | 秒级 |

## 编写新集成测试

```python
@pytest.mark.integration
async def test_my_feature(transaction: AsyncConnection):
    # transaction 是独立事务，测试结束时 ROLLBACK
    await transaction.execute(text("..."))
    result = (await transaction.execute(text("..."))).fetchone()
    assert result is not None
```

## 注意

- 测试数据库数据不持久化（使用 `tmpfs`）
- 每个测试在独立事务中运行，自动回滚
- 并发测试需每个 worker 独立的数据库 schema
