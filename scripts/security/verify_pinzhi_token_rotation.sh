#!/usr/bin/env bash
# ⚠️ DEPRECATED — 用 verify_pinzhi_token_rotation.py 替代
# 本 bash 版调用 /api/shop/info 端点（adapter.py 实际不存在该端点），且无法
# 生成 MD5 sign（品智所有端点必须签名）。会全部 SKIP/FAIL，无验证价值。
# Python 版 verify_pinzhi_token_rotation.py 用真实 adapter 签名 +
# /pinzhi/organizations.do 端点（adapter.py:170）。
# 详见 docs/runbooks/s01-pinzhi-token-rotation.md §5.1

echo "DEPRECATED — use verify_pinzhi_token_rotation.py instead" >&2
echo "  python3 scripts/security/verify_pinzhi_token_rotation.py" >&2
exit 2

# 以下保留作历史参考；本脚本已 exit 2，不会执行
set -euo pipefail

TIMEOUT="${PINZHI_VERIFY_TIMEOUT:-5}"
BRAND_FILTER="${PINZHI_VERIFY_BRAND:-}"

# === 17 个 token 配置（与 shared/adapters/pinzhi/src/merchants.py 对齐）===
declare -A BRAND_BASE_URLS=(
  [czyz]="http://czyq.pinzhikeji.net:8899/pzcatering-gateway"
  [zqx]="http://ljcg.pinzhikeji.net:8899/pzcatering-gateway"
  [sgc]="http://xcsgc.pinzhikeji.net:8899/pzcatering-gateway"
)

# 格式："env_var:store_id:store_name:brand"（store_id=API 表示主令牌，跳过 ping store endpoint）
TOKENS=(
  "CZYZ_PINZHI_API_TOKEN:API:API主令牌:czyz"
  "CZYZ_PINZHI_STORE_2461_TOKEN:2461:文化城店:czyz"
  "CZYZ_PINZHI_STORE_7269_TOKEN:7269:浏小鲜:czyz"
  "CZYZ_PINZHI_STORE_19189_TOKEN:19189:永安店:czyz"
  "ZQX_PINZHI_API_TOKEN:API:API主令牌:zqx"
  "ZQX_PINZHI_STORE_20529_TOKEN:20529:门店1:zqx"
  "ZQX_PINZHI_STORE_32109_TOKEN:32109:门店2:zqx"
  "ZQX_PINZHI_STORE_32304_TOKEN:32304:门店3:zqx"
  "ZQX_PINZHI_STORE_32305_TOKEN:32305:门店4:zqx"
  "ZQX_PINZHI_STORE_32306_TOKEN:32306:门店5:zqx"
  "ZQX_PINZHI_STORE_32309_TOKEN:32309:门店6:zqx"
  "SGC_PINZHI_API_TOKEN:API:API主令牌:sgc"
  "SGC_PINZHI_STORE_2463_TOKEN:2463:门店1:sgc"
  "SGC_PINZHI_STORE_7896_TOKEN:7896:门店2:sgc"
  "SGC_PINZHI_STORE_24777_TOKEN:24777:门店3:sgc"
  "SGC_PINZHI_STORE_36199_TOKEN:36199:门店4:sgc"
  "SGC_PINZHI_STORE_41405_TOKEN:41405:门店5:sgc"
)

# === 依赖检查 ===
for cmd in curl jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: 缺依赖 $cmd（macOS: brew install $cmd）" >&2
    exit 2
  fi
done

# === 探测函数 ===
ok_count=0
fail_count=0
skip_count=0

probe_token() {
  local env_var="$1" store_id="$2" store_name="$3" brand="$4"
  local token="${!env_var:-}"
  local base_url="${BRAND_BASE_URLS[$brand]}"

  if [ -z "$token" ]; then
    echo "✗ [$brand/$store_id $store_name] env $env_var 未设置（轮换前的预期；轮换后必须设）" >&2
    fail_count=$((fail_count + 1))
    return
  fi

  # 品智 ping endpoint（公开接口，token 失败时返 401/403）
  # 使用 /shop/info 探测（API 主令牌也支持，无需店 ID）
  local url="${base_url}/api/shop/info"
  local http_code
  http_code=$(curl -sS -o /dev/null -w "%{http_code}" \
    --max-time "$TIMEOUT" \
    -H "Authorization: Bearer ${token}" \
    -H "Content-Type: application/json" \
    "$url" 2>&1 || echo "000")

  case "$http_code" in
    200|201|204)
      echo "✓ [$brand/$store_id $store_name] HTTP $http_code"
      ok_count=$((ok_count + 1))
      ;;
    401|403)
      echo "✗ [$brand/$store_id $store_name] HTTP $http_code — token 无效或已 revoke" >&2
      fail_count=$((fail_count + 1))
      ;;
    000)
      echo "✗ [$brand/$store_id $store_name] curl 失败（网络 / DNS / 超时 ${TIMEOUT}s）" >&2
      fail_count=$((fail_count + 1))
      ;;
    404|405)
      # 接口可能不存在或不支持 GET — 但 401/403 没出来证明 token 至少被 server 接受
      echo "~ [$brand/$store_id $store_name] HTTP $http_code — endpoint 缺失，token 状态未知" >&2
      skip_count=$((skip_count + 1))
      ;;
    5*)
      echo "~ [$brand/$store_id $store_name] HTTP $http_code — 服务器错误，token 状态未知" >&2
      skip_count=$((skip_count + 1))
      ;;
    *)
      echo "? [$brand/$store_id $store_name] HTTP $http_code — 未知响应，需手工验证" >&2
      skip_count=$((skip_count + 1))
      ;;
  esac
}

echo "=== 品智 17 token 轮换 e2e 探测 ==="
echo "目标：17 个店；超时 ${TIMEOUT}s/店；过滤 brand=${BRAND_FILTER:-all}"
echo

for entry in "${TOKENS[@]}"; do
  IFS=':' read -r env_var store_id store_name brand <<< "$entry"
  if [ -n "$BRAND_FILTER" ] && [ "$BRAND_FILTER" != "$brand" ]; then
    continue
  fi
  probe_token "$env_var" "$store_id" "$store_name" "$brand"
done

echo
echo "=== 总结 ==="
echo "  ✓ OK:    $ok_count"
echo "  ✗ FAIL:  $fail_count"
echo "  ~ SKIP:  $skip_count（404/5xx，需手工验证）"
echo

if [ "$fail_count" -gt 0 ]; then
  echo "❌ FAIL — $fail_count 个 token 验证失败" >&2
  exit 1
fi

if [ "$ok_count" -lt 17 ] && [ -z "$BRAND_FILTER" ]; then
  echo "⚠️  仅 $ok_count/17 OK（其余 $skip_count skip） — 需手工复核 skip 项" >&2
  exit 1
fi

echo "✅ 全部探测 OK"
exit 0
