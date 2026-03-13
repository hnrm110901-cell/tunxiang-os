# 种子客户 API 配置目录

## 商户清单

| 商户 | brand_id | 门店数 | 品智域名 | 奥琦玮商户号 |
|------|----------|--------|----------|-------------|
| 尝在一起 | BRD_CZYZ0001 | 3家 | czyq.pinzhikeji.net | ✅ 1275413383 |
| 最黔线 | BRD_ZQX0001 | 6家 | ljcg.pinzhikeji.net | ✅ 1827518239 |
| 尚宫厨 | BRD_SGC0001 | 5家 | xcsgc.pinzhikeji.net | ✅ 1549254243 |

## 快速开通步骤

```bash
# 1. 运行种子脚本（需先启动数据库）
cd apps/api-gateway
python scripts/seed_real_merchants.py

# 2. 验证数据
python -c "
from sqlalchemy import create_engine, text
import os
url = os.getenv('DATABASE_URL','').replace('asyncpg','psycopg2')
e = create_engine(url)
with e.connect() as c:
    r = c.execute(text('SELECT brand_id, brand_name FROM brands WHERE brand_id LIKE :p'), {'p': 'BRD_%'})
    for row in r: print(row)
"
```

## ⚠️ 待填写项

### 尝在一起 - 奥琦玮商户号
1. 登录 https://crm.acewill.net 或奥琦玮管理后台
2. 进入「账户设置」→「商户信息」
3. 复制「商户号ID」
4. 更新 `.env.czyz` 中的 `CZYZ_AOQIWEI_MERCHANT_ID=` 字段
5. 更新数据库：
   ```sql
   UPDATE external_systems
   SET config = jsonb_set(config, '{aoqiwei_merchant_id}', '"填入商户号"')
   WHERE provider = 'aoqiwei'
     AND config->>'brand_id' = 'BRD_CZYZ0001';
   ```

### 尚宫厨 - 奥琦玮商户号
同上，更新 `SGC_AOQIWEI_MERCHANT_ID=` 和数据库 `BRD_SGC0001`。

## 门店 Token 安全说明

- 品智门店 Token 存储在 `external_systems.api_secret` 字段（数据库加密）
- 奥琦玮 AppKey 存储在 `external_systems.api_secret` 字段
- `.env.*` 文件已加入 `.gitignore`，禁止提交到 git
- 生产环境请将敏感字段迁移至 Vault 或加密存储
