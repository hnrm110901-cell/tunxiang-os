// 领券中心
// API:
//   GET  /api/v1/growth/coupons/available   可领取优惠券列表
//   POST /api/v1/growth/coupons/claim       领取优惠券

var api = require('../../utils/api.js');

Page({
  data: {
    // 分类Tab
    categories: [
      { key: 'all', label: '全部' },
      { key: 'reduction', label: '满减' },
      { key: 'discount', label: '折扣' },
      { key: 'newcomer', label: '新人专享' },
      { key: 'limited', label: '限时' }
    ],
    activeCategory: 'all',

    // 数据
    allList: [],
    filteredList: [],
    claimableCount: 0,
    loading: false,

    // 倒计时定时器ID
    _countdownTimer: null
  },

  onLoad: function () {
    this._loadCoupons();
  },

  onShow: function () {
    // 页面再次显示时刷新
  },

  onUnload: function () {
    this._clearCountdown();
  },

  onHide: function () {
    this._clearCountdown();
  },

  onPullDownRefresh: function () {
    var self = this;
    self._loadCoupons().then(function () {
      wx.stopPullDownRefresh();
    }).catch(function () {
      wx.stopPullDownRefresh();
    });
  },

  onShareAppMessage: function () {
    return {
      title: '领券中心 - 超多优惠等你领',
      path: '/pages/coupon-center/coupon-center'
    };
  },

  // ─── 分类切换 ───

  switchCategory: function (e) {
    var key = e.currentTarget.dataset.key;
    if (key === this.data.activeCategory) return;
    this.setData({ activeCategory: key });
    this._applyFilter();
  },

  _applyFilter: function () {
    var key = this.data.activeCategory;
    var all = this.data.allList;
    var filtered;

    if (key === 'all') {
      filtered = all;
    } else if (key === 'reduction') {
      filtered = all.filter(function (c) { return c.couponType === 'reduction' || c.couponType === 'cash'; });
    } else if (key === 'discount') {
      filtered = all.filter(function (c) { return c.couponType === 'discount'; });
    } else if (key === 'newcomer') {
      filtered = all.filter(function (c) { return c.isNewcomer; });
    } else if (key === 'limited') {
      filtered = all.filter(function (c) { return c.isLimited; });
    } else {
      filtered = all;
    }

    this.setData({ filteredList: filtered });
  },

  // ─── 加载数据 ───

  _loadCoupons: function () {
    var self = this;
    self.setData({ loading: true });

    return api.txRequest('/api/v1/growth/coupons/available')
      .then(function (data) {
        var items = self._formatList(data.items || data || []);
        var claimableCount = items.filter(function (c) {
          return c.claimStatus === 'available';
        }).length;

        self.setData({
          allList: items,
          claimableCount: claimableCount,
          loading: false
        });
        self._applyFilter();
        self._startCountdown();
      })
      .catch(function () {
        // 降级：使用Mock数据
        var mockItems = self._getMockData();
        var claimableCount = mockItems.filter(function (c) {
          return c.claimStatus === 'available';
        }).length;

        self.setData({
          allList: mockItems,
          claimableCount: claimableCount,
          loading: false
        });
        self._applyFilter();
        self._startCountdown();
      });
  },

  // ─── 格式化数据 ───

  _formatList: function (rawItems) {
    var now = Date.now();
    var self = this;

    return rawItems.map(function (c) {
      var couponType = c.coupon_type || c.type || 'reduction';
      var faceValue = '';
      var cashAmountFen = c.cash_amount_fen || 0;
      var discountRate = c.discount_rate || 0;

      if (couponType === 'reduction' || couponType === 'cash') {
        faceValue = String(Math.round(cashAmountFen / 100));
      } else if (couponType === 'discount') {
        faceValue = (discountRate / 10).toFixed(1).replace('.0', '');
      }

      var minOrderFen = c.min_order_fen || 0;
      var thresholdText = '无门槛';
      if (minOrderFen > 0) {
        thresholdText = '满' + Math.round(minOrderFen / 100) + '元可用';
      }

      // 适用范围
      var scopeText = '全场通用';
      if (c.applicable_scope === 'specific_dishes') scopeText = '限指定菜品';
      else if (c.applicable_scope === 'specific_category') scopeText = '限指定品类';
      else if (c.applicable_scope === 'specific_stores') scopeText = '限指定门店';

      // 有效期
      var validText = '';
      if (c.expiry_days) {
        validText = '领取后' + c.expiry_days + '天内有效';
      } else if (c.end_date) {
        validText = '有效至 ' + c.end_date.slice(0, 10);
      }

      // 领取状态
      var claimStatus = 'available';
      if (c.is_claimed || c.claimed_by_user) {
        claimStatus = 'claimed';
      } else if (c.total_quantity !== null && c.total_quantity !== undefined && c.claimed_count >= c.total_quantity) {
        claimStatus = 'soldout';
      }

      // 限时判断 + 倒计时
      var isLimited = false;
      var countdownText = '';
      var endTs = 0;
      if (c.end_date) {
        endTs = new Date(c.end_date + 'T23:59:59').getTime();
        var diffMs = endTs - now;
        var diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
        if (diffDays <= 3 && diffDays > 0) {
          isLimited = true;
          countdownText = self._calcCountdownText(endTs, now);
        }
      }
      if (c.is_limited) isLimited = true;

      return {
        id: c.id || c.coupon_id || '',
        name: c.name || '',
        couponType: couponType,
        faceValue: faceValue,
        thresholdText: thresholdText,
        scopeText: scopeText,
        validText: validText,
        claimStatus: claimStatus,
        isLimited: isLimited,
        isNewcomer: !!(c.is_newcomer || c.tag === 'newcomer'),
        countdownText: countdownText,
        endTs: endTs
      };
    });
  },

  _calcCountdownText: function (endTs, now) {
    var diff = endTs - (now || Date.now());
    if (diff <= 0) return '已结束';
    var hours = Math.floor(diff / (1000 * 60 * 60));
    var mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
    var secs = Math.floor((diff % (1000 * 60)) / 1000);
    if (hours >= 24) {
      var days = Math.floor(hours / 24);
      return '剩余' + days + '天' + (hours % 24) + '小时';
    }
    return '剩余' + hours + ':' + (mins < 10 ? '0' : '') + mins + ':' + (secs < 10 ? '0' : '') + secs;
  },

  // ─── 倒计时 ───

  _startCountdown: function () {
    this._clearCountdown();
    var self = this;
    var hasLimited = self.data.allList.some(function (c) { return c.isLimited; });
    if (!hasLimited) return;

    self.data._countdownTimer = setInterval(function () {
      var now = Date.now();
      var allList = self.data.allList;
      var changed = false;

      for (var i = 0; i < allList.length; i++) {
        if (allList[i].isLimited && allList[i].endTs) {
          var newText = self._calcCountdownText(allList[i].endTs, now);
          if (newText !== allList[i].countdownText) {
            allList[i].countdownText = newText;
            changed = true;
          }
        }
      }

      if (changed) {
        self.setData({ allList: allList });
        self._applyFilter();
      }
    }, 1000);
  },

  _clearCountdown: function () {
    if (this.data._countdownTimer) {
      clearInterval(this.data._countdownTimer);
      this.data._countdownTimer = null;
    }
  },

  // ─── 领取 ───

  onClaim: function (e) {
    var self = this;
    var couponId = e.currentTarget.dataset.id;
    var customerId = wx.getStorageSync('tx_customer_id') || '';

    if (!customerId) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }

    // 更新按钮状态为"领取中"
    self._updateClaimStatus(couponId, 'claiming');

    api.txRequest('/api/v1/growth/coupons/claim', 'POST', {
      coupon_id: couponId,
      customer_id: customerId
    }).then(function () {
      // 成功：震动反馈 + toast + 按钮变绿
      wx.vibrateShort({ type: 'medium' });
      wx.showToast({ title: '领取成功', icon: 'success' });
      self._updateClaimStatus(couponId, 'claimed');

      // 更新可领数
      var count = Math.max(0, self.data.claimableCount - 1);
      self.setData({ claimableCount: count });
    }).catch(function (err) {
      var msg = (err && err.message) || '领取失败';
      // 幂等：已领过
      if (msg.indexOf('已领取') >= 0 || msg.indexOf('已达') >= 0) {
        self._updateClaimStatus(couponId, 'claimed');
        wx.showToast({ title: '已领取过啦', icon: 'none' });
        return;
      }
      // 抢光
      if (msg.indexOf('领完') >= 0) {
        self._updateClaimStatus(couponId, 'soldout');
        wx.showToast({ title: '已被抢光', icon: 'none' });
        return;
      }
      // 其它错误恢复按钮
      self._updateClaimStatus(couponId, 'available');
      wx.showToast({ title: msg, icon: 'none' });
    });
  },

  _updateClaimStatus: function (couponId, status) {
    var allList = this.data.allList.map(function (c) {
      if (c.id === couponId) {
        return Object.assign({}, c, { claimStatus: status });
      }
      return c;
    });
    this.setData({ allList: allList });
    this._applyFilter();
  },

  // ─── Mock数据（后端不可用时降级） ───

  _getMockData: function () {
    return [
      {
        id: 'mock-1',
        name: '新人见面礼',
        couponType: 'reduction',
        faceValue: '20',
        thresholdText: '满100元可用',
        scopeText: '全场通用',
        validText: '领取后7天内有效',
        claimStatus: 'available',
        isLimited: false,
        isNewcomer: true,
        countdownText: '',
        endTs: 0
      },
      {
        id: 'mock-2',
        name: '满减大促',
        couponType: 'reduction',
        faceValue: '50',
        thresholdText: '满200元可用',
        scopeText: '全场通用',
        validText: '有效至 2026-04-30',
        claimStatus: 'available',
        isLimited: true,
        isNewcomer: false,
        countdownText: '剩余2天18小时',
        endTs: Date.now() + 2 * 24 * 3600 * 1000 + 18 * 3600 * 1000
      },
      {
        id: 'mock-3',
        name: '折扣体验券',
        couponType: 'discount',
        faceValue: '8.5',
        thresholdText: '满50元可用',
        scopeText: '限指定菜品',
        validText: '领取后15天内有效',
        claimStatus: 'available',
        isLimited: false,
        isNewcomer: false,
        countdownText: '',
        endTs: 0
      },
      {
        id: 'mock-4',
        name: '周末畅吃券',
        couponType: 'reduction',
        faceValue: '30',
        thresholdText: '满150元可用',
        scopeText: '限指定门店',
        validText: '有效至 2026-04-15',
        claimStatus: 'soldout',
        isLimited: false,
        isNewcomer: false,
        countdownText: '',
        endTs: 0
      }
    ];
  }
});
