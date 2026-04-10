#!/bin/bash
# ============================================================
# 屯象OS 演示环境快速创建脚本
# 版本: 1.0.0  |  最后更新: 2026-04-06
# 维护人: 李淳（屯象OS创始人）
#
# 功能:
#   为新商户/售前演示快速创建隔离演示环境
#   自动: 创建独立DB schema → 导入种子数据 → 分配子域名 → 设置TTL
#
# 使用方式:
#   ./create-demo-env.sh --tenant=demo_abc --expires=3d --brand="某品牌"
#   ./create-demo-env.sh --tenant=demo_abc --expires=7d --brand="某品牌" --template=hotpot
#
# 支持的演示模板:
#   default  通用餐饮模板（默认）
#   hotpot   火锅模板（含锅底/涮料品类）
#   fastfood 快餐模板（含套餐/加料）
#   cafe     咖啡/茶饮模板
# ============================================================

set -euo pipefail

# ──────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly DEMO_DOMAIN="demo.tunxiang.com"
readonly DEMO_SCHEMA_PREFIX="demo_"
readonly MAX_EXPIRES_DAYS=30       # 最长TTL：30天
readonly DEFAULT_EXPIRES_DAYS=7    # 默认TTL：7天

# 数据库连接（从环境变量或默认值读取）
DB_HOST="${TUNXIANG_DB_HOST:-localhost}"
DB_PORT="${TUNXIANG_DB_PORT:-5432}"
DB_USER="${TUNXIANG_DB_USER:-tunxiang}"
DB_NAME="${TUNXIANG_DB_NAME:-tunxiang_db}"
PGPASSWORD="${TUNXIANG_DB_PASSWORD:-}"
export PGPASSWORD

# Nginx配置目录
NGINX_CONF_DIR="${NGINX_CONF_DIR:-/etc/nginx/conf.d}"

# ──────────────────────────────────────────────
# 颜色输出
# ──────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

info()  { echo -e "${BLUE}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
fatal() { echo -e "${RED}[FATAL]${RESET} $*" >&2; exit 1; }
step()  { echo -e "\n${BOLD}${CYAN}▶ $*${RESET}"; }

# ──────────────────────────────────────────────
# 参数解析
# ──────────────────────────────────────────────
TENANT=""
BRAND=""
EXPIRES="7d"
TEMPLATE="default"
DRY_RUN=false
SKIP_NGINX=false

for arg in "$@"; do
  case "$arg" in
    --tenant=*)   TENANT="${arg#*=}" ;;
    --brand=*)    BRAND="${arg#*=}" ;;
    --expires=*)  EXPIRES="${arg#*=}" ;;
    --template=*) TEMPLATE="${arg#*=}" ;;
    --dry-run)    DRY_RUN=true ;;
    --skip-nginx) SKIP_NGINX=true ;;
    --help|-h)
      cat << EOF
使用方式:
  $(basename "$0") --tenant=<id> --brand=<品牌名> [选项]

必填参数:
  --tenant=<id>       租户ID（如 demo_hotpot_001，必须以 demo_ 开头）
  --brand=<品牌名>    演示品牌名称（如"某火锅品牌"）

可选参数:
  --expires=<期限>    有效期（如 3d/7d/30d，默认 7d，最长 30d）
  --template=<模板>   演示模板（default/hotpot/fastfood/cafe，默认 default）
  --skip-nginx        跳过 Nginx 子域名配置
  --dry-run           仅打印操作，不实际执行
  --help              显示此帮助

示例:
  $(basename "$0") --tenant=demo_xinruihotpot --brand="新瑞火锅" --expires=3d --template=hotpot
EOF
      exit 0
      ;;
    *)
      warn "未知参数: $arg（已忽略）"
      ;;
  esac
done

# ──────────────────────────────────────────────
# 参数校验
# ──────────────────────────────────────────────
validate_params() {
  [[ -z "$TENANT" ]]  && fatal "必须指定 --tenant=<id>"
  [[ -z "$BRAND" ]]   && fatal "必须指定 --brand=<品牌名>"

  # tenant ID 必须以 demo_ 开头（安全防护）
  [[ "$TENANT" == "${DEMO_SCHEMA_PREFIX}"* ]] || \
    fatal "tenant ID 必须以 '${DEMO_SCHEMA_PREFIX}' 开头（当前: ${TENANT}）"

  # tenant ID 只允许字母数字下划线
  [[ "$TENANT" =~ ^[a-z0-9_]+$ ]] || \
    fatal "tenant ID 只允许小写字母、数字和下划线"

  # 解析 expires
  local expires_days
  if [[ "$EXPIRES" =~ ^([0-9]+)d$ ]]; then
    expires_days="${BASH_REMATCH[1]}"
  else
    fatal "expires 格式错误（应为 Nd，如 7d）: ${EXPIRES}"
  fi

  if (( expires_days > MAX_EXPIRES_DAYS )); then
    fatal "expires 不能超过 ${MAX_EXPIRES_DAYS}天（当前: ${expires_days}天）"
  fi

  EXPIRES_DAYS="$expires_days"

  # 模板有效性
  case "$TEMPLATE" in
    default|hotpot|fastfood|cafe) ;;
    *) fatal "未知模板: ${TEMPLATE}。支持: default/hotpot/fastfood/cafe" ;;
  esac
}

# ──────────────────────────────────────────────
# 步骤 1: 检查 tenant 是否已存在
# ──────────────────────────────────────────────
check_tenant_exists() {
  step "检查 tenant 是否已存在: ${TENANT}"

  local schema_exists
  schema_exists=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = '${TENANT}');" \
    2>/dev/null || echo "false")

  if [[ "$schema_exists" == "t" ]]; then
    fatal "Tenant '${TENANT}' 的 DB schema 已存在！如需重建请先运行: ./env-manager.sh demo destroy ${TENANT}"
  fi

  ok "Tenant ${TENANT} 不存在，可以创建"
}

# ──────────────────────────────────────────────
# 步骤 2: 创建独立 DB Schema
# ──────────────────────────────────────────────
create_db_schema() {
  step "创建 DB Schema: ${TENANT}"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY-RUN] 将执行: CREATE SCHEMA ${TENANT}; GRANT ALL ON SCHEMA ${TENANT} TO ${DB_USER};"
    return
  fi

  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" << EOSQL
-- 创建 demo tenant schema
CREATE SCHEMA IF NOT EXISTS "${TENANT}";

-- 授权
GRANT ALL ON SCHEMA "${TENANT}" TO "${DB_USER}";

-- 设置 schema 元数据（通过 comment 记录创建信息）
COMMENT ON SCHEMA "${TENANT}" IS 'Demo tenant: ${BRAND} | Created: $(date -u +%Y-%m-%dT%H:%M:%SZ) | Expires: $(date -u -d "+${EXPIRES_DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "auto")';
EOSQL

  ok "DB Schema '${TENANT}' 创建成功"
}

# ──────────────────────────────────────────────
# 步骤 3: 运行 DDL 迁移（建表）
# ──────────────────────────────────────────────
run_migrations() {
  step "执行 DDL 迁移（在 schema: ${TENANT}）"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY-RUN] 将对 schema ${TENANT} 执行所有迁移脚本"
    return
  fi

  # 设置 search_path 后执行迁移
  if [[ -f "${REPO_ROOT}/migrate.sh" ]]; then
    info "使用 migrate.sh 执行迁移..."
    DB_SCHEMA="${TENANT}" bash "${REPO_ROOT}/migrate.sh" || \
      warn "迁移脚本执行中有警告，请检查日志"
  else
    warn "未找到 migrate.sh，跳过 DDL 迁移"
    warn "请手动对 schema '${TENANT}' 执行建表 SQL"
  fi

  ok "DDL 迁移完成"
}

# ──────────────────────────────────────────────
# 步骤 4: 导入种子数据
# ──────────────────────────────────────────────
import_seed_data() {
  step "导入演示种子数据（模板: ${TEMPLATE}）"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY-RUN] 将导入模板 '${TEMPLATE}' 的种子数据到 schema ${TENANT}"
    return
  fi

  local seed_script="${REPO_ROOT}/seed_demo_data.py"

  if [[ -f "$seed_script" ]]; then
    info "运行种子数据脚本..."
    python3 "$seed_script" \
      --tenant="${TENANT}" \
      --brand="${BRAND}" \
      --template="${TEMPLATE}" \
      --db-host="${DB_HOST}" \
      --db-port="${DB_PORT}" \
      --db-user="${DB_USER}" \
      --db-name="${DB_NAME}" 2>&1 || warn "种子数据导入有警告，请检查"
  else
    warn "未找到 seed_demo_data.py，尝试直接插入基础数据..."
    # 插入最基础的 tenant 元数据
    psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" << EOSQL
SET search_path TO "${TENANT}";

-- 基础配置（如果 tenants 表存在）
INSERT INTO tenants (id, name, display_name, status, created_at)
VALUES ('${TENANT}', '${TENANT}', '${BRAND}', 'active', NOW())
ON CONFLICT (id) DO NOTHING;
EOSQL
    warn "仅插入了基础 tenant 元数据，完整种子数据需手动导入"
  fi

  ok "种子数据导入完成"
}

# ──────────────────────────────────────────────
# 步骤 5: 分配子域名（Nginx 配置）
# ──────────────────────────────────────────────
configure_subdomain() {
  step "配置子域名: ${TENANT}.${DEMO_DOMAIN}"

  if [[ "$SKIP_NGINX" == "true" ]]; then
    info "已跳过 Nginx 配置（--skip-nginx）"
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY-RUN] 将创建 Nginx 配置: ${NGINX_CONF_DIR}/demo-${TENANT}.conf"
    return
  fi

  local nginx_conf="${NGINX_CONF_DIR}/demo-${TENANT}.conf"

  # 检查 Nginx conf 目录是否可写
  if [[ ! -w "$NGINX_CONF_DIR" ]]; then
    warn "Nginx conf 目录不可写: ${NGINX_CONF_DIR}，跳过子域名配置"
    warn "手动添加 DNS/Nginx 配置以访问: ${TENANT}.${DEMO_DOMAIN}"
    return
  fi

  cat > "$nginx_conf" << EONGINX
# 屯象OS Demo环境 - ${TENANT} (${BRAND})
# 创建时间: $(date -u +%Y-%m-%dT%H:%M:%SZ)
# 过期时间: $(date -u -d "+${EXPIRES_DAYS} days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "manual")

server {
    listen 80;
    server_name ${TENANT}.${DEMO_DOMAIN};

    # 将 tenant 信息注入请求头
    set \$tunxiang_tenant "${TENANT}";

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Tenant-ID ${TENANT};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }

    # 健康检查
    location /health {
        proxy_pass http://localhost:8000/health;
        access_log off;
    }

    # 拦截管理接口（Demo环境不开放）
    location /api/v1/admin/system {
        return 403 '{"error":"admin API not available in demo environment"}';
        add_header Content-Type application/json;
    }
}
EONGINX

  # 测试 Nginx 配置并重载
  if nginx -t 2>/dev/null; then
    nginx -s reload 2>/dev/null && ok "Nginx 配置已更新并重载" || warn "Nginx 重载失败，请手动执行: nginx -s reload"
  else
    warn "Nginx 配置测试失败，已写入文件但未重载: ${nginx_conf}"
  fi

  ok "子域名配置完成: http://${TENANT}.${DEMO_DOMAIN}"
}

# ──────────────────────────────────────────────
# 步骤 6: 设置 TTL（到期自动清理）
# ──────────────────────────────────────────────
setup_ttl() {
  step "设置 TTL: ${EXPIRES_DAYS} 天后自动清理"

  if [[ "$DRY_RUN" == "true" ]]; then
    info "[DRY-RUN] 将注册 TTL 清理任务"
    return
  fi

  local expires_at
  expires_at=$(date -d "+${EXPIRES_DAYS} days" +%Y-%m-%d 2>/dev/null || \
               date -v "+${EXPIRES_DAYS}d" +%Y-%m-%d 2>/dev/null || \
               echo "unknown")

  # 方式1: 写入 demo-ttl 记录表（如果存在）
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c \
    "INSERT INTO demo_tenants_ttl (tenant_id, brand_name, template, expires_at, created_at)
     VALUES ('${TENANT}', '${BRAND}', '${TEMPLATE}', '${expires_at}', NOW())
     ON CONFLICT (tenant_id) DO UPDATE SET expires_at = EXCLUDED.expires_at;" \
    2>/dev/null || warn "demo_tenants_ttl 表不存在，跳过DB记录"

  # 方式2: 创建 at 定时任务（如果 at 命令可用）
  if command -v at &>/dev/null; then
    echo "bash ${SCRIPT_DIR}/../scripts/env-manager.sh demo destroy ${TENANT}" | \
      at "$(date -d "+${EXPIRES_DAYS} days" '+%H:%M %Y-%m-%d' 2>/dev/null || echo "now + ${EXPIRES_DAYS} days")" \
      2>/dev/null && ok "已注册 at 定时清理任务（${expires_at}）" || warn "at 定时任务注册失败"
  else
    warn "at 命令不可用，请手动在 ${expires_at} 销毁此演示环境"
    warn "销毁命令: ./env-manager.sh demo destroy ${TENANT}"
  fi
}

# ──────────────────────────────────────────────
# 步骤 7: 输出访问信息
# ──────────────────────────────────────────────
print_summary() {
  local expires_at
  expires_at=$(date -d "+${EXPIRES_DAYS} days" '+%Y-%m-%d' 2>/dev/null || echo "${EXPIRES_DAYS}天后")

  echo ""
  echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}${GREEN}║       演示环境创建完成！                   ║${RESET}"
  echo -e "${BOLD}${GREEN}╠════════════════════════════════════════════╣${RESET}"
  echo -e "${BOLD}${GREEN}║${RESET} Tenant ID : ${BOLD}${TENANT}${RESET}"
  echo -e "${BOLD}${GREEN}║${RESET} 品牌名称  : ${BOLD}${BRAND}${RESET}"
  echo -e "${BOLD}${GREEN}║${RESET} 演示模板  : ${TEMPLATE}"
  echo -e "${BOLD}${GREEN}║${RESET} 访问地址  : http://${TENANT}.${DEMO_DOMAIN}"
  echo -e "${BOLD}${GREEN}║${RESET} 有效期    : ${EXPIRES_DAYS}天（到 ${expires_at}）"
  echo -e "${BOLD}${GREEN}╠════════════════════════════════════════════╣${RESET}"
  echo -e "${BOLD}${GREEN}║${RESET} 销毁命令:"
  echo -e "${BOLD}${GREEN}║${RESET}   ./env-manager.sh demo destroy ${TENANT}"
  echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════╝${RESET}"
  echo ""
}

# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────
main() {
  echo -e "\n${BOLD}屯象OS 演示环境创建脚本${RESET} v1.0.0"
  echo -e "时间: $(date '+%Y-%m-%d %H:%M:%S')\n"

  validate_params

  if [[ "$DRY_RUN" == "true" ]]; then
    warn "DRY-RUN 模式：仅打印操作，不实际执行"
  fi

  info "Tenant ID : ${TENANT}"
  info "品牌名称  : ${BRAND}"
  info "演示模板  : ${TEMPLATE}"
  info "有效期    : ${EXPIRES_DAYS}天"
  echo ""

  check_tenant_exists
  create_db_schema
  run_migrations
  import_seed_data
  configure_subdomain
  setup_ttl
  print_summary
}

main "$@"
