#!/usr/bin/env bash
# Tier 1 测试 Docker 跑测器（PD.2）
#
# 背景：本机 macOS 默认 Python 3.9，部分 Tier 1 测试需要 Python 3.11+
#       （pytest-asyncio 1.x、structlog、sqlalchemy 2.0 等依赖最低 3.10/3.11）。
#       此脚本用 python:3.11-slim 容器 + 最小依赖跑全套 Tier 1，
#       不污染本机环境，3-5 分钟内完整跑完。
#
# 用法：
#   ./scripts/run_tier1_tests.sh                  # 跑全部 Tier 1 文件名约定
#   ./scripts/run_tier1_tests.sh points           # 只跑包含 'points' 的文件
#   ./scripts/run_tier1_tests.sh -k test_consume  # 透传 pytest -k 表达式
#
# 退出码：
#   0 — 全部通过
#   1 — 至少一项失败
#   2 — Docker 不可用
#
# 已知通过的 Tier 1 模块（725/725，2026-05-05 第二批基线扩展后）：
#
#   第一批（115）：
#     tx-member  test_points_tier1                  29
#     tx-trade   test_order_state_machine_tier1     17
#     tx-trade   test_payment_saga_tier1             9
#     tx-trade   test_wine_storage_tier1             7
#     tx-trade   test_rls_isolation_tier1            5
#     tx-org     test_royalty_calculator_tier1      13
#     tx-finance test_invoice_tier1                 12
#     edge       test_offline_sync_crdt             23
#
#   第二批 tx-finance 凭证体系（289）：
#     accounting_periods 50 / erp_push_log_rls 12 / financial_voucher_lines 20 /
#     financial_voucher_service 37 / financial_vouchers_idempotency_void 24 /
#     financial_vouchers 22 / prior_period_adjustment 20 / red_flush 46 /
#     voucher_backfill 20 / voucher_generator_persist 20 / voucher_period_check 18
#
#   第二批 tx-trade 安全/审计/缓冲/多租户（315）：
#     alembic_chain_known_broken 11 / api_idempotency 17 / audit_outbox_flusher 17 /
#     audit_outbox 14 / banquet_lead 10 / codemod_tzinfo_residue 7 /
#     franchise_backfill 35 / high_value_mfa 15 / kds_delta 9 /
#     mark_offline_scheduler 3 / no_sql_fstring_regression 4 / no_utcnow_regression 5 /
#     offline_order_id 14 / rbac_audit_deny 18 / rbac_dev_bypass_prod_guard 27 /
#     rbac 12 / route_mfa_enforcement 13 / saga_buffer 11 / trade_audit_cross_tenant 11 /
#     v395_delivery_dispatches_rls 13 / v396_concurrently_pj2 6 /
#     v396_franchise_last_event_id 36 / invoice 2 / pos_integration 5
#
#   第二批 tx-member / tx-org / tx-ops（30）：
#     customer_lifecycle 14 / sales_target 12 / telemetry 4
#
# 跑通基线 = 115（第一批） + 610（第二批） = 725 / 725
#
# 未跑通（4 文件）— 依赖 fastapi.testclient / 真实 PG 等更重依赖，
# 留单独 PR 用 docker-compose 起 PG 容器配合：
#   tx-org   test_task_engine_tier1
#   tx-trade test_orders_idempotency_wiring_tier1
#   tx-trade test_sync_pull_cursor_pj1_tier1
#   tx-trade test_sync_pull_tier1

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="python:3.11-slim"
DEPS="pytest pytest-asyncio structlog sqlalchemy fastapi pydantic httpx pyyaml aiosqlite asyncpg"

# 测试参数（默认全套 Tier 1，可被 $1 覆盖为子集模式）
PYTEST_ARGS=()
if [ $# -gt 0 ]; then
    case "$1" in
        -k|-m|-x|-v|--tb|-q)
            # 透传 pytest 参数
            PYTEST_ARGS=("$@")
            ;;
        *)
            # 子集模式：$1 是文件名关键词
            FILTER="$1"
            shift
            mapfile -t TEST_FILES < <(find "$REPO_ROOT/services" "$REPO_ROOT/edge" \
                -name "*tier1*.py" -o -name "*${FILTER}*tier1*.py" 2>/dev/null \
                | grep "$FILTER" | sed "s|$REPO_ROOT/||")
            if [ ${#TEST_FILES[@]} -eq 0 ]; then
                echo "::error::No Tier 1 test files matched filter: $FILTER"
                exit 1
            fi
            PYTEST_ARGS=("${TEST_FILES[@]}" "$@")
            ;;
    esac
fi

# Tier 1 默认文件集（一次性跑完）
if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_ARGS=(
        # 第一批基线（PD.2 第一会话，115 测试）
        "services/tx-member/src/tests/test_points_tier1.py"                                  # 29
        "services/tx-trade/tests/test_order_state_machine_tier1.py"                           # 17
        "services/tx-trade/tests/test_payment_saga_tier1.py"                                  # 9
        "services/tx-trade/tests/test_wine_storage_tier1.py"                                  # 7
        "services/tx-trade/tests/test_rls_isolation_tier1.py"                                 # 5
        "services/tx-org/src/tests/test_royalty_calculator_tier1.py"                          # 13
        "services/tx-finance/tests/test_invoice_tier1.py"                                     # 12
        "edge/sync-engine/tests/test_offline_sync_crdt.py"                                    # 23
        # 第二批基线扩展（PD.2 续作，610 测试）— tx-finance 凭证体系
        "services/tx-finance/src/tests/test_accounting_periods_tier1.py"                      # 50
        "services/tx-finance/src/tests/test_erp_push_log_rls_tier1.py"                        # 12
        "services/tx-finance/src/tests/test_financial_voucher_lines_tier1.py"                 # 20
        "services/tx-finance/src/tests/test_financial_voucher_service_tier1.py"               # 37
        "services/tx-finance/src/tests/test_financial_vouchers_idempotency_void_tier1.py"     # 24
        "services/tx-finance/src/tests/test_financial_vouchers_tier1.py"                      # 22
        "services/tx-finance/src/tests/test_prior_period_adjustment_tier1.py"                 # 20
        "services/tx-finance/src/tests/test_red_flush_tier1.py"                               # 46
        "services/tx-finance/src/tests/test_voucher_backfill_tier1.py"                        # 20
        "services/tx-finance/src/tests/test_voucher_generator_persist_tier1.py"               # 20
        "services/tx-finance/src/tests/test_voucher_period_check_tier1.py"                    # 18
        # 第二批基线扩展 — tx-trade 安全/审计/缓冲/多租户
        "services/tx-trade/src/tests/test_alembic_chain_known_broken_scope_pj5_tier1.py"      # 11
        "services/tx-trade/src/tests/test_api_idempotency_tier1.py"                            # 17
        "services/tx-trade/src/tests/test_audit_outbox_flusher_tier1.py"                       # 17
        "services/tx-trade/src/tests/test_audit_outbox_tier1.py"                               # 14
        "services/tx-trade/src/tests/test_banquet_lead_tier1.py"                               # 10
        "services/tx-trade/src/tests/test_codemod_tzinfo_residue_pj3_tier1.py"                 # 7
        "services/tx-trade/src/tests/test_franchise_backfill_tier1.py"                         # 35
        "services/tx-trade/src/tests/test_high_value_mfa_threshold_tier1.py"                   # 15
        "services/tx-trade/src/tests/test_kds_delta_tier1.py"                                  # 9
        "services/tx-trade/src/tests/test_mark_offline_scheduler_tier1.py"                     # 3
        "services/tx-trade/src/tests/test_no_sql_fstring_regression_tier1.py"                  # 4
        "services/tx-trade/src/tests/test_no_utcnow_regression_tier1.py"                       # 5
        "services/tx-trade/src/tests/test_offline_order_id_tier1.py"                           # 14
        "services/tx-trade/src/tests/test_rbac_audit_deny_tier1.py"                            # 18
        "services/tx-trade/src/tests/test_rbac_dev_bypass_prod_guard_tier1.py"                 # 27
        "services/tx-trade/src/tests/test_rbac_tier1.py"                                       # 12
        "services/tx-trade/src/tests/test_route_mfa_enforcement_tier1.py"                      # 13
        "services/tx-trade/src/tests/test_saga_buffer_tier1.py"                                # 11
        "services/tx-trade/src/tests/test_trade_audit_cross_tenant_tier1.py"                   # 11
        "services/tx-trade/src/tests/test_v395_delivery_dispatches_rls_tier1.py"               # 13
        "services/tx-trade/src/tests/test_v396_concurrently_pj2_tier1.py"                      # 6
        "services/tx-trade/src/tests/test_v396_franchise_last_event_id_tier1.py"               # 36
        "services/tx-trade/tests/test_invoice_tier1.py"                                        # 2
        "services/tx-trade/tests/test_pos_integration_tier1.py"                                # 5
        # 第二批基线扩展 — tx-member / tx-org / tx-ops
        "services/tx-member/src/tests/test_customer_lifecycle_tier1.py"                        # 14
        "services/tx-org/src/tests/test_sales_target_tier1.py"                                 # 12
        "services/tx-ops/src/tests/test_telemetry_tier1.py"                                    # 4
    )
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "::error::Docker 未安装。Tier 1 测试需要 Python 3.11+，本机 Python 3.9 不兼容。"
    exit 2
fi

echo "=== Tier 1 Docker Runner ==="
echo "Image:  $IMAGE"
echo "Deps:   $DEPS"
echo "Tests:  ${#PYTEST_ARGS[@]} target(s)"
echo ""

# 透传模式（-k/-m/...）：单容器跑（用户已显式控制范围）
case "${1:-}" in
    -k|-m|-x|-v|--tb|-q)
        exec docker run --rm -v "$REPO_ROOT:/app" -w /app "$IMAGE" \
            bash -c "pip install --quiet $DEPS && python -m pytest ${PYTEST_ARGS[*]} --tb=short"
        ;;
esac

# 默认 / 子集模式：逐文件 docker run（避免跨文件 sys.path 污染）
# 不同 service 的 test 文件用 sys.path.insert 把各自 src/ 加到 path 头部，
# 同进程跑时第一个 service 的 src/ 会 shadow 掉后续 service 的同名模块（namespace 包）
TOTAL=0
PASS=0
FAIL_FILES=()
for test_file in "${PYTEST_ARGS[@]}"; do
    echo "--- $test_file ---"
    if docker run --rm -v "$REPO_ROOT:/app" -w /app "$IMAGE" \
        bash -c "set -o pipefail; pip install --quiet $DEPS 2>/dev/null && python -m pytest '$test_file' --tb=line -q 2>&1 | tail -5"; then
        PASS=$((PASS + 1))
    else
        FAIL_FILES+=("$test_file")
    fi
    TOTAL=$((TOTAL + 1))
    echo ""
done

echo "=== Summary ==="
echo "Passed:  $PASS / $TOTAL"
if [ ${#FAIL_FILES[@]} -gt 0 ]; then
    echo "Failed:"
    printf '  - %s\n' "${FAIL_FILES[@]}"
    exit 1
fi
echo "All Tier 1 files passed."
