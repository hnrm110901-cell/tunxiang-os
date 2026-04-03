#!/bin/bash
# 验证 DNS 解析是否生效
SERVER_IP="42.194.229.21"
DOMAINS="tunxiangos.com www.tunxiangos.com api.tunxiangos.com hub.tunxiangos.com os.tunxiangos.com pos.tunxiangos.com kds.tunxiangos.com m.tunxiangos.com forge.tunxiangos.com ws.tunxiangos.com docs.tunxiangos.com gray-pos.tunxiangos.com gray-kds.tunxiangos.com gray-os.tunxiangos.com gray-api.tunxiangos.com gray-m.tunxiangos.com stg-pos.tunxiangos.com stg-os.tunxiangos.com stg-api.tunxiangos.com"

echo "═══════════════════════════════════════"
echo " DNS 解析验证 (期望 IP: $SERVER_IP)"
echo "═══════════════════════════════════════"

pass=0; fail=0
for domain in $DOMAINS; do
  resolved=$(dig +short "$domain" 2>/dev/null | head -1)
  if [ "$resolved" = "$SERVER_IP" ] || [ "$resolved" = "tunxiangos.com." ]; then
    echo "  ✅ $domain → $resolved"
    ((pass++))
  else
    echo "  ❌ $domain → ${resolved:-未解析}"
    ((fail++))
  fi
done

echo ""
echo "结果: $pass 通过 / $fail 失败 / 共 $(echo $DOMAINS | wc -w | tr -d ' ') 条"
[ $fail -eq 0 ] && echo "🎉 全部解析正确！" || echo "⚠️ 请等待 DNS 生效（通常 5-10 分钟）"
