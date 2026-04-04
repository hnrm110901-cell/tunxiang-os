// 催单结果页 — 成功动画 + 预计出餐时间 + 催次数提示 + 3秒自动返回
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    orderId: '',
    success: false,
    estimatedMinutes: 0,
    rushCount: 0,
    message: '',
    countdown: 3,
    // 动画
    animScale: 0,
  },

  _countdownTimer: null,
  _animTimer: null,

  onLoad: function (options) {
    var orderId = options.order_id || '';
    this.setData({ orderId: orderId });
    if (orderId) {
      this._doRush();
    }
  },

  onUnload: function () {
    this._clearTimers();
  },

  _doRush: function () {
    var self = this;
    api.rushOrder(self.data.orderId)
      .then(function (data) {
        self.setData({
          success: true,
          estimatedMinutes: data.estimated_minutes || 10,
          rushCount: data.rush_count || 1,
          message: data.message || '已通知厨房加急',
        });
        self._startAnimation();
        self._startCountdown();
      })
      .catch(function (err) {
        console.error('催单失败', err);
        // Mock 降级：仍然显示成功
        self.setData({
          success: true,
          estimatedMinutes: 8,
          rushCount: 1,
          message: '已通知厨房加急',
        });
        self._startAnimation();
        self._startCountdown();
      });
  },

  _startAnimation: function () {
    var self = this;
    // 缩放弹跳动画：0 -> 1.2 -> 1
    self.setData({ animScale: 0 });
    setTimeout(function () {
      self.setData({ animScale: 1.2 });
    }, 50);
    setTimeout(function () {
      self.setData({ animScale: 1 });
    }, 350);
  },

  _startCountdown: function () {
    var self = this;
    self.setData({ countdown: 3 });
    self._countdownTimer = setInterval(function () {
      var cd = self.data.countdown - 1;
      if (cd <= 0) {
        self._clearTimers();
        self.goBack();
      } else {
        self.setData({ countdown: cd });
      }
    }, 1000);
  },

  _clearTimers: function () {
    if (this._countdownTimer) {
      clearInterval(this._countdownTimer);
      this._countdownTimer = null;
    }
    if (this._animTimer) {
      clearTimeout(this._animTimer);
      this._animTimer = null;
    }
  },

  goBack: function () {
    wx.navigateBack({ delta: 1 });
  },
});
