#!/usr/bin/env python3
"""从 JSON 凭证文件注入商户环境变量到 .env

用法:
  python3 scripts/inject-merchant-env.py /path/to/creds.json /opt/tunxiang-os/.env

JSON 格式示例:
{
  "CZYZ_PINZHI_BASE_URL": "https://czyq.pinzhikeji.net/api/v1",
  "CZYZ_PINZHI_API_TOKEN": "xxx",
  ...
}

也支持 Vault KV 格式:
{
  "data": {
    "data": {
      "CZYZ_PINZHI_API_TOKEN": "xxx",
      ...
    }
  }
}
"""

import json
import sys
from pathlib import Path

MERCHANT_KEYS = [
    # 尝在一起 — 品智
    "CZYZ_PINZHI_BASE_URL",
    "CZYZ_PINZHI_API_TOKEN",
    "CZYZ_PINZHI_STORE_2461_TOKEN",
    "CZYZ_PINZHI_STORE_7269_TOKEN",
    "CZYZ_PINZHI_STORE_19189_TOKEN",
    # 尝在一起 — 奥琦玮
    "CZYZ_AOQIWEI_BASE_URL",
    "CZYZ_AOQIWEI_APP_ID",
    "CZYZ_AOQIWEI_APP_KEY",
    "CZYZ_AOQIWEI_MERCHANT_ID",
    # 最黔线 — 品智
    "ZQX_PINZHI_BASE_URL",
    "ZQX_PINZHI_API_TOKEN",
    "ZQX_PINZHI_STORE_20529_TOKEN",
    "ZQX_PINZHI_STORE_32109_TOKEN",
    "ZQX_PINZHI_STORE_32304_TOKEN",
    "ZQX_PINZHI_STORE_32305_TOKEN",
    "ZQX_PINZHI_STORE_32306_TOKEN",
    "ZQX_PINZHI_STORE_32309_TOKEN",
    # 最黔线 — 奥琦玮
    "ZQX_AOQIWEI_BASE_URL",
    "ZQX_AOQIWEI_APP_ID",
    "ZQX_AOQIWEI_APP_KEY",
    "ZQX_AOQIWEI_MERCHANT_ID",
    # 尚宫厨 — 品智
    "SGC_PINZHI_BASE_URL",
    "SGC_PINZHI_API_TOKEN",
    "SGC_PINZHI_STORE_2463_TOKEN",
    "SGC_PINZHI_STORE_7896_TOKEN",
    "SGC_PINZHI_STORE_24777_TOKEN",
    "SGC_PINZHI_STORE_36199_TOKEN",
    "SGC_PINZHI_STORE_41405_TOKEN",
    # 尚宫厨 — 奥琦玮
    "SGC_AOQIWEI_BASE_URL",
    "SGC_AOQIWEI_APP_ID",
    "SGC_AOQIWEI_APP_KEY",
    "SGC_AOQIWEI_MERCHANT_ID",
    # 尚宫厨 — 卡券
    "SGC_COUPON_BASE_URL",
    "SGC_COUPON_APP_ID",
    "SGC_COUPON_APP_KEY",
    "SGC_COUPON_PLATFORMS",
]


def main() -> None:
    if len(sys.argv) < 3:
        print(f"用法: {sys.argv[0]} <creds.json> <.env路径>")
        sys.exit(1)

    creds_path = Path(sys.argv[1])
    env_path = Path(sys.argv[2])

    with open(creds_path) as f:
        raw = json.load(f)

    # 支持 Vault KV v2 格式
    if "data" in raw and "data" in raw["data"]:
        creds = raw["data"]["data"]
    elif "data" in raw:
        creds = raw["data"]
    else:
        creds = raw

    # 读取现有 .env
    existing_lines: list[str] = []
    existing_keys: set[str] = set()
    if env_path.exists():
        with open(env_path) as f:
            existing_lines = f.readlines()
        for line in existing_lines:
            if "=" in line and not line.strip().startswith("#"):
                existing_keys.add(line.split("=", 1)[0].strip())

    # 追加缺失的凭证
    new_lines: list[str] = []
    for key in MERCHANT_KEYS:
        if key in creds and key not in existing_keys:
            new_lines.append(f"{key}={creds[key]}\n")

    if not new_lines:
        print("所有凭证已存在，无需更新。")
        return

    with open(env_path, "a") as f:
        f.write("\n# ── 商户凭证（自动注入） ──\n")
        for line in new_lines:
            f.write(line)

    print(f"✓ 已注入 {len(new_lines)} 个凭证到 {env_path}")


if __name__ == "__main__":
    main()
