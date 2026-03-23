# MiniApp 终端 · 消费者小程序

## 技术栈

```
uni-app (Vue 3 + <script setup> + TypeScript)
uni-ui（官方组件库）
Pinia（状态管理）
自定义业务组件
编译目标：微信小程序 + 抖音小程序 + H5
```

## 为什么用 uni-app + Vue 3

- 中国小程序跨端编译市场占有率最高的方案
- 一套代码编译到微信+抖音+H5三个平台
- 插件市场有大量餐饮相关组件
- 中文社区极其成熟，问题解决速度最快
- 这是屯象OS唯一使用Vue的终端，与React终端无代码耦合

## 页面结构

```
apps/miniapp-customer/src/
  pages/
    index/index.vue           # 首页（附近门店/推荐）
    store/detail.vue          # 门店详情
    menu/index.vue            # 菜单浏览+点餐
    cart/index.vue            # 购物车
    order/create.vue          # 下单+支付
    order/detail.vue          # 订单详情+出餐追踪
    order/list.vue            # 历史订单
    member/index.vue          # 会员中心
    member/card.vue           # 会员卡/储值卡
    coupon/index.vue          # 优惠券列表
    chef-home/index.vue       # 大厨到家
    enterprise/index.vue      # 企业订餐
    evaluate/index.vue        # 评价
  components/
    tx-dish-card.vue          # 菜品卡片
    tx-cart-bar.vue           # 底部购物车悬浮栏
    tx-spec-selector.vue      # 规格/做法/口味选择弹层
    tx-coupon-card.vue        # 优惠券卡片
    tx-ai-recommend.vue       # AI推荐模块
    tx-order-status.vue       # 订单状态追踪
    tx-store-card.vue         # 门店卡片
    tx-empty.vue              # 空状态
  composables/
    useAuth.ts                # 微信登录+手机号获取
    usePay.ts                 # 支付封装
    useLocation.ts            # 定位
    useCart.ts                # 购物车逻辑
  api/
    request.ts                # uni.request封装
    modules/
      store.ts                # 门店API
      menu.ts                 # 菜单API
      order.ts                # 订单API
      member.ts               # 会员API
      coupon.ts               # 优惠券API
  store/
    user.ts                   # Pinia用户状态
    cart.ts                   # Pinia购物车状态
  static/                     # 静态资源
  pages.json                  # 页面路由+TabBar配置
  manifest.json               # 小程序配置
  uni.scss                    # 全局样式变量
```

## 设计规范

```
主色调：#FF6B35（与Admin/Store保持一致）
卡片圆角：24rpx
按钮高度：88rpx（44px，微信标准）
购物车栏：固定底部 120rpx高
菜品卡片：左图右文模式（列表）或上图下文模式（网格）
底部TabBar：4项（首页/点餐/订单/我的）
页面间距：左右 32rpx
```

## API对接

```typescript
// api/request.ts
import { useUserStore } from '@/store/user';

const BASE_URL = import.meta.env.VITE_API_BASE;

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE';

export function txRequest<T>(
  url: string,
  method: HttpMethod = 'GET',
  data?: Record<string, any>,
): Promise<T> {
  const userStore = useUserStore();
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}/api/v1${url}`,
      method,
      data,
      header: {
        'Content-Type': 'application/json',
        'X-Tenant-ID': userStore.tenantId || '',
        'Authorization': userStore.token ? `Bearer ${userStore.token}` : '',
      },
      success: (res) => {
        const body = res.data as { ok: boolean; data: T; error?: any };
        if (body.ok) resolve(body.data);
        else reject(body.error);
      },
      fail: (err) => reject(err),
    });
  });
}
```

## 核心页面模式

### 菜单点餐页

```vue
<!-- pages/menu/index.vue -->
<template>
  <view class="menu-page">
    <!-- 门店信息栏 -->
    <view class="store-header">
      <text class="store-name">{{ store.name }}</text>
      <text class="table-no">{{ tableNo }}号桌</text>
    </view>

    <!-- 分类+菜品双栏 -->
    <view class="menu-body">
      <scroll-view class="category-nav" scroll-y>
        <view
          v-for="cat in categories" :key="cat.id"
          class="category-item"
          :class="{ active: currentCategory === cat.id }"
          @tap="currentCategory = cat.id"
        >
          <text>{{ cat.name }}</text>
        </view>
      </scroll-view>

      <scroll-view class="dish-list" scroll-y>
        <tx-dish-card
          v-for="dish in filteredDishes" :key="dish.id"
          :dish="dish"
          :quantity="getQuantity(dish.id)"
          @add="addToCart(dish)"
          @detail="showDetail(dish)"
        />
      </scroll-view>
    </view>

    <!-- AI推荐 -->
    <tx-ai-recommend
      v-if="recommendations.length"
      :items="recommendations"
      @select="addToCart"
    />

    <!-- 底部购物车栏 -->
    <tx-cart-bar
      :count="cartCount"
      :total="cartTotal"
      @tap="goToCart"
      @checkout="goToCheckout"
    />
  </view>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useCart } from '@/composables/useCart';
import type { DishItem } from '@tx/api-types';

const { cart, addToCart, getQuantity, cartCount, cartTotal } = useCart();
const currentCategory = ref('');
// ... 
</script>

<style lang="scss">
.menu-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.menu-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.category-nav {
  width: 160rpx;
  background: #F8F7F5;
}
.category-item {
  padding: 24rpx 16rpx;
  text-align: center;
  font-size: 28rpx;
  &.active {
    color: #FF6B35;
    font-weight: 600;
    background: #FFFFFF;
  }
}
.dish-list {
  flex: 1;
  padding: 16rpx;
}
</style>
```

## 编码规则

1. **必须使用 `<script setup lang="ts">`** —— 不用Options API
2. **样式用 rpx 单位** —— 750rpx = 屏幕宽度，实现响应式
3. **不引入 Ant Design / Naive UI / Element Plus** —— 只用uni-ui + 自定义组件
4. **API调用统一走txRequest** —— 自动带tenant_id和token
5. **页面文件不超过500行** —— 复杂逻辑抽到composables
6. **图片必须懒加载** —— `<image lazy-load />`
7. **首屏主包 < 2MB** —— 小程序审核硬要求
8. **分包加载** —— 大厨到家/企业订餐/评价等低频页面放分包
9. **微信支付/抖音支付走后端下单** —— 前端只调 `uni.requestPayment`
10. **会员登录用手机号快速验证** —— `<button open-type="getPhoneNumber">`
11. **所有页面配置分享** —— `onShareAppMessage` + `onShareTimeline`
12. **禁止在模板中写复杂表达式** —— 用computed
13. **条件编译** —— 平台差异用 `#ifdef MP-WEIXIN` / `#ifdef MP-TOUTIAO`
14. **AI推荐模块带"AI"标签** —— 让用户知道这是智能推荐

## 与React终端的关系

```
共享层（纯TypeScript，不依赖框架）：
  shared/api-types/    → MiniApp通过import使用相同的类型定义
  shared/constants/    → 订单状态枚举、菜品分类枚举等
  shared/utils/        → formatMoney()、calcMarginRate()等纯函数

不共享：
  UI组件              → MiniApp用Vue组件，Admin/Store用React组件
  状态管理            → MiniApp用Pinia，Admin/Store用Zustand
  API调用层           → MiniApp用uni.request，其他用fetch
```
