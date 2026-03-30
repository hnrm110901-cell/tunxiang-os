// 排队取号页 — 选人数/显示等待/取号/轮询叫号
var app = getApp();
var api = require('../../utils/api.js');

Page({
  data: {
    guestOptions: [
      { label: '1-4人', value: '1-4', icon: '\ud83d\udc65' },
      { label: '5-8人', value: '5-8', icon: '\ud83d\udc68\u200d\ud83d\udc69\u200d\ud83d\udc67\u200d\ud83d\udc66' },
      { label: '9人以上', value: '9+', icon: '\ud83c\udf89' },
    ],
    selectedGuests: '',
    queueSummary: [],
    queueTicket: null,
    estimate: null,
    submitting: false,
    pollTimer: null,
  },

  onLoad: function () {
    this.loadQueueSummary();
    this.checkExistingTicket();
  },

  onUnload: function () {
    if (this.data.pollTimer) {
      clearInterval(this.data.pollTimer);
    }
  },

  onShow: function () {
    this.loadQueueSummary();
  },

  selectGuests: function (e) {
    var value = e.currentTarget.dataset.value;
    this.setData({ selectedGuests: value });
    this._loadEstimate(value);
  },

  _loadEstimate: function (guestRange) {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchQueueEstimate(storeId, guestRange)
      .then(function (data) {
        self.setData({
          estimate: {
            waiting: data.waiting || 0,
            estimateMin: data.estimate_min || 0,
          },
        });
      })
      .catch(function (err) {
        console.warn('loadEstimate failed', err);
        self.setData({ estimate: null });
      });
  },

  loadQueueSummary: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchQueueSummary(storeId)
      .then(function (data) {
        self.setData({ queueSummary: data.items || [] });
      })
      .catch(function (err) {
        console.error('loadQueueSummary failed', err);
      });
  },

  checkExistingTicket: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchMyTicket(storeId)
      .then(function (data) {
        if (data) {
          self.setData({ queueTicket: data });
          self.startPolling();
        }
      })
      .catch(function (err) {
        console.error('checkExistingTicket failed', err);
      });
  },

  takeNumber: function () {
    var self = this;
    if (!self.data.selectedGuests) {
      wx.showToast({ title: '请选择用餐人数', icon: 'none' });
      return;
    }
    self.setData({ submitting: true });

    var storeId = app.globalData.storeId;
    api.takeQueue(storeId, self.data.selectedGuests)
      .then(function (data) {
        wx.showToast({ title: '取号成功', icon: 'success' });
        self.setData({ queueTicket: data, submitting: false });
        self.startPolling();
      })
      .catch(function (err) {
        console.error('takeNumber failed', err);
        wx.showToast({ title: err.message || '取号失败', icon: 'none' });
        self.setData({ submitting: false });
      });
  },

  startPolling: function () {
    var self = this;
    if (self.data.pollTimer) clearInterval(self.data.pollTimer);
    var timer = setInterval(function () {
      self.refreshTicketStatus();
    }, 10000);
    self.setData({ pollTimer: timer });
  },

  refreshTicketStatus: function () {
    var self = this;
    var storeId = app.globalData.storeId;
    api.fetchMyTicket(storeId)
      .then(function (data) {
        if (data) {
          self.setData({ queueTicket: data });
          if (data.status === 'called') {
            // 叫号提醒
            wx.showModal({
              title: '叫号通知',
              content: '您的号码 ' + data.ticketNo + ' 已到，请前往就座！',
              showCancel: false,
              confirmColor: '#FF6B2C',
            });
            // 振动提示
            wx.vibrateShort({ type: 'heavy' });
            clearInterval(self.data.pollTimer);
            self.setData({ pollTimer: null });
          }
        } else {
          self.setData({ queueTicket: null });
          clearInterval(self.data.pollTimer);
          self.setData({ pollTimer: null });
        }
      })
      .catch(function (err) {
        console.error('refreshTicketStatus failed', err);
      });
  },

  cancelQueue: function () {
    var self = this;
    wx.showModal({
      title: '提示',
      content: '确定取消排队？',
      confirmColor: '#FF6B2C',
      success: function (res) {
        if (!res.confirm) return;
        var ticket = self.data.queueTicket;
        api.cancelQueueTicket(ticket.id)
          .then(function () {
            wx.showToast({ title: '已取消', icon: 'success' });
            if (self.data.pollTimer) {
              clearInterval(self.data.pollTimer);
            }
            self.setData({ queueTicket: null, pollTimer: null });
            self.loadQueueSummary();
          })
          .catch(function (err) {
            console.error('cancelQueue failed', err);
            wx.showToast({ title: '取消失败', icon: 'none' });
          });
      },
    });
  },
});
