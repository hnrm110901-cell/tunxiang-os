// 大厨到家订单跟踪 — 厨师出发→到达→烹饪→完成
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    bookingId: '',
    booking: null,
    loading: true,
    // 状态流程
    statusSteps: [
      { key: 'confirmed', label: '已确认', icon: '✓' },
      { key: 'chef_departed', label: '厨师出发', icon: '🚗' },
      { key: 'chef_arrived', label: '厨师到达', icon: '📍' },
      { key: 'cooking', label: '烹饪中', icon: '🔥' },
      { key: 'completed', label: '已完成', icon: '✨' },
    ],
    currentStepIndex: 0,
    // 评价
    showRating: false,
    ratingScore: 5,
    ratingComment: '',
    submittingRating: false,
    // 定时刷新
    refreshTimer: null,
  },

  onLoad: function (options) {
    if (options.booking_id) {
      this.setData({ bookingId: options.booking_id });
      this.loadBooking(options.booking_id);
      this._startAutoRefresh();
    }
  },

  onUnload: function () {
    this._stopAutoRefresh();
  },

  onShareAppMessage: function () {
    return { title: '徐记海鲜 · 大厨到家订单', path: '/pages/chef-at-home/index' };
  },

  loadBooking: function (bookingId) {
    var self = this;
    var id = bookingId || self.data.bookingId;

    api.txRequest('/api/v1/chef-at-home/bookings?customer_id=' + (wx.getStorageSync('tx_customer_id') || ''))
      .then(function (data) {
        var items = data.items || [];
        var booking = null;
        for (var i = 0; i < items.length; i++) {
          if (items[i].id === id) {
            booking = items[i];
            break;
          }
        }
        if (booking) {
          var stepIndex = self._getStepIndex(booking.status);
          self.setData({
            booking: booking,
            loading: false,
            currentStepIndex: stepIndex,
            showRating: booking.status === 'completed',
          });
        } else {
          self.setData({ loading: false });
        }
      })
      .catch(function (err) {
        console.error('loadBooking failed', err);
        self.setData({ loading: false });
      });
  },

  _getStepIndex: function (status) {
    var steps = this.data.statusSteps;
    for (var i = 0; i < steps.length; i++) {
      if (steps[i].key === status) return i;
    }
    if (status === 'rated') return steps.length - 1;
    return 0;
  },

  _startAutoRefresh: function () {
    var self = this;
    self.data.refreshTimer = setInterval(function () {
      if (self.data.booking && (self.data.booking.status === 'completed' || self.data.booking.status === 'rated')) {
        self._stopAutoRefresh();
        return;
      }
      self.loadBooking();
    }, 15000); // 每15秒刷新
  },

  _stopAutoRefresh: function () {
    if (this.data.refreshTimer) {
      clearInterval(this.data.refreshTimer);
      this.data.refreshTimer = null;
    }
  },

  // 评价相关
  setRating: function (e) {
    this.setData({ ratingScore: Number(e.currentTarget.dataset.score) });
  },

  onCommentInput: function (e) {
    this.setData({ ratingComment: e.detail.value });
  },

  submitRating: function () {
    var self = this;
    self.setData({ submittingRating: true });

    api.txRequest('/api/v1/chef-at-home/bookings/' + self.data.bookingId + '/rate', 'PUT', {
      rating: self.data.ratingScore,
      comment: self.data.ratingComment,
    }).then(function (data) {
      wx.showToast({ title: '评价成功', icon: 'success' });
      self.setData({
        booking: data,
        showRating: false,
        submittingRating: false,
      });
    }).catch(function (err) {
      wx.showToast({ title: err.message || '评价失败', icon: 'none' });
      self.setData({ submittingRating: false });
    });
  },

  callChef: function () {
    var booking = this.data.booking;
    if (booking && booking.chef_phone) {
      wx.makePhoneCall({ phoneNumber: booking.chef_phone });
    } else {
      wx.showToast({ title: '暂无厨师电话', icon: 'none' });
    }
  },

  goBack: function () {
    wx.navigateBack({ fail: function () { wx.switchTab({ url: '/pages/order/order' }); } });
  },
});
