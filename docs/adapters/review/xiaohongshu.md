# xiaohongshu 适配器评审（Sprint F1）

## 基本信息
- 对接系统：小红书（POI / 优惠券 / 评价抓取）
- 主文件：
  - `shared/adapters/xiaohongshu/src/xhs_client.py`
  - `shared/adapters/xiaohongshu/src/xhs_coupon_adapter.py`
  - `shared/adapters/xiaohongshu/src/xhs_poi_sync.py`
  - `shared/adapters/xiaohongshu/src/xhs_review_crawler.py`
- 代码行数：734 行
- Tier：T3（营销类，不直接涉及资金）
- 负责 Squad：Growth
- 工时预估：2pd

## 现状快照
- 依赖外部 SDK：httpx / uuid
- 是否存在 MOCK_MODE：**否**
- 是否 emit 事件：**否**
- 是否有幂等检查：**是**（xhs_client.py 第 48 行 `"nonce": uuid.uuid4().hex[:16]`）
- 是否有重试退避：**否**（0 处命中）
- 测试文件数：**0 个**——P1（T3 仍建议补主路径测试）

## 7 维评分（待 Owner 填充）
| 维度 | 分 | 证据 | 缺陷 |
|---|---|---|---|
| 1 订单/菜品双向同步 | ?/4 | 单向（POI/券下发+评价拉取） |  |
| 2 状态映射完备 | ?/4 |  |  |
| 3 重试/幂等 | ?/4 | 有 nonce，无重试 |  |
| 4 Mock/生产切换 | ?/4 |  |  |
| 5 凭证托管 | ?/4 |  |  |
| 6 异常分支 | ?/4 |  |  |
| 7 事件总线接入 | ?/4 |  |  |
| **总分** | **?/28** | | |

## 已识别缺陷（审计初稿）
- P0：
  - （T3 无强制 P0，按规划评分 <22 时直接 flag off）
- P1：
  - P1-1 无 tests/
  - P1-2 无 MOCK_MODE
  - P1-3 无重试（小红书反爬严格，429 高频）
  - P1-4 review_crawler 是否合规（反爬条款）待法务评估
- P2：
  - P2-1 emit_event COUPON.PUBLISHED / REVIEW.CRAWLED（T3 可暂缓）

## 推荐动作
- [ ] 补 MOCK_MODE + fixtures
- [ ] 429/5xx 退避（针对反爬触发高频 429）
- [ ] 评分 <22 时 flag off `agents.growth.xiaohongshu`

## 验收时间盒
- 评分完成：2026-04-29
- P0/P1 缺陷修复：2026-05-05
- 上生产 Gate：2026-05-07
