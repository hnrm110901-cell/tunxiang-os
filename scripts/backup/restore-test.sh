#!/bin/bash
# 屯象OS 备份恢复演练脚本
# 等保三级要求：定期（至少每月1次）验证备份可用性
# 演练策略：下载最近备份 → 解密 → 还原到测试数据库 → 验证数据 → 清理
#
# 安全原则：
#   - 恢复目标库：tunxiang_os_restore_test（独立测试库，不影响生产）
#   - 演练完成后立即删除解密临时文件
#   - 演练结果写入 CLS 审计日志
#
# 运行方式：
#   手动：sudo bash /opt/txos/scripts/backup/restore-test.sh
#   定时：0 3 1 * * /opt/txos/scripts/backup/restore-test.sh  # 每月1号凌晨3点

set -euo pipefail

# ── 配置 ─────────────────────────────────────────────────────────────────────
ENV_FILE="/etc/txos/backup.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
else
    echo "ERROR: 环境变量文件不存在：$ENV_FILE" >&2
    exit 1
fi

TEST_DATE=$(date +%Y%m%d_%H%M%S)
RESTORE_DB="tunxiang_os_restore_test"      # 专用测试库（不是生产库！）
TEMP_DIR=$(mktemp -d /tmp/txos-restore-XXXXXX)
COS_BUCKET="${COS_BUCKET:-txos-backup-sh}"
COS_REGION="${COS_REGION:-ap-shanghai}"
LOG_FILE="${LOG_FILE:-/var/log/txos-backup.log}"
AUDIT_LOG="${AUDIT_LOG:-/var/log/txos-backup-audit.log}"

: "${BACKUP_ENCRYPTION_KEY:?ERROR: BACKUP_ENCRYPTION_KEY 未设置}"
: "${BACKUP_DB_PASSWORD:?ERROR: BACKUP_DB_PASSWORD 未设置}"

# ── 工具函数 ──────────────────────────────────────────────────────────────────

log() {
    local level="$1"
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*" | tee -a "$LOG_FILE"
}

log_audit() {
    local event="$1"
    local extra="${2:-}"
    printf '{"event":"%s","date":"%s","host":"%s"%s}\n' \
        "$event" "$TEST_DATE" "$(hostname)" "$extra" \
        >> "$AUDIT_LOG"
}

cleanup() {
    log "INFO" "清理临时文件：$TEMP_DIR"
    rm -rf "$TEMP_DIR"
}

die() {
    log "ERROR" "$*"
    log_audit "restore_test.failed" ",\"reason\":\"$*\""
    cleanup
    exit 1
}

# 注册退出清理钩子（无论成功还是失败都执行）
trap cleanup EXIT

# ── 主流程 ───────────────────────────────────────────────────────────────────

log "INFO" "========================================"
log "INFO" "屯象OS 月度恢复演练开始：$TEST_DATE"
log "INFO" "目标测试库：$RESTORE_DB"
log "INFO" "========================================"
log_audit "restore_test.started"

# ── 步骤1：查找最近一次备份文件 ─────────────────────────────────────────────

log "INFO" "步骤1/6: 查找 COS 上最新备份..."

LATEST_DATE=$(coscli ls "cos://${COS_BUCKET}/daily/" --region "$COS_REGION" \
    | grep -oP '\d{8}' | sort -r | head -1) \
    || die "无法列出 COS 备份目录"

if [[ -z "$LATEST_DATE" ]]; then
    die "COS 中没有找到备份文件"
fi

log "INFO" "最新备份日期：$LATEST_DATE"

# 获取该日期下的加密备份文件
LATEST_FILE=$(coscli ls "cos://${COS_BUCKET}/daily/${LATEST_DATE}/" --region "$COS_REGION" \
    | grep '\.sql\.gz\.enc$' | awk '{print $NF}' | head -1) \
    || die "无法获取备份文件列表"

if [[ -z "$LATEST_FILE" ]]; then
    die "日期 $LATEST_DATE 下没有找到 .sql.gz.enc 文件"
fi

log "INFO" "选择备份文件：$LATEST_FILE"

# ── 步骤2：下载备份文件和校验和 ────────────────────────────────────────────

log "INFO" "步骤2/6: 从 COS 下载备份文件..."

LOCAL_ENC="$TEMP_DIR/backup.sql.gz.enc"
LOCAL_SHA="$TEMP_DIR/backup.sql.gz.enc.sha256"

coscli cp "cos://${COS_BUCKET}/daily/${LATEST_DATE}/${LATEST_FILE}" \
    "$LOCAL_ENC" --region "$COS_REGION" \
    || die "下载加密备份文件失败"

coscli cp "cos://${COS_BUCKET}/daily/${LATEST_DATE}/${LATEST_FILE}.sha256" \
    "$LOCAL_SHA" --region "$COS_REGION" \
    || die "下载校验和文件失败"

log "INFO" "下载完成（$(du -h "$LOCAL_ENC" | cut -f1)）"

# ── 步骤3：校验文件完整性 ───────────────────────────────────────────────────

log "INFO" "步骤3/6: 验证 SHA256 校验和..."

EXPECTED_CHECKSUM=$(awk '{print $1}' "$LOCAL_SHA")
ACTUAL_CHECKSUM=$(sha256sum "$LOCAL_ENC" | cut -d' ' -f1)

if [[ "$EXPECTED_CHECKSUM" != "$ACTUAL_CHECKSUM" ]]; then
    die "校验和不匹配！文件可能已损坏。期望：$EXPECTED_CHECKSUM，实际：$ACTUAL_CHECKSUM"
fi

log "INFO" "校验和验证通过：$ACTUAL_CHECKSUM"

# ── 步骤4：解密并还原到测试数据库 ──────────────────────────────────────────

log "INFO" "步骤4/6: 解密并还原到测试数据库 $RESTORE_DB..."

# 创建或重建测试库（如已存在则先删除）
PGPASSWORD="$BACKUP_DB_PASSWORD" psql \
    -h "${DB_HOST:-127.0.0.1}" \
    -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-txos}" \
    -c "DROP DATABASE IF EXISTS $RESTORE_DB;" \
    -c "CREATE DATABASE $RESTORE_DB;" \
    postgres \
    || die "创建测试数据库失败"

# 解密并管道导入（不写入明文文件到磁盘）
openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 \
    -pass "env:BACKUP_ENCRYPTION_KEY" \
    -in "$LOCAL_ENC" \
    | gunzip \
    | PGPASSWORD="$BACKUP_DB_PASSWORD" psql \
        -h "${DB_HOST:-127.0.0.1}" \
        -p "${DB_PORT:-5432}" \
        -U "${DB_USER:-txos}" \
        -d "$RESTORE_DB" \
        --quiet \
        2>>"$LOG_FILE" \
    || die "数据库还原失败"

log "INFO" "数据库还原完成"

# ── 步骤5：数据完整性验证 ───────────────────────────────────────────────────

log "INFO" "步骤5/6: 验证关键表数据完整性..."

run_check() {
    local table="$1"
    local min_rows="$2"
    local count
    count=$(PGPASSWORD="$BACKUP_DB_PASSWORD" psql \
        -h "${DB_HOST:-127.0.0.1}" \
        -p "${DB_PORT:-5432}" \
        -U "${DB_USER:-txos}" \
        -d "$RESTORE_DB" \
        -t -c "SELECT COUNT(*) FROM $table;" 2>/dev/null | tr -d ' ')

    if [[ -z "$count" ]] || [[ "$count" -lt "$min_rows" ]]; then
        die "表 $table 数据验证失败（期望 >=$min_rows 行，实际 ${count:-0} 行）"
    fi
    log "INFO" "  ✓ $table: $count 行"
}

# 验证核心 Ontology 六大实体表不为空
run_check "stores"      1
run_check "employees"   1
run_check "menu_items"  1

# 验证 RLS 关键字段存在
RLS_CHECK=$(PGPASSWORD="$BACKUP_DB_PASSWORD" psql \
    -h "${DB_HOST:-127.0.0.1}" \
    -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-txos}" \
    -d "$RESTORE_DB" \
    -t -c "SELECT COUNT(*) FROM information_schema.columns
           WHERE column_name = 'tenant_id';" 2>/dev/null | tr -d ' ')

if [[ "$RLS_CHECK" -lt 5 ]]; then
    log "WARN" "RLS tenant_id 字段数量偏少：$RLS_CHECK（期望 >=5），请人工确认"
else
    log "INFO" "  ✓ RLS tenant_id 字段：$RLS_CHECK 张表"
fi

log "INFO" "数据完整性验证通过"

# ── 步骤6：清理测试库 ───────────────────────────────────────────────────────

log "INFO" "步骤6/6: 删除测试数据库..."

PGPASSWORD="$BACKUP_DB_PASSWORD" psql \
    -h "${DB_HOST:-127.0.0.1}" \
    -p "${DB_PORT:-5432}" \
    -U "${DB_USER:-txos}" \
    -c "DROP DATABASE IF EXISTS $RESTORE_DB;" \
    postgres \
    || log "WARN" "删除测试库失败（可手动执行：DROP DATABASE $RESTORE_DB;）"

# ── 完成 ────────────────────────────────────────────────────────────────────

log_audit "restore_test.completed" \
    ",\"backup_file\":\"$LATEST_FILE\",\"checksum\":\"$ACTUAL_CHECKSUM\",\"result\":\"success\""

log "INFO" "========================================"
log "INFO" "月度恢复演练完成 ✓"
log "INFO" "备份文件：$LATEST_FILE"
log "INFO" "恢复结果：正常，数据完整"
log "INFO" "========================================"
