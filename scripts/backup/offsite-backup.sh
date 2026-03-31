#!/bin/bash
# 屯象OS 异地备份脚本
# 腾讯云广州（生产） → 上海（COS）跨地域备份
# 等保三级要求：关键数据异地备份，加密存储
#
# 依赖：postgresql-client / openssl / coscli
# 配置：/etc/txos/backup.env（见 README.md）
# Crontab：0 2 * * * /opt/txos/scripts/backup/offsite-backup.sh
#          每天凌晨 2:00 执行（业务低峰期）

set -euo pipefail

# ── 配置 ─────────────────────────────────────────────────────────────────────
# 从环境变量文件加载（禁止硬编码敏感信息，符合 CLAUDE.md 规范）
ENV_FILE="/etc/txos/backup.env"
if [[ -f "$ENV_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENV_FILE"
else
    echo "ERROR: 环境变量文件不存在：$ENV_FILE" >&2
    exit 1
fi

BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DATE_SHORT=$(date +%Y%m%d)
BACKUP_DIR="${BACKUP_DIR:-/opt/backups/txos}"
DB_NAME="${DB_NAME:-tunxiang_os}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-5432}"
DB_USER="${DB_USER:-txos}"
COS_BUCKET="${COS_BUCKET:-txos-backup-sh}"
COS_REGION="${COS_REGION:-ap-shanghai}"
LOG_FILE="${LOG_FILE:-/var/log/txos-backup.log}"
AUDIT_LOG="${AUDIT_LOG:-/var/log/txos-backup-audit.log}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"

# 必须环境变量检查
: "${BACKUP_ENCRYPTION_KEY:?ERROR: BACKUP_ENCRYPTION_KEY 未设置}"
: "${BACKUP_DB_PASSWORD:?ERROR: BACKUP_DB_PASSWORD 未设置}"

# ── 工具函数 ──────────────────────────────────────────────────────────────────

log() {
    local level="$1"
    shift
    local msg="$*"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] [$level] $msg" | tee -a "$LOG_FILE"
}

log_audit() {
    # 写结构化 JSON 审计记录（供 CLS 采集）
    local event="$1"
    local extra="${2:-}"
    printf '{"event":"%s","date":"%s","host":"%s"%s}\n' \
        "$event" "$BACKUP_DATE" "$(hostname)" "$extra" \
        >> "$AUDIT_LOG"
}

die() {
    log "ERROR" "$*"
    log_audit "backup.failed" ",\"reason\":\"$*\""
    exit 1
}

# ── 前置检查 ─────────────────────────────────────────────────────────────────

check_dependencies() {
    local missing=()
    for cmd in pg_dump openssl coscli; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        die "缺少依赖命令：${missing[*]}"
    fi
}

check_disk_space() {
    # 确保备份目录有足够空间（至少 2GB）
    local available
    available=$(df -BG "$BACKUP_DIR" 2>/dev/null | awk 'NR==2 {gsub("G",""); print $4}')
    if [[ -z "$available" ]] || [[ "$available" -lt 2 ]]; then
        die "备份目录可用空间不足 2GB（当前：${available}GB）"
    fi
}

# ── 主流程 ───────────────────────────────────────────────────────────────────

log "INFO" "=========================================="
log "INFO" "屯象OS 异地备份开始：$BACKUP_DATE"
log "INFO" "=========================================="
log_audit "backup.started"

check_dependencies
mkdir -p "$BACKUP_DIR"
check_disk_space

# ── 步骤1：PostgreSQL 全量备份 ────────────────────────────────────────────────

DUMP_FILE="$BACKUP_DIR/txos_${BACKUP_DATE}.sql.gz"

log "INFO" "步骤1/5: 执行 pg_dump 备份..."

PGPASSWORD="$BACKUP_DB_PASSWORD" pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --format=plain \
    --no-password \
    --verbose \
    2>>"$LOG_FILE" \
    | gzip --best > "$DUMP_FILE" \
    || die "pg_dump 失败"

DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
log "INFO" "数据库备份完成：$DUMP_FILE（压缩后 $DUMP_SIZE）"

# ── 步骤2：加密备份文件 ──────────────────────────────────────────────────────

log "INFO" "步骤2/5: AES-256-CBC 加密备份文件..."

ENCRYPTED_FILE="${DUMP_FILE}.enc"

openssl enc -aes-256-cbc -pbkdf2 -iter 100000 \
    -pass "env:BACKUP_ENCRYPTION_KEY" \
    -in  "$DUMP_FILE" \
    -out "$ENCRYPTED_FILE" \
    || die "openssl 加密失败"

# 计算校验和（用于完整性验证）
CHECKSUM=$(sha256sum "$ENCRYPTED_FILE" | cut -d' ' -f1)
echo "$CHECKSUM  ${BACKUP_DATE}.sql.gz.enc" > "${ENCRYPTED_FILE}.sha256"

# 删除未加密的备份文件（防止明文数据残留）
rm -f "$DUMP_FILE"
log "INFO" "加密完成，SHA256：$CHECKSUM"

# ── 步骤3：上传到腾讯云 COS（上海地域）─────────────────────────────────────

log "INFO" "步骤3/5: 上传到 COS（$COS_REGION）..."

COS_PATH="cos://${COS_BUCKET}/daily/${BACKUP_DATE_SHORT}/${BACKUP_DATE}.sql.gz.enc"
COS_CHECKSUM_PATH="cos://${COS_BUCKET}/daily/${BACKUP_DATE_SHORT}/${BACKUP_DATE}.sql.gz.enc.sha256"

coscli cp "$ENCRYPTED_FILE" "$COS_PATH" \
    --region "$COS_REGION" \
    || die "COS 上传失败（加密备份文件）"

coscli cp "${ENCRYPTED_FILE}.sha256" "$COS_CHECKSUM_PATH" \
    --region "$COS_REGION" \
    || die "COS 上传失败（校验和文件）"

ENC_SIZE=$(du -h "$ENCRYPTED_FILE" | cut -f1)
log "INFO" "上传完成：$COS_PATH（$ENC_SIZE）"

# ── 步骤4：清理本地旧备份 ────────────────────────────────────────────────────

log "INFO" "步骤4/5: 清理 ${RETAIN_DAYS} 天前的本地备份..."

# 只删除加密文件（未加密文件在步骤2已删除）
CLEANED_COUNT=$(find "$BACKUP_DIR" -name "*.sql.gz.enc" -mtime +"$RETAIN_DAYS" -print | wc -l)
find "$BACKUP_DIR" -name "*.sql.gz.enc"        -mtime +"$RETAIN_DAYS" -delete
find "$BACKUP_DIR" -name "*.sql.gz.enc.sha256" -mtime +"$RETAIN_DAYS" -delete

log "INFO" "清理旧备份完成（删除 ${CLEANED_COUNT} 个文件）"

# ── 步骤5：写审计记录 ────────────────────────────────────────────────────────

log "INFO" "步骤5/5: 写审计记录..."

log_audit "backup.completed" \
    ",\"cos_path\":\"$COS_PATH\",\"size\":\"$ENC_SIZE\",\"checksum\":\"$CHECKSUM\",\"cleaned_files\":$CLEANED_COUNT"

log "INFO" "=========================================="
log "INFO" "屯象OS 异地备份全流程完成 ✓"
log "INFO" "文件：${BACKUP_DATE}.sql.gz.enc → COS 上海"
log "INFO" "=========================================="
