var app = getApp();
var api = require('../../utils/api.js');

// Mock 数据：API 失败时降级使用
var MOCK_DETAIL = {
  id: 'mock-campaign-001',
  name: '招牌酸菜鱼拼团特惠',
  status: 'active',
  group_price_fen: 6800,
  original_price_fen: 9800,
  target_size: 5,
  current_size: 3,
  end_time: new Date(Date.now() + 3600000 * 24).toISOString(),
  members: [
    { nickname: '小明', avatar_url: '' },
    { nickname: '小红', avatar_url: '' },
    { nickname: '阿强', avatar_url: '' }
  ],
  description: '<p>精选新鲜鲈鱼，搭配秘制酸菜，麻辣鲜香，回味无穷。</p>',
  detail_images: [],
  rules: [
    '活动期间每人限参团1次',
    '拼团成功后优惠自动发放',
    '未成团将在活动结束后自动退款',
    '拼团商品不与其他优惠同享'
  ],
  banners: [],
  _is_mock: true
};

Page({
  data: {
    detail: null,
    banners: [
      '/assets/placeholder-1.png',
      '/assets/placeholder-2.png',
      '/assets/placeholder-3.png'
    ],
    groupPriceYuan: '0.00',
    originalPriceYuan: '0.00',
    savedYuan: '0.00',
    countdown: { hours: '00', minutes: '00', seconds: '00' },
    displayMembers: [],
    emptySlots: [],
    rules: [],
    rulesExpanded: false,
    joining: false,
    showSuccess: false,
    campaignId: ''
  },

  _timer: null,

  onLoad: function (options) {
    var id = options.campaign_id || options.id || '';
    this.setData({ campaignId: id });
    this._loadDetail(id);
  },

  onUnload: function () {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  },

  onShareAppMessage: function () {
    var detail = this.data.detail;
    var title = detail ? detail.name + ' - 超值拼团' : '超值拼团';
    return {
      title: title,
      path: '/pages/group-buy-detail/group-buy-detail?id=' + this.data.campaignId,
      imageUrl: this.data.banners[0] || ''
    };
  },

  // ─── 加载详情 ───
  _loadDetail: function (id) {
    var self = this;
    api.txRequest('/api/v1/group-buy/campaigns/' + encodeURIComponent(id))
      .then(function (data) {
        self._applyDetail(data);
      })
      .catch(function () {
        // API 失败降级 Mock 数据
        self._applyDetail(MOCK_DETAIL);
        wx.showToast({ title: '已加载演示数据', icon: 'none' });
      });
  },

  _applyDetail: function (data) {
    var groupPriceFen = data.group_price_fen || 0;
    var originalPriceFen = data.original_price_fen || 0;
    var savedFen = originalPriceFen - groupPriceFen;
    var members = data.members || [];
    var displayMembers = members.slice(0, 5);
    var targetSize = data.target_size || 0;
    var currentSize = data.current_size || 0;
    var emptyCount = Math.max(0, Math.min(targetSize - currentSize, 5 - displayMembers.length));
    var emptySlots = [];
    for (var i = 0; i < emptyCount; i++) {
      emptySlots.push(i);
    }

    var banners = data.banners && data.banners.length > 0
      ? data.banners
      : ['/assets/placeholder-1.png', '/assets/placeholder-2.png', '/assets/placeholder-3.png'];

    var rules = data.rules && data.rules.length > 0
      ? data.rules
      : MOCK_DETAIL.rules;

    this.setData({
      detail: data,
      banners: banners,
      groupPriceYuan: (groupPriceFen / 100).toFixed(2),
      originalPriceYuan: (originalPriceFen / 100).toFixed(2),
      savedYuan: (savedFen / 100).toFixed(2),
      displayMembers: displayMembers,
      emptySlots: emptySlots,
      rules: rules
    });

    // 启动倒计时
    if (data.end_time && data.status === 'active') {
      this._startCountdown(data.end_time);
    }
  },

  // ─── 倒计时 ───
  _startCountdown: function (endTimeStr) {
    var self = this;
    if (self._timer) {
      clearInterval(self._timer);
    }

    var updateFn = function () {
      var now = Date.now();
      var end = new Date(endTimeStr).getTime();
      var diff = Math.max(0, Math.floor((end - now) / 1000));

      if (diff <= 0) {
        clearInterval(self._timer);
        self._timer = null;
        self.setData({
          countdown: { hours: '00', minutes: '00', seconds: '00' }
        });
        return;
      }

      var h = Math.floor(diff / 3600);
      var m = Math.floor((diff % 3600) / 60);
      var s = diff % 60;

      self.setData({
        countdown: {
          hours: h < 10 ? '0' + h : '' + h,
          minutes: m < 10 ? '0' + m : '' + m,
          seconds: s < 10 ? '0' + s : '' + s
        }
      });
    };

    updateFn();
    self._timer = setInterval(updateFn, 1000);
  },

  // ─── 参团 ───
  joinGroup: function () {
    var self = this;
    if (self.data.joining) return;

    var memberId = wx.getStorageSync('tx_customer_id') || '';
    if (!memberId) {
      wx.showToast({ title: '请先登录', icon: 'none' });
      return;
    }

    self.setData({ joining: true });
    api.txRequest('/api/v1/group-buy/join', 'POST', {
      campaign_id: self.data.campaignId,
      member_id: memberId,
      quantity: 1
    }).then(function () {
      self.setData({ joining: false, showSuccess: true });
      // 刷新详情
      self._loadDetail(self.data.campaignId);
    }).catch(function (err) {
      self.setData({ joining: false });
      var msg = (err && err.message) || '参团失败，请重试';
      wx.showToast({ title: msg, icon: 'none' });
    });
  },

  // ─── 展开/收起规则 ───
  toggleRules: function () {
    this.setData({ rulesExpanded: !this.data.rulesExpanded });
  },

  // ─── 关闭成功弹层 ───
  closeSuccess: function () {
    this.setData({ showSuccess: false });
  },

  // ─── 查看全部成员 ───
  viewAllMembers: function () {
    wx.showToast({ title: '查看全部成员', icon: 'none' });
  }
});
