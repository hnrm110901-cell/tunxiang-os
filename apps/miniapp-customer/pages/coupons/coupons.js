// 优惠券页
const app = getApp();

Page({
  data: {
    filter: 'available',
    coupons: [],
    emptyText: '暂无可用优惠券',
  },

  onLoad() {
    this.loadCoupons();
  },

  onPullDownRefresh() {
    this.loadCoupons().then(() => wx.stopPullDownRefresh());
  },

  setFilter(e) {
    const filter = e.currentTarget.dataset.filter;
    const emptyMap = {
      available: '暂无可用优惠券',
      used: '暂无已使用的优惠券',
      expired: '暂无已过期的优惠券',
    };
    this.setData({ filter, emptyText: emptyMap[filter] });
    this.loadCoupons();
  },

  async loadCoupons() {
    try {
      const res = await wx.request({
        url: `${app.globalData.apiBase}/api/v1/coupon/my-list`,
        data: {
          customer_id: app.globalData.customerId,
          status: this.data.filter,
        },
        header: { 'X-Tenant-ID': app.globalData.tenantId },
      });
      if (res.data.ok) {
        const coupons = (res.data.data.items || []).map(c => this.formatCoupon(c));
        this.setData({ coupons });
      }
    } catch (err) {
      console.error('loadCoupons failed', err);
    }
  },

  formatCoupon(coupon) {
    // 门槛文案
    let thresholdText = '无门槛';
    if (coupon.threshold_amount && coupon.threshold_amount > 0) {
      thresholdText = `满${coupon.threshold_amount / 100}元可用`;
    }

    // 有效期文案
    let expireText = '';
    if (coupon.expire_at) {
      expireText = `有效期至 ${coupon.expire_at.slice(0, 10)}`;
    }

    // 使用条件
    let condition = '';
    if (coupon.applicable_scope === 'specific_dishes') {
      condition = '限指定菜品使用';
    } else if (coupon.applicable_scope === 'specific_category') {
      condition = '限指定品类使用';
    } else if (coupon.applicable_scope === 'specific_stores') {
      condition = '限指定门店使用';
    }

    // 折扣值展示
    let discountValue = '';
    if (coupon.type === 'reduction') {
      discountValue = String(coupon.discount_value / 100);
    } else if (coupon.type === 'discount') {
      discountValue = String(coupon.discount_value / 10);
    }

    return {
      ...coupon,
      thresholdText,
      expireText,
      condition,
      discountValue,
    };
  },

  useCoupon(e) {
    const id = e.currentTarget.dataset.id;
    wx.navigateTo({
      url: `/pages/index/index?coupon_id=${id}`,
    });
  },
});
